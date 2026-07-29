"""Tests for specialist review validation."""

from __future__ import annotations

from top_down_planning.models import (
    ReviewCheckpoint,
    ReviewDecision,
    ReviewFindingCategory,
    ReviewFindingSeverity,
    ReviewerRole,
    SpecialistReviewResult,
)
from top_down_planning.review_validator import validate_specialist_review
from tests.plan_factory import make_root_plan


def test_specialist_approve_rejects_blocking_findings() -> None:
    plan = make_root_plan()
    result = SpecialistReviewResult(
        reviewer_role=ReviewerRole.ADVERSARIAL,
        plan_digest="abc",
        checkpoint=ReviewCheckpoint.FINAL_CANDIDATE,
        decision=ReviewDecision.APPROVE,
        summary="Looks good",
        findings=[
            {
                "id": "finding-001",
                "severity": ReviewFindingSeverity.BLOCKING,
                "category": ReviewFindingCategory.COVERAGE,
                "reviewer_role": ReviewerRole.ADVERSARIAL,
                "observation": "Missing coverage",
            }
        ],
    )
    errors = validate_specialist_review(result, plan=plan, expected_digest="abc")
    assert any("blocking" in error for error in errors)


def test_specialist_needs_revision_requires_findings() -> None:
    plan = make_root_plan()
    result = SpecialistReviewResult(
        reviewer_role=ReviewerRole.ADVERSARIAL,
        plan_digest="abc",
        checkpoint=ReviewCheckpoint.FINAL_CANDIDATE,
        decision=ReviewDecision.NEEDS_REVISION,
        summary="Fix issues",
        findings=[],
    )
    errors = validate_specialist_review(result, plan=plan, expected_digest="abc")
    assert any("requires at least one finding" in error for error in errors)
