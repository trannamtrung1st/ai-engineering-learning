"""Tests for max_children constraint handling."""

from __future__ import annotations

from top_down_planning.completeness import child_limit_blocked_summary, has_child_limit_blocked_leaves
from top_down_planning.models import (
    BlockedConstraintCode,
    DecompositionStatus,
    MarkBlockedOperation,
    PlanItem,
    PlanState,
    PlanningLimits,
    SourceMetadata,
)
from top_down_planning.state_updates import apply_response
from top_down_planning.models import AgentResponse
from top_down_planning.validator import validate_response


def _root_plan() -> PlanState:
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
                decomposition_status=DecompositionStatus.NEEDS_EXPANSION,
            )
        ],
    )


def test_structured_mark_blocked_for_child_limit() -> None:
    plan = _root_plan()
    response = AgentResponse(
        operations=[
            MarkBlockedOperation(
                node_id="item-001",
                reason="Requires at least 9 direct children",
                constraint_code=BlockedConstraintCode.MAX_CHILDREN_EXCEEDED,
                required_min_children=9,
            )
        ]
    )
    errors = validate_response(
        plan,
        response,
        selected_ids=["item-001"],
        limits=PlanningLimits(max_children_per_expansion=8),
    )
    assert errors == []
    updated = apply_response(plan, response)
    assert has_child_limit_blocked_leaves(updated)
    summary = child_limit_blocked_summary(
        updated,
        max_children_per_expansion=8,
    )
    assert summary is not None
    assert "at least 9 direct children" in summary
    assert "max_children_per_expansion is 8" in summary


def test_required_min_children_must_exceed_limit() -> None:
    plan = _root_plan()
    response = AgentResponse(
        operations=[
            MarkBlockedOperation(
                node_id="item-001",
                reason="Requires 8 children",
                constraint_code=BlockedConstraintCode.MAX_CHILDREN_EXCEEDED,
                required_min_children=8,
            )
        ]
    )
    errors = validate_response(
        plan,
        response,
        selected_ids=["item-001"],
        limits=PlanningLimits(max_children_per_expansion=8),
    )
    assert any("must exceed" in error for error in errors)
