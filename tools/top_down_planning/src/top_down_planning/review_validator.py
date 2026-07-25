"""Validate structured whole-plan review and final confirmation results."""

from __future__ import annotations

from top_down_planning.models import (
    ConfirmationDecision,
    FinalConfirmationResult,
    PlanState,
    ReviewDecision,
    ReviewFindingSeverity,
    WholePlanReviewResult,
)


def validate_whole_plan_review(
    result: WholePlanReviewResult,
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
        errors.append("Review summary must not be empty")

    node_ids = {item.id for item in plan.plan}
    for index, finding in enumerate(result.findings):
        prefix = f"Finding {index + 1}"
        if not finding.description.strip():
            errors.append(f"{prefix}: description must not be empty")
        for node_id in finding.node_ids:
            if node_id not in node_ids:
                errors.append(f"{prefix}: unknown node id {node_id!r}")

    blocking_or_major = [
        finding
        for finding in result.findings
        if finding.severity
        in {ReviewFindingSeverity.BLOCKING, ReviewFindingSeverity.MAJOR}
    ]

    if result.decision == ReviewDecision.APPROVE:
        if blocking_or_major:
            errors.append(
                "approve decision cannot include blocking or major findings"
            )
    elif result.decision == ReviewDecision.NEEDS_REVISION:
        if not result.findings:
            errors.append("needs_revision decision requires at least one finding")
    elif result.decision == ReviewDecision.BLOCKED:
        if not result.summary.strip():
            errors.append("blocked decision requires a summary explanation")

    return errors


def validate_final_confirmation(
    result: FinalConfirmationResult,
    *,
    plan: PlanState,
    expected_digest: str,
    deterministic_validation_passed: bool,
) -> list[str]:
    errors: list[str] = []
    if result.plan_digest != expected_digest:
        errors.append(
            f"Confirmation plan_digest mismatch: expected {expected_digest}, "
            f"got {result.plan_digest}"
        )
    if not result.summary.strip():
        errors.append("Confirmation summary must not be empty")
    if not deterministic_validation_passed:
        errors.append(
            "Final confirmation cannot override failed deterministic validation"
        )

    node_ids = {item.id for item in plan.plan}
    for index, finding in enumerate(result.findings):
        prefix = f"Finding {index + 1}"
        if not finding.description.strip():
            errors.append(f"{prefix}: description must not be empty")
        for node_id in finding.node_ids:
            if node_id not in node_ids:
                errors.append(f"{prefix}: unknown node id {node_id!r}")

    blocking_or_major = [
        finding
        for finding in result.findings
        if finding.severity
        in {ReviewFindingSeverity.BLOCKING, ReviewFindingSeverity.MAJOR}
    ]

    if result.decision == ConfirmationDecision.CONFIRMED:
        if blocking_or_major:
            errors.append(
                "confirmed decision cannot include blocking or major findings"
            )
    elif result.decision == ConfirmationDecision.NEEDS_REVISION:
        if not result.findings:
            errors.append("needs_revision decision requires at least one finding")
    elif result.decision == ConfirmationDecision.BLOCKED:
        if not result.summary.strip():
            errors.append("blocked decision requires a summary explanation")

    return errors
