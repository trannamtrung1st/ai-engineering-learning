"""Create prepared parent and child execution runs from verified packages (proposal §12, §17)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from top_down_planning.config import (
    compute_input_digest,
    compute_output_goal_digest,
    compute_unit_output_goal_digest,
)
from top_down_planning.config.context_digests import (
    build_initial_context_snapshot_binding_with_diagnostics,
)
from top_down_planning.domain.models import Plan
from top_down_planning.domain.run_kind import (
    RUN_KIND_PARENT_EXECUTION,
    RUN_KIND_SUB_TDP_EXECUTION,
)
from top_down_planning.orchestrator.phases import PLAN_VALIDATED
from top_down_planning.package.execution_validation import (
    validate_resolved_config_against_package,
    verify_package_authoritative_inputs,
)
from top_down_planning.package.loader import LoadedExecutionPackage, LoadedUnit
from top_down_planning.package.store_persist import persist_package_in_store
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.path_ids import new_run_id


def inherited_whole_plan_approval(
    *,
    run_id: str,
    plan: Plan,
    package_manifest: dict[str, Any],
    run_digests: dict[str, str],
) -> dict[str, Any]:
    """Persist the packaged inherited approval attestation — not a reviewer session."""

    planning_run = package_manifest.get("planning_run") or {}
    attestation = planning_run.get("inherited_plan_approval")
    if not isinstance(attestation, dict) or not attestation:
        raise ValueError(
            "prepared package missing planning_run.inherited_plan_approval attestation"
        )
    record = copy.deepcopy(attestation)
    record["plan_source"] = "prepared_package"
    record["plan_review_inherited"] = True
    record["inherited_plan_approval"] = True
    # Distinct schema marker — never invent a child reviewer binding.
    record.pop("reviewer_binding", None)
    if not record.get("id"):
        record["id"] = str(
            planning_run.get("whole_plan_review_id")
            or f"inherited-plan-approval-{run_id}"
        )
    approved = dict(record.get("approved_digests") or {})
    approved.update(
        {str(key): str(value) for key, value in run_digests.items() if value}
    )
    record["approved_digests"] = approved
    record["target_revision"] = int(plan.revision)
    return record


def package_binding_from_manifest(
    manifest: dict[str, Any],
    *,
    manifest_path: Path,
    selected_unit_id: str | None = None,
    unit_record: LoadedUnit | None = None,
) -> dict[str, Any]:
    planning_run = manifest.get("planning_run") or {}
    binding: dict[str, Any] = {
        "manifest_path": str(manifest_path.resolve()),
        "package_id": str(manifest.get("package_id") or ""),
        "package_digest": str(manifest.get("package_digest") or ""),
        "planning_run_id": str(planning_run.get("run_id") or ""),
        "parent_plan_digest": str((manifest.get("parent") or {}).get("plan_digest") or ""),
        "approved_parent_plan_digest": str(
            planning_run.get("approved_plan_digest") or ""
        ),
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
        verify_package_authoritative_inputs(package)
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
        persisted_manifest = persist_package_in_store(store.root, package)
        package_binding = package_binding_from_manifest(
            package.manifest,
            manifest_path=persisted_manifest,
            selected_unit_id=selected_unit_id,
            unit_record=unit_record,
        )
        parent_output_goal_digest = compute_output_goal_digest(
            resolved_config, base_dir=workspace
        )
        if run_kind == RUN_KIND_SUB_TDP_EXECUTION:
            unit_goal = str(plan.output_goal or "").strip()
            unit_goal_digest = compute_unit_output_goal_digest(unit_goal)
            package_binding["unit_output_goal"] = unit_goal
            package_binding["unit_output_goal_digest"] = unit_goal_digest
            package_binding["parent_output_goal_digest"] = parent_output_goal_digest
            output_goal_digest = unit_goal_digest
            sub_tdp = (invocation or {}).get("sub_tdp") or {}
            if not isinstance(sub_tdp, dict):
                sub_tdp = {}
            parent_run_id = str(sub_tdp.get("parent_run_id") or "").strip() or "direct"
            unit_id = str(
                sub_tdp.get("unit_id") or selected_unit_id or ""
            ).strip()
            if unit_id:
                package_binding["creation_key"] = (
                    f"{package_binding['package_digest']}:{parent_run_id}:{unit_id}"
                )
        else:
            output_goal_digest = parent_output_goal_digest
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
            output_goal_digest=output_goal_digest,
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
