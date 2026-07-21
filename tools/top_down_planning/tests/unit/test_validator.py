from top_down_planning.models import (
    AgentResponse,
    Assessment,
    ChildDraft,
    DecompositionStatus,
    ExpandOperation,
    MarkActionableOperation,
    MarkBlockedOperation,
    PlanningLimits,
)
from top_down_planning.scheduler import initialize_root_plan
from tests.plan_factory import make_root_plan
from top_down_planning.validator import validate_response


def _plan():
    return make_root_plan(
        input_file="./idea.md",
        output_goal="Produce an actionable implementation plan",
        input_digest="a",
        output_goal_digest="b",
    )


def test_validate_expand_success() -> None:
    plan = _plan()
    response = AgentResponse(
        operations=[
            ExpandOperation(
                node_id="item-001",
                children=[
                    ChildDraft(title="A", objective="Do A"),
                    ChildDraft(title="B", objective="Do B"),
                ],
            )
        ]
    )
    assert validate_response(plan, response, selected_ids=["item-001"], limits=PlanningLimits()) == []


def test_validate_missing_operation() -> None:
    plan = _plan()
    response = AgentResponse(operations=[])
    errors = validate_response(plan, response, selected_ids=["item-001"], limits=PlanningLimits())
    assert any("at least one operation" in error for error in errors)


def test_validate_duplicate_sibling_title() -> None:
    plan = _plan()
    response = AgentResponse(
        operations=[
            ExpandOperation(
                node_id="item-001",
                children=[
                    ChildDraft(title="Same", objective="A"),
                    ChildDraft(title="Same", objective="B"),
                ],
            )
        ]
    )
    errors = validate_response(plan, response, selected_ids=["item-001"], limits=PlanningLimits())
    assert any("Duplicate sibling title" in error for error in errors)


def test_validate_actionable_requires_outputs() -> None:
    plan = _plan()
    response = AgentResponse(
        operations=[MarkActionableOperation(node_id="item-001")]
    )
    errors = validate_response(plan, response, selected_ids=["item-001"], limits=PlanningLimits())
    assert any("expected_outputs" in error for error in errors)


def test_validate_blocked_requires_fields() -> None:
    plan = _plan()
    response = AgentResponse(
        operations=[MarkBlockedOperation(node_id="item-001", reason="blocked")]
    )
    errors = validate_response(plan, response, selected_ids=["item-001"], limits=PlanningLimits())
    assert any("missing_information" in error for error in errors)


def test_validate_max_children_limit() -> None:
    plan = _plan()
    children = [ChildDraft(title=f"C{i}", objective=f"obj {i}") for i in range(3)]
    response = AgentResponse(
        operations=[ExpandOperation(node_id="item-001", children=children)]
    )
    errors = validate_response(
        plan,
        response,
        selected_ids=["item-001"],
        limits=PlanningLimits(max_children_per_expansion=2),
    )
    assert any("max children" in error for error in errors)
