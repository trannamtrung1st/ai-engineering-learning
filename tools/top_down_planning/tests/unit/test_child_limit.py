"""Tests for structured blocked items without child-limit resume helpers."""

from __future__ import annotations

from top_down_planning.models import (
    BlockedConstraintCode,
    DecompositionStatus,
    MarkBlockedOperation,
    PlanItem,
    PlanState,
    ReadinessStatus,
    SourceMetadata,
)
from top_down_planning.state_updates import apply_response
from top_down_planning.validator import validate_response
from tests.helpers import make_agent_response


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
    response = make_agent_response(
        operations=[
            MarkBlockedOperation(
                node_id="item-001",
                title="Plan the required workstreams",
                objective="Preserve every explicitly required top-level workstream.",
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
        output_goal_text="Produce an actionable implementation plan",
    )
    assert errors == []
    updated = apply_response(plan, response)
    root = updated.item_by_id("item-001")
    assert root is not None
    assert root.decomposition_status == DecompositionStatus.BLOCKED
    assert root.blocked_constraint_code == BlockedConstraintCode.MAX_CHILDREN_EXCEEDED
    assert root.blocked_required_min_children == 9
    assert root.readiness_status == ReadinessStatus.BLOCKED


def test_required_min_children_must_be_positive() -> None:
    plan = _root_plan()
    response = make_agent_response(
        operations=[
            MarkBlockedOperation(
                node_id="item-001",
                title="Plan the required workstreams",
                objective="Preserve every explicitly required top-level workstream.",
                reason="Requires children",
                constraint_code=BlockedConstraintCode.MAX_CHILDREN_EXCEEDED,
            )
        ]
    )
    errors = validate_response(
        plan,
        response,
        selected_ids=["item-001"],
        output_goal_text="Produce an actionable implementation plan",
    )
    assert any("required_min_children" in error for error in errors)
