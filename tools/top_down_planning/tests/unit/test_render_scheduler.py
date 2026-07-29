"""Unit tests for sequential render batch scheduling."""

from __future__ import annotations

from top_down_planning.models import (
    DecompositionStatus,
    PlanItem,
    PlanState,
    RenderConfig,
    SourceMetadata,
)
from top_down_planning.render_scheduler import build_render_batch_schedule, validate_batch_independence


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


def test_build_render_batch_schedule_uses_actionable_leaves_only() -> None:
    plan = _plan_with_leaves()
    batches, errors = build_render_batch_schedule(plan, render_config=RenderConfig())
    assert errors == []
    scheduled_ids = {item_id for batch in batches for item_id in batch.item_ids}
    assert scheduled_ids == {"item-002", "item-003"}


def test_batches_do_not_mix_ancestors_and_descendants() -> None:
    plan = _plan_with_leaves()
    batches, _ = build_render_batch_schedule(plan, render_config=RenderConfig(batch_size=3))
    for batch in batches:
        items = [plan.item_by_id(item_id) for item_id in batch.item_ids]
        items = [item for item in items if item is not None]
        assert validate_batch_independence(plan, items) == []
