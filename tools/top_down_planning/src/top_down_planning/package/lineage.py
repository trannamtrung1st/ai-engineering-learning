"""Verify child-to-parent lineage for attach operations (proposal §14)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from top_down_planning.domain.run_kind import RUN_KIND_SUB_TDP_EXECUTION, resolve_run_kind
from top_down_planning.orchestrator.phases import OUTPUT_VALIDATED
from top_down_planning.package.loader import LoadedExecutionPackage


@dataclass(frozen=True)
class LineageMismatch:
    field: str
    expected: str
    actual: str


class ExecutionLineageValidator:
    """Validate independently executed children against parent orchestration."""

    def validate_attach(
        self,
        *,
        parent_package: LoadedExecutionPackage,
        parent_manifest_digest: str,
        child_run: dict[str, Any],
        child_status_attachable: bool = True,
    ) -> list[LineageMismatch]:
        mismatches: list[LineageMismatch] = []
        if resolve_run_kind(child_run) != RUN_KIND_SUB_TDP_EXECUTION:
            mismatches.append(
                LineageMismatch("run_kind", RUN_KIND_SUB_TDP_EXECUTION, resolve_run_kind(child_run))
            )

        binding = child_run.get("package_binding") or {}
        if not isinstance(binding, dict):
            binding = {}

        child_package_id = str(binding.get("package_id") or "")
        parent_package_id = str(parent_package.manifest.get("package_id") or "")
        if child_package_id != parent_package_id:
            mismatches.append(
                LineageMismatch("package_id", parent_package_id, child_package_id)
            )

        child_package_digest = str(binding.get("package_digest") or "")
        parent_package_digest = str(parent_package.manifest.get("package_digest") or "")
        if child_package_digest != parent_package_digest:
            mismatches.append(
                LineageMismatch("package_digest", parent_package_digest, child_package_digest)
            )

        unit_id = str(binding.get("selected_unit_id") or binding.get("unit_id") or "")
        if unit_id not in parent_package.units:
            mismatches.append(LineageMismatch("unit_id", "known unit", unit_id or "<missing>"))
        else:
            unit_record = parent_package.units[unit_id]
            child_unit_digest = str(binding.get("unit_plan_digest") or "")
            if child_unit_digest != unit_record.plan_digest:
                mismatches.append(
                    LineageMismatch(
                        "unit_plan_digest",
                        unit_record.plan_digest,
                        child_unit_digest,
                    )
                )
            child_subtree_digest = str(binding.get("assigned_subtree_digest") or "")
            if child_subtree_digest != unit_record.assigned_subtree_digest:
                mismatches.append(
                    LineageMismatch(
                        "assigned_subtree_digest",
                        unit_record.assigned_subtree_digest,
                        child_subtree_digest,
                    )
                )

        phase = str(child_run.get("phase") or "")
        status = str(child_run.get("status") or "")
        if child_status_attachable:
            if status not in {"completed", "paused"}:
                mismatches.append(
                    LineageMismatch("status", "completed|paused", status)
                )
            if status == "completed" and phase != OUTPUT_VALIDATED:
                mismatches.append(
                    LineageMismatch("phase", OUTPUT_VALIDATED, phase)
                )

        return mismatches


__all__ = ["ExecutionLineageValidator", "LineageMismatch"]
