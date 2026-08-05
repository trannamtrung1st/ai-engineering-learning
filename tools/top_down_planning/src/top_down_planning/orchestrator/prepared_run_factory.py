"""Create prepared parent and child execution runs from verified packages (proposal §12, §17)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from top_down_planning.config import (
    build_initial_context_snapshot_binding_with_diagnostics,
    compute_input_digest,
    compute_output_goal_digest,
    resolve_workspace,
)
from top_down_planning.domain.approval_digests import PLAN_APPROVAL_DIGEST_KEYS
from top_down_planning.domain.models import Plan
from top_down_planning.domain.run_kind import (
    RUN_KIND_PARENT_EXECUTION,
    RUN_KIND_SUB_TDP_EXECUTION,
)
from top_down_planning.domain.session_bindings import reviewer_binding_for_provider_session
from top_down_planning.orchestrator.phases import PLAN_VALIDATED
from top_down_planning.package.loader import LoadedExecutionPackage, LoadedUnit
from top_down_planning.persistence import FileRunStore
from top_down_planning.package.execution_validation import validate_resolved_config_against_package
from top_down_planning.persistence.digests import compute_plan_digest
from top_down_planning.persistence.path_ids import new_run_id


def inherited_whole_plan_approval(
    *,
    run_id: str,
    plan: Plan,
    package_manifest: dict[str, Any],
    run_digests: dict[str, str],
) -> dict[str, Any]:
    """Package-derived inherited approval — not a new reviewer session."""

    plan_revision = int(plan.revision)
    digests = {
        str(key): str(value)
        for key, value in run_digests.items()
        if key in PLAN_APPROVAL_DIGEST_KEYS and value
    }
    plan_digest = compute_plan_digest(plan)
    digests["plan"] = plan_digest
    planning_run = package_manifest.get("planning_run") or {}
    loop_id = str(planning_run.get("whole_plan_review_id") or f"review-whole-plan-{run_id}")
    binding = reviewer_binding_for_provider_session(
        "prepared-package-reviewer",
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
            "acceptance_criteria_checked": [
                "Plan approved in planning run and verified via execution package lineage",
            ],
            "summary": "Inherited prepared-package plan approval.",
        },
        "plan_source": "prepared_package",
        "plan_review_inherited": True,
    }


def package_binding_from_manifest(
    manifest: dict[str, Any],
    *,
    manifest_path: Path,
    selected_unit_id: str | None = None,
    unit_record: LoadedUnit | None = None,
) -> dict[str, Any]:
    binding: dict[str, Any] = {
        "manifest_path": str(manifest_path.resolve()),
        "package_id": str(manifest.get("package_id") or ""),
        "package_digest": str(manifest.get("package_digest") or ""),
        "planning_run_id": str((manifest.get("planning_run") or {}).get("run_id") or ""),
        "parent_plan_digest": str((manifest.get("parent") or {}).get("plan_digest") or ""),
        "selected_unit_id": selected_unit_id,
    }
    if unit_record is not None:
        binding["unit_id"] = unit_record.unit_id
        binding["unit_plan_digest"] = unit_record.plan_digest
        binding["assigned_subtree_digest"] = unit_record.assigned_subtree_digest
    return binding


class PreparedRunFactory:
    """Create execution-only runs from a verified package."""

    def create_parent_run(
        self,
        store: FileRunStore,
        package: LoadedExecutionPackage,
        *,
        resolved_config: dict[str, Any],
        invocation: dict[str, Any],
    ) -> str:
        return self._create_prepared_run(
            store,
            package,
            plan=package.parent_plan,
            run_kind=RUN_KIND_PARENT_EXECUTION,
            resolved_config=resolved_config,
            invocation=invocation,
            selected_unit_id=None,
            unit_record=None,
        )

    def create_child_run(
        self,
        store: FileRunStore,
        package: LoadedExecutionPackage,
        unit: LoadedUnit,
        *,
        resolved_config: dict[str, Any],
        invocation: dict[str, Any],
    ) -> str:
        return self._create_prepared_run(
            store,
            package,
            plan=unit.plan,
            run_kind=RUN_KIND_SUB_TDP_EXECUTION,
            resolved_config=resolved_config,
            invocation=invocation,
            selected_unit_id=unit.unit_id,
            unit_record=unit,
        )

    def _create_prepared_run(
        self,
        store: FileRunStore,
        package: LoadedExecutionPackage,
        *,
        plan: Plan,
        run_kind: str,
        resolved_config: dict[str, Any],
        invocation: dict[str, Any],
        selected_unit_id: str | None,
        unit_record: LoadedUnit | None,
    ) -> str:
        workspace = package.workspace_path
        validate_resolved_config_against_package(
            resolved_config,
            package,
            workspace=workspace,
        )
        binding, context_spec_digest, context_snapshot_digest, _ = (
            build_initial_context_snapshot_binding_with_diagnostics(
                resolved_config,
                workspace=workspace,
            )
        )
        run_id = new_run_id()
        package_binding = package_binding_from_manifest(
            package.manifest,
            manifest_path=package.manifest_path,
            selected_unit_id=selected_unit_id,
            unit_record=unit_record,
        )
        run_record_extras = {
            "run_kind": run_kind,
            "package_binding": package_binding,
            "plan_source": "prepared_package",
            "plan_review_inherited": True,
        }
        store.create_run(
            run_id,
            plan=plan,
            resolved_config=resolved_config,
            input_digest=compute_input_digest(resolved_config, base_dir=workspace),
            output_goal_digest=compute_output_goal_digest(resolved_config, base_dir=workspace),
            context_spec_digest=context_spec_digest,
            context_snapshot_digest=context_snapshot_digest,
            context_snapshot_binding=binding,
            phase=PLAN_VALIDATED,
            workspace=str(workspace),
            invocation=invocation,
            run_extras=run_record_extras,
        )
        run = store.load_run(run_id)
        store.save_review(
            run_id,
            inherited_whole_plan_approval(
                run_id=run_id,
                plan=plan,
                package_manifest=package.manifest,
                run_digests=dict(run.get("digests") or {}),
            ),
        )
        return run_id


__all__ = [
    "PreparedRunFactory",
    "inherited_whole_plan_approval",
    "package_binding_from_manifest",
]
