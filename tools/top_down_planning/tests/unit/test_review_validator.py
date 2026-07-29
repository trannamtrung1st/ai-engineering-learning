"""Tests for review result validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from top_down_planning.models import (
    ConfirmationDecision,
    DecompositionStatus,
    FinalConfirmationResult,
    PlanItem,
    PlanState,
    ReviewDecision,
    ReviewFinding,
    ReviewFindingCategory,
    ReviewFindingSeverity,
    RevisionMode,
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


def _plan_with_actionable_leaves() -> PlanState:
    return PlanState(
        source=SourceMetadata(
            input_file="idea.md",
            output_goal="goal",
            input_digest="a",
            output_goal_digest="b",
        ),
        plan=[
            PlanItem(
                id="item-001",
                title="Root",
                objective="Root objective",
                decomposition_status=DecompositionStatus.EXPANDED,
            ),
            PlanItem(
                id="item-002",
                parent_id="item-001",
                title="Child",
                objective="Child objective",
                depth=1,
                order=2,
                decomposition_status=DecompositionStatus.ACTIONABLE,
            ),
        ],
    )


def test_review_finding_requires_revision_mode() -> None:
    with pytest.raises(ValidationError):
        ReviewFinding(
            severity=ReviewFindingSeverity.MAJOR,
            category=ReviewFindingCategory.CONSISTENCY,
            node_ids=["item-002"],
            description="Fix detail",
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
                revision_mode=RevisionMode.REOPEN,
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


def test_needs_revision_requires_actionable_finding() -> None:
    plan = _plan_with_actionable_leaves()
    result = WholePlanReviewResult(
        plan_digest="abc",
        decision=ReviewDecision.NEEDS_REVISION,
        summary="Fix items",
        findings=[
            ReviewFinding(
                severity=ReviewFindingSeverity.MINOR,
                category=ReviewFindingCategory.OTHER,
                revision_mode=RevisionMode.ANNOTATE,
                node_ids=[],
                description="Informational only",
            )
        ],
    )
    errors = validate_whole_plan_review(result, plan=plan, expected_digest="abc")
    assert any("requires at least one actionable finding" in error for error in errors)


def test_final_confirmation_needs_revision_requires_actionable_finding() -> None:
    plan = _plan_with_actionable_leaves()
    result = FinalConfirmationResult(
        plan_digest="abc",
        decision=ConfirmationDecision.NEEDS_REVISION,
        summary="Fix items",
        findings=[
            ReviewFinding(
                severity=ReviewFindingSeverity.MINOR,
                category=ReviewFindingCategory.OTHER,
                revision_mode=RevisionMode.ANNOTATE,
                node_ids=[],
                description="Informational only",
            )
        ],
    )
    errors = validate_final_confirmation(
        result,
        plan=plan,
        expected_digest="abc",
        deterministic_validation_passed=True,
    )
    assert any("requires at least one actionable finding" in error for error in errors)


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


def test_amend_rejects_non_actionable_node() -> None:
    plan = _plan_with_actionable_leaves()
    root = plan.item_by_id("item-001")
    assert root is not None
    root.decomposition_status = DecompositionStatus.NEEDS_EXPANSION
    result = WholePlanReviewResult(
        plan_digest="abc",
        decision=ReviewDecision.NEEDS_REVISION,
        summary="Fix root",
        findings=[
            ReviewFinding(
                severity=ReviewFindingSeverity.MAJOR,
                category=ReviewFindingCategory.GRANULARITY,
                revision_mode=RevisionMode.AMEND,
                node_ids=["item-001"],
                description="Wrong mode",
            )
        ],
    )
    errors = validate_whole_plan_review(result, plan=plan, expected_digest="abc")
    assert any("revision_mode=amend requires actionable node" in error for error in errors)


def test_amend_rejects_expanded_non_leaf() -> None:
    plan = _plan_with_actionable_leaves()
    result = WholePlanReviewResult(
        plan_digest="abc",
        decision=ReviewDecision.NEEDS_REVISION,
        summary="Fix root",
        findings=[
            ReviewFinding(
                severity=ReviewFindingSeverity.MAJOR,
                category=ReviewFindingCategory.GRANULARITY,
                revision_mode=RevisionMode.AMEND,
                node_ids=["item-001"],
                description="Wrong mode",
            )
        ],
    )
    errors = validate_whole_plan_review(result, plan=plan, expected_digest="abc")
    assert any(
        "revision_mode=amend requires actionable node" in error
        and "expanded" in error
        for error in errors
    )
