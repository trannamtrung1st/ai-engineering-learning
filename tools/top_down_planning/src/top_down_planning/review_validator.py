"""Validate structured whole-plan review and final confirmation results."""

from __future__ import annotations

from top_down_planning.completeness import is_leaf
from top_down_planning.models import (
    ConfirmationDecision,
    DecompositionStatus,
    FinalConfirmationResult,
    PlanState,
    ReviewDecision,
    ReviewFinding,
    ReviewFindingSeverity,
    RevisionMode,
    WholePlanReviewResult,
)


def _is_ancestor(plan: PlanState, *, ancestor_id: str, item_id: str) -> bool:
    current = plan.item_by_id(item_id)
    while current is not None and current.parent_id is not None:
        if current.parent_id == ancestor_id:
            return True
        current = plan.item_by_id(current.parent_id)
    return False


def _validate_findings(plan: PlanState, findings: list[ReviewFinding]) -> list[str]:
    errors: list[str] = []
    node_ids = {item.id for item in plan.plan}
    for index, finding in enumerate(findings):
        prefix = f"Finding {index + 1}"
        if not finding.description.strip():
            errors.append(f"{prefix}: description must not be empty")
        mode = finding.revision_mode
        if mode in {RevisionMode.REOPEN, RevisionMode.AMEND} and not finding.node_ids:
            errors.append(
                f"{prefix}: revision_mode={mode.value} requires at least one node_id"
            )
        for node_id in finding.node_ids:
            if node_id not in node_ids:
                errors.append(f"{prefix}: unknown node id {node_id!r}")
            elif mode == RevisionMode.AMEND:
                item = plan.item_by_id(node_id)
                if item is None:
                    continue
                if item.decomposition_status != DecompositionStatus.ACTIONABLE:
                    errors.append(
                        f"{prefix}: revision_mode=amend requires actionable node "
                        f"{node_id!r} (status={item.decomposition_status.value}); "
                        "use revision_mode=reopen when structure must change"
                    )
                elif not is_leaf(plan, node_id):
                    errors.append(
                        f"{prefix}: revision_mode=amend requires actionable leaf "
                        f"{node_id!r}; use revision_mode=reopen when structure must change"
                    )
        if mode == RevisionMode.REOPEN and finding.node_ids:
            for node_id in finding.node_ids:
                for other_id in finding.node_ids:
                    if node_id == other_id:
                        continue
                    if _is_ancestor(plan, ancestor_id=other_id, item_id=node_id):
                        errors.append(
                            f"{prefix}: cite only the reopen root {other_id!r}, "
                            f"not descendant {node_id!r}"
                        )
    return errors


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

    errors.extend(_validate_findings(plan, result.findings))

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
        elif not any(
            finding.revision_mode in {RevisionMode.REOPEN, RevisionMode.AMEND}
            or (
                finding.revision_mode == RevisionMode.ANNOTATE
                and finding.node_ids
            )
            for finding in result.findings
        ):
            errors.append(
                "needs_revision requires at least one actionable finding "
                "(reopen, amend, or annotate with node_ids)"
            )
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

    errors.extend(_validate_findings(plan, result.findings))

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
