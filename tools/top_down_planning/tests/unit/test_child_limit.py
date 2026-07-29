"""Tests for structural expansion limits (depth and children per expand)."""

from __future__ import annotations

from top_down_planning.models import (
    ChildDraft,
    DecompositionStatus,
    ExpandOperation,
    MarkActionableOperation,
    PlanItem,
    PlanState,
    PlanningLimits,
    SourceMetadata,
)
from top_down_planning.state_updates import apply_response
from top_down_planning.validator import validate_response
from tests.helpers import DEFAULT_LIMITS, make_agent_response


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


def _deep_item(depth: int) -> PlanItem:
    return PlanItem(
        id="item-deep",
        parent_id="item-001",
        title="Deep item",
        objective="Deep objective",
        depth=depth,
        order=2,
        decomposition_status=DecompositionStatus.NEEDS_EXPANSION,
    )


def test_expand_rejects_too_many_children() -> None:
    plan = _root_plan()
    limits = PlanningLimits(max_children_per_expansion=2)
    response = make_agent_response(
        operations=[
            ExpandOperation(
                node_id="item-001",
                title="Generated root",
                objective="Describe the requested plan",
                children=[
                    ChildDraft(title="A", objective="Do A"),
                    ChildDraft(title="B", objective="Do B"),
                    ChildDraft(title="C", objective="Do C"),
                ],
            )
        ]
    )
    errors = validate_response(
        plan,
        response,
        selected_ids=["item-001"],
        output_goal_text="Produce an actionable implementation plan",
        limits=limits,
    )
    assert any("exceeds max children" in error for error in errors)
    assert any("mark_actionable" in error for error in errors)


def test_expand_accepts_children_at_limit() -> None:
    plan = _root_plan()
    limits = PlanningLimits(max_children_per_expansion=2)
    response = make_agent_response(
        operations=[
            ExpandOperation(
                node_id="item-001",
                title="Generated root",
                objective="Describe the requested plan",
                children=[
                    ChildDraft(title="A", objective="Do A"),
                    ChildDraft(title="B", objective="Do B"),
                ],
            )
        ]
    )
    errors = validate_response(
        plan,
        response,
        selected_ids=["item-001"],
        output_goal_text="Produce an actionable implementation plan",
        limits=limits,
    )
    assert errors == []


def test_expand_rejects_at_max_depth() -> None:
    plan = _root_plan()
    plan.plan.append(_deep_item(depth=6))
    limits = PlanningLimits(max_depth=6)
    response = make_agent_response(
        operations=[
            ExpandOperation(
                node_id="item-deep",
                children=[ChildDraft(title="Too deep", objective="child")],
            )
        ]
    )
    errors = validate_response(
        plan,
        response,
        selected_ids=["item-deep"],
        output_goal_text="Produce an actionable implementation plan",
        limits=limits,
    )
    assert any("max_depth=6" in error for error in errors)
    assert any("mark_actionable" in error for error in errors)


def test_mark_actionable_at_max_depth_is_valid() -> None:
    plan = _root_plan()
    plan.plan.append(_deep_item(depth=6))
    response = make_agent_response(
        operations=[
            MarkActionableOperation(
                node_id="item-deep",
                expected_outputs=["Leaf output"],
                acceptance_criteria=["Done"],
                notes=["Captured ancillary detail from source input."],
            )
        ]
    )
    errors = validate_response(
        plan,
        response,
        selected_ids=["item-deep"],
        output_goal_text="Produce an actionable implementation plan",
        limits=DEFAULT_LIMITS,
    )
    assert errors == []
    updated = apply_response(plan, response)
    leaf = updated.item_by_id("item-deep")
    assert leaf is not None
    assert leaf.decomposition_status == DecompositionStatus.ACTIONABLE
    assert "Captured ancillary detail" in leaf.notes[0]
