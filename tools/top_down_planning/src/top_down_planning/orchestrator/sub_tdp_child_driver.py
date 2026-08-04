"""Drive a single Sub-TDP child run in-process."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from core_tools.config import load_yaml_config
from core_tools.provider import Provider

from top_down_planning.config import (
    build_initial_context_snapshot_binding_with_diagnostics,
    compute_input_digest,
    compute_output_goal_digest,
    resolve_output_goal_text,
    resolve_workspace,
)
from top_down_planning.config.execution import assert_child_execution_allowed
from top_down_planning.domain.approval_digests import PLAN_APPROVAL_DIGEST_KEYS
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID, seed_plan_root_item
from top_down_planning.domain.session_bindings import reviewer_binding_for_provider_session
from top_down_planning.domain.sub_tdp_artifacts import orchestration_root_relative
from top_down_planning.domain.sub_tdp_units import SubTdpUnit
from top_down_planning.orchestrator.apply_resume import apply_resume_plan_atomically
from top_down_planning.orchestrator.phases import OUTPUT_VALIDATED, PLAN_VALIDATED
from top_down_planning.orchestrator.prepare_resume import prepare_resume
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.digests import compute_plan_digest
from top_down_planning.persistence.path_ids import new_run_id

ProviderFactory = Callable[[dict[str, Any], Path], Provider]

_CHILD_INVOCATION: dict[str, Any] = {
    "observability": {
        "color": "never",
        "log_level": "quiet",
        "log_format": "console",
        "agent_text": False,
        "timestamps": False,
        "agent_transcript": False,
        "max_message_length": None,
        "max_tool_summary_length": None,
    },
    "runs_dir": {"path": "", "source": "sub_tdp_child"},
    "stream_json": False,
    "until": "completed",
    "command": "sub_tdp_child",
}


def unit_relative_directory(
    unit: SubTdpUnit,
    *,
    state_file: str | None = None,
) -> str:
    root_rel = orchestration_root_relative(state_file)
    return f"{root_rel}/{unit.directory}"


def child_runs_store_path(
    workspace: Path,
    unit: SubTdpUnit,
    *,
    state_file: str | None = None,
) -> Path:
    unit_rel = unit_relative_directory(unit, state_file=state_file)
    return workspace / unit_rel / "runs"


def child_unit_directory(
    workspace: Path,
    unit: SubTdpUnit,
    *,
    state_file: str | None = None,
) -> Path:
    return workspace / unit_relative_directory(unit, state_file=state_file)


def load_child_resolved_config(unit_dir: Path) -> dict[str, Any]:
    config_path = unit_dir / "config.yaml"
    if not config_path.is_file():
        raise ValueError(f"child config missing: {config_path}")
    return load_yaml_config(config_path)


def build_minimal_child_plan(unit: SubTdpUnit, *, output_goal: str) -> Plan:
    root = seed_plan_root_item()
    work = PlanItem(
        id=unit.plan_item_id,
        parent_id=PLAN_ROOT_ITEM_ID,
        order_key="0000000000",
        title=unit.title,
        outcome=unit.outcome,
        kind="work",
    )
    return Plan(
        id=f"plan-sub-tdp-{unit.plan_item_id}",
        revision=0,
        output_goal=output_goal,
        items={
            PLAN_ROOT_ITEM_ID: root,
            unit.plan_item_id: work,
        },
    )


def synthetic_whole_plan_approval(store: FileRunStore, run_id: str) -> dict[str, Any]:
    run = store.load_run(run_id)
    plan = store.load_plan(run_id)
    plan_revision = int(plan["revision"])
    digests = {
        str(key): str(value)
        for key, value in (run.get("digests") or {}).items()
        if key in PLAN_APPROVAL_DIGEST_KEYS and value
    }
    plan_digest = compute_plan_digest(plan)
    digests["plan"] = plan_digest
    loop_id = f"review-whole-plan-{run_id}"
    binding = reviewer_binding_for_provider_session(
        "sub-tdp-child-reviewer",
        instance_seed=loop_id,
    )
    return {
        "id": loop_id,
        "type": "whole_plan",
        "revise_at": "blocker",
        "review_record_schema_version": 2,
        "review_contract_version": 2,
        "reviewer_binding": binding.to_dict() if binding is not None else None,
        "target_revision": plan_revision,
        "scope": {"kind": "whole_plan"},
        "status": "approved",
        "findings": [],
        "revision_cycles": 0,
        "approved_digests": digests,
        "lifecycle_status": "approved",
        "active_stage": "scope_review",
        "scope_review_rounds": 1,
        "scope_review_result": {
            "stage": "scope_review",
            "target_digest": plan_digest,
            "scope_id": "whole_plan",
            "decision": "approved",
            "reported_findings": [],
            "acceptance_criteria_checked": ["Sub-TDP child plan approved by orchestrator"],
            "summary": "Sub-TDP child plan pre-approved.",
        },
    }


def create_child_run(
    child_store: FileRunStore,
    unit: SubTdpUnit,
    *,
    child_config: dict[str, Any],
    workspace: Path,
) -> str:
    workspace = workspace.resolve()
    assert_child_execution_allowed(child_config)
    resolved_workspace = resolve_workspace(child_config, cwd=workspace)
    output_goal = resolve_output_goal_text(child_config, base_dir=resolved_workspace)
    plan = build_minimal_child_plan(unit, output_goal=output_goal)
    binding, context_spec_digest, context_snapshot_digest, _ = (
        build_initial_context_snapshot_binding_with_diagnostics(
            child_config,
            workspace=resolved_workspace,
        )
    )
    run_id = new_run_id()
    invocation = dict(_CHILD_INVOCATION)
    invocation["runs_dir"] = {
        "path": str(child_store.root.resolve()),
        "source": "sub_tdp_child",
    }
    child_store.create_run(
        run_id,
        plan=plan,
        resolved_config=child_config,
        input_digest=compute_input_digest(child_config, base_dir=resolved_workspace),
        output_goal_digest=compute_output_goal_digest(child_config, base_dir=resolved_workspace),
        context_spec_digest=context_spec_digest,
        context_snapshot_digest=context_snapshot_digest,
        context_snapshot_binding=binding,
        phase=PLAN_VALIDATED,
        workspace=str(resolved_workspace),
        invocation=invocation,
    )
    child_store.save_review(run_id, synthetic_whole_plan_approval(child_store, run_id))
    return run_id


def _child_run_terminal(child_run: dict[str, Any]) -> bool:
    return (
        str(child_run.get("status") or "") == "completed"
        and str(child_run.get("phase") or "") == OUTPUT_VALIDATED
    )


def continue_child_sub_tdp(
    child_store: FileRunStore,
    child_run_id: str,
    *,
    create_provider: ProviderFactory,
    workspace: Path,
) -> dict[str, Any]:
    child_run = child_store.load_run(child_run_id)
    if _child_run_terminal(child_run):
        return child_run

    child_config = child_store.load_resolved_config(child_run_id)
    resolved_workspace = resolve_workspace(child_config, cwd=workspace.resolve())

    if str(child_run.get("status") or "") == "paused":
        resume_plan = prepare_resume(child_store, child_run_id, child_config)
        apply_resume_plan_atomically(
            child_store,
            resume_plan,
            resolved_config=child_config,
        )

    from top_down_planning.orchestrator.engine import RunEngine

    engine = RunEngine(child_store, create_provider=create_provider)
    result = engine.continue_run(child_run_id, until="completed")
    child_run = child_store.load_run(child_run_id)
    if not result.ok and str(child_run.get("status") or "") == "paused":
        return child_run
    if str(child_run.get("phase") or "") == OUTPUT_VALIDATED:
        return child_run
    if not result.ok:
        raise RuntimeError(
            f"child Sub-TDP run {child_run_id} did not complete: {result.reason}"
        )
    return child_run


__all__ = [
    "build_minimal_child_plan",
    "child_runs_store_path",
    "child_unit_directory",
    "continue_child_sub_tdp",
    "create_child_run",
    "load_child_resolved_config",
    "synthetic_whole_plan_approval",
    "unit_relative_directory",
]
