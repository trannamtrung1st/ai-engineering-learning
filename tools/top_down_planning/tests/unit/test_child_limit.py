"""Tests for max_children constraint handling."""

from __future__ import annotations

from top_down_planning.completeness import (
    child_limit_blocked_summary,
    has_child_limit_blocked_leaves,
    reopen_eligible_child_limit_blocked,
)
from top_down_planning.models import (
    BlockedConstraintCode,
    DecompositionStatus,
    MarkBlockedOperation,
    PlanItem,
    PlanState,
    PlanningLimits,
    ReadinessStatus,
    SourceMetadata,
)
from top_down_planning.state_updates import apply_response
from top_down_planning.models import AgentResponse
from top_down_planning.validator import validate_response
from tests.helpers import default_generation, make_agent_response


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
    response = make_agent_response(
        operations=[
            MarkBlockedOperation(
                node_id="item-001",
                title="Plan the required workstreams",
                objective="Preserve every explicitly required top-level workstream.",
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


def test_reopen_eligible_child_limit_blocked_when_limit_increases() -> None:
    plan = _root_plan()
    response = make_agent_response(
        operations=[
            MarkBlockedOperation(
                node_id="item-001",
                title="Plan the required workstreams",
                objective="Preserve every explicitly required top-level workstream.",
                reason="Requires at least 11 direct children",
                constraint_code=BlockedConstraintCode.MAX_CHILDREN_EXCEEDED,
                required_min_children=11,
            )
        ]
    )
    blocked = apply_response(plan, response)
    assert has_child_limit_blocked_leaves(blocked)

    reopened_plan, reopened_ids = reopen_eligible_child_limit_blocked(
        blocked,
        max_children_per_expansion=10,
    )
    assert reopened_ids == []
    assert has_child_limit_blocked_leaves(reopened_plan)

    reopened_plan, reopened_ids = reopen_eligible_child_limit_blocked(
        blocked,
        max_children_per_expansion=12,
    )
    assert reopened_ids == ["item-001"]
    assert not has_child_limit_blocked_leaves(reopened_plan)
    root = reopened_plan.item_by_id("item-001")
    assert root is not None
    assert root.decomposition_status == DecompositionStatus.NEEDS_EXPANSION
    assert root.blocked_constraint_code is None
    assert root.readiness_status == ReadinessStatus.PENDING
