"""Cross-snapshot digest binding validation for journaled commits."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core_tools.persistence import PersistenceError

from top_down_planning.config import compute_input_digest, compute_output_goal_digest
from top_down_planning.config.context import compute_context_snapshot_digest_from_payload
from top_down_planning.config.context_digests import compute_context_spec_digest_from_config
from top_down_planning.domain.run_kind import RUN_KIND_SUB_TDP_EXECUTION, resolve_run_kind
from top_down_planning.config.resolve import compute_unit_output_goal_digest
from top_down_planning.domain.models import Plan
from top_down_planning.persistence.digests import (
    compute_config_contract_digest,
    compute_config_execution_digest,
    compute_output_digest,
    compute_plan_digest,
)


def _expected_output_goal_digest(
    run: dict[str, Any],
    plan: dict[str, Any],
    resolved_config: dict[str, Any],
    *,
    workspace: Path,
) -> str:
    try:
        if resolve_run_kind(run) == RUN_KIND_SUB_TDP_EXECUTION:
            return compute_unit_output_goal_digest(Plan.from_dict(plan).output_goal)
    except ValueError:
        pass
    return compute_output_goal_digest(resolved_config, base_dir=workspace)


def validate_snapshot_digest_bindings(
    run: dict[str, Any],
    *,
    plan: dict[str, Any],
    production: dict[str, Any],
    resolved_config: dict[str, Any],
    workspace: Path,
) -> None:
    """Require run digest fields to match the prospective canonical snapshots."""

    digests = run.get("digests")
    if not isinstance(digests, dict):
        raise PersistenceError("run.digests must be an object")

    expected_plan = str(digests.get("plan") or "").strip()
    actual_plan = compute_plan_digest(plan)
    if not expected_plan or actual_plan != expected_plan:
        raise PersistenceError("run.digests.plan does not match plan snapshot")

    expected_contract = str(digests.get("config_contract") or "").strip()
    actual_contract = compute_config_contract_digest(resolved_config)
    if not expected_contract or actual_contract != expected_contract:
        raise PersistenceError(
            "run.digests.config_contract does not match resolved-config snapshot"
        )

    expected_execution = str(digests.get("config_execution") or "").strip()
    actual_execution = compute_config_execution_digest(resolved_config)
    if not expected_execution or actual_execution != expected_execution:
        raise PersistenceError(
            "run.digests.config_execution does not match resolved-config snapshot"
        )

    expected_input = str(digests.get("input") or "").strip()
    actual_input = compute_input_digest(resolved_config, base_dir=workspace)
    if not expected_input or actual_input != expected_input:
        raise PersistenceError("run.digests.input does not match resolved-config snapshot")

    expected_output_goal = str(digests.get("output_goal") or "").strip()
    actual_output_goal = _expected_output_goal_digest(
        run,
        plan,
        resolved_config,
        workspace=workspace,
    )
    if not expected_output_goal or actual_output_goal != expected_output_goal:
        raise PersistenceError(
            "run.digests.output_goal does not match resolved-config snapshot"
        )

    expected_context_spec = str(digests.get("context_spec") or "").strip()
    actual_context_spec = compute_context_spec_digest_from_config(
        resolved_config,
        workspace=workspace,
    )
    if not expected_context_spec or actual_context_spec != expected_context_spec:
        raise PersistenceError(
            "run.digests.context_spec does not match resolved-config snapshot"
        )

    binding = run.get("context_snapshot_binding")
    if not isinstance(binding, dict):
        raise PersistenceError("context_snapshot_binding is required on schema v3 run records")
    expected_context_snapshot = str(digests.get("context_snapshot") or "").strip()
    actual_context_snapshot = compute_context_snapshot_digest_from_payload(binding)
    if not expected_context_snapshot or actual_context_snapshot != expected_context_snapshot:
        raise PersistenceError(
            "run.digests.context_snapshot does not match context_snapshot_binding"
        )

    output_digest = str(digests.get("output") or "").strip()
    if output_digest:
        actual_output = compute_output_digest(production)
        if actual_output != output_digest:
            raise PersistenceError(
                "run.digests.output does not match production snapshot"
            )


def bind_run_digests_for_plan_update(
    run: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    """Return a run payload with ``digests.plan`` updated for a plan revision bump."""

    run_patch = dict(run)
    digests = dict(run_patch.get("digests") or {})
    digests["plan"] = compute_plan_digest(plan)
    run_patch["digests"] = digests
    return run_patch


def bind_run_digests_for_production_update(
    run: dict[str, Any],
    production: dict[str, Any],
) -> dict[str, Any]:
    """Return a run payload with ``digests.output`` updated when output binding exists."""

    run_patch = dict(run)
    digests = dict(run_patch.get("digests") or {})
    if str(digests.get("output") or "").strip():
        digests["output"] = compute_output_digest(production)
    run_patch["digests"] = digests
    return run_patch


def bind_run_digests_for_config_update(
    run: dict[str, Any],
    resolved_config: dict[str, Any],
    *,
    workspace: Path | None = None,
) -> dict[str, Any]:
    """Return a run payload with config-derived digest fields updated."""

    run_patch = dict(run)
    digests = dict(run_patch.get("digests") or {})
    digests["config_contract"] = compute_config_contract_digest(resolved_config)
    digests["config_execution"] = compute_config_execution_digest(resolved_config)
    if workspace is not None:
        digests["input"] = compute_input_digest(resolved_config, base_dir=workspace)
        digests["context_spec"] = compute_context_spec_digest_from_config(
            resolved_config,
            workspace=workspace,
        )
    run_patch["digests"] = digests
    return run_patch
