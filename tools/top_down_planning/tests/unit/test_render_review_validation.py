"""Tests for render batch and final output review validation."""

from __future__ import annotations

from top_down_planning.models import (
    RenderBatchReviewDecision,
    RenderBatchReviewFinding,
    RenderBatchReviewResult,
    RenderOutputFindingCategory,
    RenderOutputReviewDecision,
    RenderOutputReviewFinding,
    RenderedOutputReviewResult,
    ReviewFindingSeverity,
)
from top_down_planning.render_batch_review import validate_render_batch_review
from top_down_planning.render_review import validate_render_output_review
from tests.plan_factory import make_root_plan


def test_render_batch_review_rejects_unknown_plan_item() -> None:
    plan = make_root_plan(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="a",
        output_goal_digest="b",
    )
    result = RenderBatchReviewResult(
        batch_index=0,
        plan_digest="digest",
        output_goal_digest="goal-digest",
        processed_batches_digest="batches-digest",
        deliverable_output_digest="deliverable-digest",
        decision=RenderBatchReviewDecision.NEEDS_REVISION,
        summary="Missing coverage",
        findings=[
            RenderBatchReviewFinding(
                severity=ReviewFindingSeverity.MAJOR,
                category=RenderOutputFindingCategory.COVERAGE,
                description="Area missing",
                plan_item_ids=["item-999"],
            )
        ],
    )
    errors = validate_render_batch_review(
        result,
        plan=plan,
        batch_item_ids=["item-001"],
        deliverable_paths=["implementation-plan.md"],
    )
    assert any("unknown plan item id" in error for error in errors)


def test_render_batch_review_rejects_out_of_scope_artifact() -> None:
    plan = make_root_plan(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="a",
        output_goal_digest="b",
    )
    result = RenderBatchReviewResult(
        batch_index=0,
        plan_digest="digest",
        output_goal_digest="goal-digest",
        processed_batches_digest="batches-digest",
        deliverable_output_digest="deliverable-digest",
        decision=RenderBatchReviewDecision.NEEDS_REVISION,
        summary="Wrong artifact",
        findings=[
            RenderBatchReviewFinding(
                severity=ReviewFindingSeverity.MAJOR,
                category=RenderOutputFindingCategory.CONSISTENCY,
                description="Wrong file",
                artifact_paths=["other.md"],
            )
        ],
    )
    errors = validate_render_batch_review(
        result,
        plan=plan,
        batch_item_ids=["item-001"],
        deliverable_paths=["implementation-plan.md"],
    )
    assert any("not in scope" in error for error in errors)


def test_render_output_review_rejects_invalid_batch_index() -> None:
    plan = make_root_plan(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="a",
        output_goal_digest="b",
    )
    result = RenderedOutputReviewResult(
        plan_digest="digest",
        output_goal_digest="goal-digest",
        processed_batches_digest="batches-digest",
        deliverable_output_digest="deliverable-digest",
        decision=RenderOutputReviewDecision.NEEDS_REVISION,
        summary="Batch issue",
        findings=[],
        affected_batch_indices=[99],
        affected_artifact_paths=[],
    )
    errors = validate_render_output_review(
        result,
        plan=plan,
        processed_batch_indices=[0, 1],
        deliverable_paths=["implementation-plan.md"],
    )
    assert any("not in processed batch scope" in error for error in errors)


def test_render_output_review_rejects_empty_summary() -> None:
    plan = make_root_plan(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="a",
        output_goal_digest="b",
    )
    result = RenderedOutputReviewResult(
        plan_digest="digest",
        output_goal_digest="goal-digest",
        processed_batches_digest="batches-digest",
        deliverable_output_digest="deliverable-digest",
        decision=RenderOutputReviewDecision.APPROVE,
        summary="",
        findings=[],
    )
    errors = validate_render_output_review(
        result,
        plan=plan,
        processed_batch_indices=[0],
        deliverable_paths=["implementation-plan.md"],
    )
    assert any("summary must not be empty" in error for error in errors)
