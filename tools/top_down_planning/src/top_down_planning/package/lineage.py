"""Verify child-to-parent lineage for attach and resume (proposal §14)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from top_down_planning.domain.run_kind import RUN_KIND_SUB_TDP_EXECUTION, resolve_run_kind
from top_down_planning.orchestrator.phases import OUTPUT_VALIDATED
from top_down_planning.package.loader import LoadedExecutionPackage
from top_down_planning.persistence.digests import compute_output_digest, compute_plan_digest


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
        child_production: dict[str, Any],
        child_plan: Any,
    ) -> list[LineageMismatch]:
        expected_digest = parent_manifest_digest or str(
            parent_package.manifest.get("package_digest") or ""
        )
        if not expected_digest:
            raise ValueError("parent package_digest is required for attach validation")

        mismatches = self._validate_binding(
            parent_package=parent_package,
            child_run=child_run,
            expected_package_digest=expected_digest,
        )
        status = str(child_run.get("status") or "")
        phase = str(child_run.get("phase") or "")
        outcome = str(child_run.get("outcome") or "")

        if status != "completed":
            mismatches.append(LineageMismatch("status", "completed", status))
        if phase != OUTPUT_VALIDATED:
            mismatches.append(LineageMismatch("phase", OUTPUT_VALIDATED, phase))
        if outcome != "accepted":
            mismatches.append(
                LineageMismatch("outcome", "accepted", outcome or "<missing>")
            )

        unit_id = str(
            (child_run.get("package_binding") or {}).get("selected_unit_id")
            or (child_run.get("package_binding") or {}).get("unit_id")
            or ""
        )
        unit = parent_package.units.get(unit_id)
        if unit is not None:
            actual_plan_digest = compute_plan_digest(child_plan)
            expected_plan_digest = compute_plan_digest(unit.plan)
            if actual_plan_digest != expected_plan_digest:
                mismatches.append(
                    LineageMismatch(
                        "persisted_plan_digest",
                        expected_plan_digest,
                        actual_plan_digest,
                    )
                )

        claim = child_production.get("completion_claim")
        if not isinstance(claim, dict):
            mismatches.append(
                LineageMismatch("completion_claim", "present", "<missing>")
            )
        output_digest = compute_output_digest(child_production)
        binding = child_run.get("package_binding") or {}
        expected_output = str(
            binding.get("accepted_output_digest")
            or (child_run.get("digests") or {}).get("output")
            or ""
        ).strip()
        if not expected_output:
            mismatches.append(
                LineageMismatch("output_digest", "present", "<missing>")
            )
        elif expected_output != output_digest:
            mismatches.append(
                LineageMismatch("output_digest", expected_output, output_digest)
            )

        return mismatches

    def validate_resume(
        self,
        *,
        parent_package: LoadedExecutionPackage,
        child_run: dict[str, Any],
        expected_unit_id: str,
    ) -> list[LineageMismatch]:
        mismatches = self._validate_binding(
            parent_package=parent_package,
            child_run=child_run,
            expected_package_digest=str(
                parent_package.manifest.get("package_digest") or ""
            ),
        )
        binding = child_run.get("package_binding") or {}
        unit_id = str(
            binding.get("selected_unit_id") or binding.get("unit_id") or ""
        )
        if unit_id != expected_unit_id:
            mismatches.append(
                LineageMismatch("unit_id", expected_unit_id, unit_id or "<missing>")
            )
        return mismatches

    def _validate_binding(
        self,
        *,
        parent_package: LoadedExecutionPackage,
        child_run: dict[str, Any],
        expected_package_digest: str,
    ) -> list[LineageMismatch]:
        mismatches: list[LineageMismatch] = []
        try:
            kind = resolve_run_kind(child_run)
        except ValueError as exc:
            mismatches.append(
                LineageMismatch("run_kind", RUN_KIND_SUB_TDP_EXECUTION, str(exc))
            )
            return mismatches
        if kind != RUN_KIND_SUB_TDP_EXECUTION:
            mismatches.append(
                LineageMismatch("run_kind", RUN_KIND_SUB_TDP_EXECUTION, kind)
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
        if child_package_digest != expected_package_digest:
            mismatches.append(
                LineageMismatch(
                    "package_digest",
                    expected_package_digest,
                    child_package_digest,
                )
            )

        planning_run_id = str(
            (parent_package.manifest.get("planning_run") or {}).get("run_id") or ""
        )
        child_planning = str(binding.get("planning_run_id") or "")
        if planning_run_id and child_planning != planning_run_id:
            mismatches.append(
                LineageMismatch(
                    "planning_run_id",
                    planning_run_id,
                    child_planning or "<missing>",
                )
            )

        parent_plan_digest = str(
            (parent_package.manifest.get("parent") or {}).get("plan_digest") or ""
        )
        child_parent_digest = str(binding.get("parent_plan_digest") or "")
        if parent_plan_digest and child_parent_digest != parent_plan_digest:
            mismatches.append(
                LineageMismatch(
                    "parent_plan_digest",
                    parent_plan_digest,
                    child_parent_digest or "<missing>",
                )
            )

        unit_id = str(binding.get("selected_unit_id") or binding.get("unit_id") or "")
        if unit_id not in parent_package.units:
            mismatches.append(
                LineageMismatch("unit_id", "known unit", unit_id or "<missing>")
            )
        else:
            unit_record = parent_package.units[unit_id]
            child_unit_digest = str(binding.get("unit_plan_digest") or "")
            if child_unit_digest != unit_record.plan_digest:
                mismatches.append(
                    LineageMismatch(
                        "unit_plan_digest",
                        unit_record.plan_digest,
                        child_unit_digest or "<missing>",
                    )
                )
            child_subtree_digest = str(binding.get("assigned_subtree_digest") or "")
            if child_subtree_digest != unit_record.assigned_subtree_digest:
                mismatches.append(
                    LineageMismatch(
                        "assigned_subtree_digest",
                        unit_record.assigned_subtree_digest,
                        child_subtree_digest or "<missing>",
                    )
                )
        return mismatches


def accepted_result_record(
    *,
    child_run: dict[str, Any],
    child_production: dict[str, Any],
    unit_id: str,
    unit_plan_digest: str,
) -> dict[str, Any]:
    digests = child_run.get("digests") or {}
    return {
        "child_run_id": child_run.get("id"),
        "unit_id": unit_id,
        "unit_plan_digest": unit_plan_digest,
        "output_revision": int(child_production.get("output_revision") or 0),
        "output_digest": str(
            digests.get("output") or compute_output_digest(child_production)
        ),
        "whole_output_review_id": str(
            (child_run.get("package_binding") or {}).get("whole_output_review_id") or ""
        ),
        "outcome": str(child_run.get("outcome") or ""),
    }


__all__ = [
    "ExecutionLineageValidator",
    "LineageMismatch",
    "accepted_result_record",
]
