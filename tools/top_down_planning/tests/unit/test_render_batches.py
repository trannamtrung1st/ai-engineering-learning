"""Unit tests for render batch helpers."""

from __future__ import annotations

from top_down_planning.models import (
    DecompositionStatus,
    PlanItem,
    PlanState,
    ProcessedBatchRecord,
    SourceMetadata,
)
from top_down_planning.render_batches import (
    processed_batch_indices,
    processed_batches_digest,
    validate_batch_independence,
    validate_render_batch_selection,
)


def _plan_with_leaves() -> PlanState:
    return PlanState(
        source=SourceMetadata(
            input_file="idea.md",
            output_goal="goal",
            input_digest="in",
            output_goal_digest="out",
        ),
        plan=[
            PlanItem(
                id="item-001",
                title="Root",
                objective="Root objective",
                depth=0,
                order=1,
                decomposition_status=DecompositionStatus.EXPANDED,
            ),
            PlanItem(
                id="item-002",
                parent_id="item-001",
                title="Child A",
                objective="Child A objective",
                depth=1,
                order=1,
                decomposition_status=DecompositionStatus.ACTIONABLE,
            ),
            PlanItem(
                id="item-003",
                parent_id="item-001",
                title="Child B",
                objective="Child B objective",
                depth=1,
                order=2,
                decomposition_status=DecompositionStatus.ACTIONABLE,
            ),
        ],
    )


def test_processed_batches_digest_is_stable() -> None:
    records = [
        ProcessedBatchRecord(
            iteration=1,
            selected_items=["item-002"],
            purpose="first batch",
        ),
        ProcessedBatchRecord(
            iteration=2,
            selected_items=["item-003"],
            purpose="second batch",
        ),
    ]
    first = processed_batches_digest(records)
    second = processed_batches_digest(records)
    assert first == second
    assert len(first) == 64


def test_processed_batch_indices_are_sequential() -> None:
    records = [
        ProcessedBatchRecord(iteration=1, selected_items=["item-002"]),
        ProcessedBatchRecord(iteration=2, selected_items=["item-003"]),
    ]
    assert processed_batch_indices(records) == [0, 1]


def test_validate_batch_independence_rejects_ancestor_pairs() -> None:
    plan = _plan_with_leaves()
    root = plan.plan[0]
    child = plan.plan[1]
    errors = validate_batch_independence(plan, [root, child])
    assert any("ancestor/descendant pair" in error for error in errors)


def test_validate_render_batch_selection_requires_manifest() -> None:
    plan = _plan_with_leaves()
    errors = validate_render_batch_selection(
        plan,
        selected_ids=[],
        eligible_ids={"item-002", "item-003"},
        covered_ids=set(),
    )
    assert any("select-batch" in error for error in errors)


def test_validate_render_batch_selection_rejects_covered_items() -> None:
    plan = _plan_with_leaves()
    errors = validate_render_batch_selection(
        plan,
        selected_ids=["item-002"],
        eligible_ids={"item-002", "item-003"},
        covered_ids={"item-002"},
    )
    assert any("already covered" in error for error in errors)


def test_validate_batch_independence_accepts_sibling_leaves() -> None:
    plan = _plan_with_leaves()
    sibling_a = plan.plan[1]
    sibling_b = plan.plan[2]
    assert validate_batch_independence(plan, [sibling_a, sibling_b]) == []
