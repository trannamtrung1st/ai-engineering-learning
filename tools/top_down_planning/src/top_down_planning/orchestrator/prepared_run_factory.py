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
from top_down_planning.config.context import compute_context_spec_digest_from_config
from top_down_planning.domain.models import Plan
from top_down_planning.domain.run_kind import (
    RUN_KIND_PARENT_EXECUTION,
    RUN_KIND_SUB_TDP_EXECUTION,
)
from top_down_planning.orchestrator.phases import PLAN_VALIDATED
from top_down_planning.package.execution_validation import (
    validate_resolved_config_against_package,
    verify_package_authoritative_inputs,
    verify_package_context_snapshot_with_baseline,
    verify_package_immutable_contract,
)
from top_down_planning.package.loader import (
    ExecutionPackageError,
    LoadedExecutionPackage,
    LoadedUnit,
)
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
        upstream_accepted_results: list[dict[str, Any]] | None = None,
        workspace_baseline_results: list[dict[str, Any]] | None = None,
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
            upstream_accepted_results=upstream_accepted_results,
            workspace_baseline_results=workspace_baseline_results,
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
        upstream_accepted_results: list[dict[str, Any]] | None = None,
        workspace_baseline_results: list[dict[str, Any]] | None = None,
    ) -> str:
        workspace = package.workspace_path
        upstream = list(upstream_accepted_results or [])
        if (
            run_kind == RUN_KIND_SUB_TDP_EXECUTION
            and unit_record is not None
            and unit_record.depends_on
            and not upstream
        ):
            raise ExecutionPackageError(
                f"unit {unit_record.unit_id!r} depends_on requires upstream_accepted_results",
                code="sub_tdp_upstream_invalid",
            )
        if workspace_baseline_results is not None:
            baseline_for_auth = list(workspace_baseline_results)
        else:
            baseline_for_auth = list(upstream)
        if baseline_for_auth:
            verify_package_immutable_contract(package)
            binding = verify_package_context_snapshot_with_baseline(
                package,
                store=store,
                baseline_wrappers=baseline_for_auth,
            )
        else:
            binding = verify_package_authoritative_inputs(package)
        validate_resolved_config_against_package(
            resolved_config,
            package,
            workspace=workspace,
        )
        from top_down_planning.config.context import (
            compute_context_snapshot_digest_from_payload,
        )

        context_snapshot_digest = compute_context_snapshot_digest_from_payload(binding)
        context_spec_digest = compute_context_spec_digest_from_config(
            resolved_config,
            workspace=workspace,
        )
        if run_kind == RUN_KIND_SUB_TDP_EXECUTION:
            from top_down_planning.package.execution_validation import (
                verify_merged_baseline_workspace_bytes,
            )
            from top_down_planning.package.lineage import (
                verify_upstream_wrapper_matches_live_delivery,
                verify_baseline_wrapper_matches_current_package,
            )

            package_id = str(package.manifest.get("package_id") or "").strip()
            package_digest = str(package.manifest.get("package_digest") or "").strip()
            for wrapper in baseline_for_auth:
                try:
                    verify_upstream_wrapper_matches_live_delivery(store, wrapper)
                    verify_baseline_wrapper_matches_current_package(
                        wrapper,
                        package_id=package_id,
                        package_digest=package_digest,
                        package_units=package.units,
                    )
                except (OSError, ValueError, KeyError) as exc:
                    raise ExecutionPackageError(
                        f"workspace baseline wrapper delivery invalid: {exc}",
                        code="sub_tdp_upstream_invalid",
                    ) from exc
            if baseline_for_auth:
                expected_snapshot = str(
                    (package.manifest.get("context") or {}).get("context_snapshot_digest")
                    or ""
                )
                try:
                    verify_merged_baseline_workspace_bytes(
                        baseline_for_auth,
                        workspace=workspace,
                        initial_snapshot_digest=expected_snapshot,
                        resolved_config=resolved_config,
                        unit_depends_on={
                            uid: list(u.depends_on) for uid, u in package.units.items()
                        },
                    )
                except ExecutionPackageError as exc:
                    raise ExecutionPackageError(
                        f"workspace baseline bytes invalid: {exc}",
                        code="sub_tdp_upstream_invalid",
                    ) from exc
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
            package_binding["upstream_accepted_results"] = list(upstream)
            package_binding["workspace_baseline_accepted_results"] = list(
                baseline_for_auth
            )
            expected_initial = str(
                (package.manifest.get("context") or {}).get("context_snapshot_digest")
                or ""
            )
            from top_down_planning.package.lineage import (
                baseline_accepted_result_digests_from_wrappers,
            )

            package_binding["baseline_accepted_result_digests"] = (
                baseline_accepted_result_digests_from_wrappers(baseline_for_auth)
            )
            if (
                not package_binding["baseline_accepted_result_digests"]
                and context_snapshot_digest != expected_initial
            ):
                raise ExecutionPackageError(
                    "child with empty baseline_accepted_result_digests must be at "
                    "package initial snapshot",
                    code="sub_tdp_upstream_invalid",
                )
            package_binding["external_prerequisites"] = list(
                unit_record.external_prerequisites if unit_record else []
            )
            package_binding["baseline_context_snapshot_digest"] = context_snapshot_digest
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
