"""Validate structured specialist review results."""

from __future__ import annotations

from top_down_planning.models import (
    PlanState,
    ReviewDecision,
    ReviewFindingSeverity,
    SpecialistReviewResult,
)


def validate_specialist_review(
    result: SpecialistReviewResult,
    *,
    plan: PlanState,
    expected_digest: str,
) -> list[str]:
    errors: list[str] = []
    if result.plan_digest != expected_digest:
        errors.append(
            f"Review plan_digest mismatch: expected {expected_digest}, "
            f"got {result.plan_digest}"
        )
    if not result.summary.strip():
        errors.append("Specialist review summary must not be empty")
    node_ids = {item.id for item in plan.plan}
    for index, finding in enumerate(result.findings):
        prefix = f"Finding {index + 1}"
        if not finding.id.strip():
            errors.append(f"{prefix}: id must not be empty")
        if not finding.observation.strip():
            errors.append(f"{prefix}: observation must not be empty")
        for branch_id in finding.affected_branches:
            if branch_id not in node_ids:
                errors.append(f"{prefix}: unknown affected branch {branch_id!r}")
    if result.decision == ReviewDecision.APPROVE:
        blocking = [
            finding
            for finding in result.findings
            if finding.severity == ReviewFindingSeverity.BLOCKING
        ]
        if blocking:
            errors.append("approve decision cannot include blocking findings")
    elif result.decision == ReviewDecision.NEEDS_REVISION and not result.findings:
        errors.append("needs_revision decision requires at least one finding")
    return errors
