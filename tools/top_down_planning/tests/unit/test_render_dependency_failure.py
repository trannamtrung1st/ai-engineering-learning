"""Tests for dependency_failed propagation."""

from __future__ import annotations

from top_down_planning.models import (
    DecompositionStatus,
    PlanItem,
    PlanState,
    RenderManifestItem,
    SourceMetadata,
)
from top_down_planning.render_flow import _is_dependency_blocked


def _plan() -> PlanState:
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
                objective="Root",
                depth=0,
                order=1,
                decomposition_status=DecompositionStatus.ACTIONABLE,
            ),
            PlanItem(
                id="item-002",
                parent_id="item-001",
                title="Child",
                objective="Child",
                depth=1,
                order=1,
                decomposition_status=DecompositionStatus.ACTIONABLE,
            ),
        ],
    )


def test_child_blocked_when_parent_failed() -> None:
    plan = _plan()
    child = RenderManifestItem(plan_item_id="item-002", parent_id="item-001", depth=1)
    assert _is_dependency_blocked(plan, child, {"item-001"})


def test_sibling_not_blocked_when_other_branch_failed() -> None:
    plan = _plan()
    root = RenderManifestItem(plan_item_id="item-001", depth=0)
    assert not _is_dependency_blocked(plan, root, {"item-999"})
