"""Mandatory whole-artifact review audit pass identifiers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from top_down_planning.domain.reviews import ReviewLoop

WHOLE_PLAN_AUDIT_PASS_IDS: tuple[str, ...] = (
    "preflight_triage",
    "coverage_and_modality",
    "dependency_closure",
    "ownership_and_shared_surfaces",
    "acceptance_and_branch_completeness",
    "scope_risk_and_traceability",
    "finding_family_expansion",
)

WHOLE_OUTPUT_AUDIT_PASS_IDS: tuple[str, ...] = (
    "plan_conformance",
    "evidence_correctness",
    "cross_output_consistency",
    "completion_claim_integrity",
    "traceability",
    "plan_risk_coverage",
)


def mandatory_audit_pass_ids_for_loop(loop: ReviewLoop) -> tuple[str, ...]:
    if loop.type == "whole_plan":
        return WHOLE_PLAN_AUDIT_PASS_IDS
    if loop.type == "whole_output":
        return WHOLE_OUTPUT_AUDIT_PASS_IDS
    return ()
