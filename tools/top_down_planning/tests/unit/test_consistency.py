from top_down_planning.models import (
    AgentResponse,
    ChildDraft,
    DecompositionStatus,
    ExpandOperation,
    MarkBlockedOperation,
    MarkOutOfScopeOperation,
    PlanItem,
)
from top_down_planning.scheduler import initialize_root_plan
from tests.helpers import DEFAULT_LIMITS, make_agent_response
from tests.plan_factory import make_root_plan
from top_down_planning.state_updates import apply_response
from top_down_planning.validator import validate_response


def _plan():
    return make_root_plan(
        input_file="./idea.md",
        output_goal="Produce an actionable implementation plan",
        input_digest="a",
        output_goal_digest="b",
    )


def test_apply_blocked_and_out_of_scope() -> None:
    plan = _plan()
    blocked = apply_response(
        plan,
        make_agent_response(
            operations=[
                MarkBlockedOperation(
                    node_id="item-001",
                    title="Resolve the output format",
                    objective="Determine the required JSON formatting before planning.",
                    reason="Missing stakeholder decision",
                    missing_information="Output JSON formatting preference",
                    open_question="Should output be pretty-printed or compact?",
                )
            ]
        ),
    )
    item = blocked.item_by_id("item-001")
    assert item is not None
    assert item.decomposition_status == DecompositionStatus.BLOCKED
    assert item.open_questions

    plan = _plan()
    out_of_scope = apply_response(
        plan,
        make_agent_response(
            operations=[
                MarkOutOfScopeOperation(
                    node_id="item-001",
                    title="Assess the requested work",
                    objective="Determine whether the input contributes to the output goal.",
                    reason="Not required for this output goal",
                )
            ]
        ),
    )
    item = out_of_scope.item_by_id("item-001")
    assert item is not None
    assert item.decomposition_status == DecompositionStatus.OUT_OF_SCOPE


def test_validate_rejects_cycles_before_apply() -> None:
    plan = _plan()
    response = make_agent_response(
        operations=[
            ExpandOperation(
                node_id="item-001",
                title="Generated root",
                objective="Describe the requested plan",
                children=[
                    ChildDraft(
                        ref="child-a",
                        title="A",
                        objective="a",
                        dependencies=["child-b"],
                    ),
                    ChildDraft(
                        ref="child-b",
                        title="B",
                        objective="b",
                        dependencies=["child-a"],
                    ),
                ],
            )
        ]
    )
    errors = validate_response(
        plan,
        response,
        selected_ids=["item-001"],
        output_goal_text="Produce an actionable implementation plan",
        limits=DEFAULT_LIMITS,
    )
    assert any("->" in error for error in errors)


def test_invalid_response_does_not_mutate_plan() -> None:
    plan = _plan()
    original_count = len(plan.plan)
    response = make_agent_response(
        operations=[
            ExpandOperation(
                node_id="item-001",
                title="Generated root",
                objective="Describe the requested plan",
                children=[ChildDraft(title="Only", objective="one")],
            ),
            ExpandOperation(
                node_id="item-001",
                title="Generated root",
                objective="Describe the requested plan",
                children=[ChildDraft(title="Duplicate", objective="op")],
            ),
        ]
    )
    errors = validate_response(
        plan,
        response,
        selected_ids=["item-001"],
        output_goal_text="Produce an actionable implementation plan",
        limits=DEFAULT_LIMITS,
    )
    assert errors
    assert len(plan.plan) == original_count
