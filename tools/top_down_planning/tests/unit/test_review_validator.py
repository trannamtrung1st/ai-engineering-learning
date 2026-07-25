"""Tests for review result validation."""

from __future__ import annotations

from top_down_planning.models import (
    ConfirmationDecision,
    FinalConfirmationResult,
    PlanItem,
    PlanState,
    ReviewDecision,
    ReviewFinding,
    ReviewFindingCategory,
    ReviewFindingSeverity,
    SourceMetadata,
    WholePlanReviewResult,
)
from top_down_planning.review_validator import (
    validate_final_confirmation,
    validate_whole_plan_review,
)


def _plan() -> PlanState:
    return PlanState(
        source=SourceMetadata(
            input_file="idea.md",
            output_goal="goal",
            input_digest="a",
            output_goal_digest="b",
        ),
        plan=[
            PlanItem(id="item-001", title="Root", objective="Objective"),
        ],
    )


def test_approve_rejects_major_findings() -> None:
    plan = _plan()
    result = WholePlanReviewResult(
        plan_digest="digest",
        decision=ReviewDecision.APPROVE,
        summary="Looks good",
        findings=[
            ReviewFinding(
                severity=ReviewFindingSeverity.MAJOR,
                category=ReviewFindingCategory.COVERAGE,
                node_ids=["item-001"],
                description="Missing branch",
            )
        ],
    )
    errors = validate_whole_plan_review(result, plan=plan, expected_digest="digest")
    assert any("approve decision cannot include blocking or major" in error for error in errors)


def test_stale_digest_rejected() -> None:
    plan = _plan()
    result = WholePlanReviewResult(
        plan_digest="old-digest",
        decision=ReviewDecision.APPROVE,
        summary="Looks good",
    )
    errors = validate_whole_plan_review(result, plan=plan, expected_digest="new-digest")
    assert any("plan_digest mismatch" in error for error in errors)


def test_confirmed_rejects_failed_deterministic_validation() -> None:
    plan = _plan()
    result = FinalConfirmationResult(
        plan_digest="digest",
        decision=ConfirmationDecision.CONFIRMED,
        summary="Confirmed",
    )
    errors = validate_final_confirmation(
        result,
        plan=plan,
        expected_digest="digest",
        deterministic_validation_passed=False,
    )
    assert any("cannot override failed deterministic validation" in error for error in errors)

