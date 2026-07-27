"""Unit tests for progressive render scheduling."""

from __future__ import annotations

from top_down_planning.models import (
    DecompositionStatus,
    PlanItem,
    PlanState,
    RenderConfig,
    RenderScope,
    SourceMetadata,
)
from top_down_planning.render_scheduler import (
    build_progressive_schedule,
    build_rollup_schedule,
    groups_in_wave,
    unique_waves,
)


def _plan_with_hierarchy() -> PlanState:
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
                decomposition_status=DecompositionStatus.ACTIONABLE,
            ),
            PlanItem(
                id="item-002",
                parent_id="item-001",
                title="Child",
                objective="Child objective",
                depth=1,
                order=1,
                decomposition_status=DecompositionStatus.ACTIONABLE,
            ),
            PlanItem(
                id="item-003",
                parent_id="item-001",
                title="Blocked child",
                objective="Blocked",
                depth=1,
                order=2,
                decomposition_status=DecompositionStatus.BLOCKED,
                blocked_reason="waiting",
            ),
        ],
    )


def test_nodes_scheduled_in_increasing_depth():
    plan = _plan_with_hierarchy()
    items, errors = build_progressive_schedule(plan, render_config=RenderConfig())
    assert errors == []
    assert [item.depth for item in items] == sorted(item.depth for item in items)


def test_child_wave_after_parent_wave():
    plan = _plan_with_hierarchy()
    items, _ = build_progressive_schedule(plan, render_config=RenderConfig())
    parent = next(item for item in items if item.plan_item_id == "item-001")
    child = next(item for item in items if item.plan_item_id == "item-002")
    assert child.wave > parent.wave


def test_invalid_dependency_rejected():
    plan = _plan_with_hierarchy()
    items, errors = build_progressive_schedule(
        plan,
        render_config=RenderConfig(),
        render_dependencies={"item-001": ["item-002"]},
    )
    assert items == []
    assert any("shallower" in error for error in errors)


def test_blocked_node_included_in_schedule():
    plan = _plan_with_hierarchy()
    items, _ = build_progressive_schedule(plan, render_config=RenderConfig())
    ids = {item.plan_item_id for item in items}
    assert "item-003" in ids


def test_rollup_reverse_depth_order():
    plan = _plan_with_hierarchy()
    items, _ = build_rollup_schedule(plan, render_config=RenderConfig())
    child = next(item for item in items if item.plan_item_id == "item-002")
    parent = next(item for item in items if item.plan_item_id == "item-001")
    assert child.wave < parent.wave


def test_unique_waves_and_groups():
    plan = _plan_with_hierarchy()
    items, _ = build_progressive_schedule(plan, render_config=RenderConfig())
    waves = unique_waves(items)
    assert waves == [0, 1]
    assert groups_in_wave(items, 0) == [0]
