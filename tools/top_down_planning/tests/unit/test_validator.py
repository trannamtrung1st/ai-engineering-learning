from top_down_planning.models import (
    AgentResponse,
    Assessment,
    ChildDraft,
    DecompositionStatus,
    ExpandOperation,
    MarkActionableOperation,
    MarkBlockedOperation,
    PlanItem,
    PlanningLimits,
    ReviseActionableOperation,
)
from top_down_planning.scheduler import initialize_root_plan
from tests.helpers import default_generation, make_agent_response
from tests.plan_factory import make_root_plan
from top_down_planning.validator import (
    validate_amend_response,
    validate_response,
    validate_wave_responses,
)


def _plan():
    return make_root_plan(
        input_file="./idea.md",
        output_goal="Produce an actionable implementation plan",
        input_digest="a",
        output_goal_digest="b",
    )


def test_validate_expand_success() -> None:
    plan = _plan()
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
    assert validate_response(plan, response, selected_ids=["item-001"], limits=PlanningLimits()) == []


def test_validate_root_expand_requires_generated_metadata() -> None:
    plan = _plan()
    response = make_agent_response(
        operations=[
            ExpandOperation(
                node_id="item-001",
                children=[ChildDraft(title="A", objective="Do A")],
            )
        ]
    )

    errors = validate_response(
        plan,
        response,
        selected_ids=["item-001"],
        limits=PlanningLimits(),
    )

    assert any("requires a generated title and objective" in error for error in errors)


def test_validate_root_terminal_decision_requires_generated_metadata() -> None:
    plan = _plan()
    response = make_agent_response(
        operations=[
            MarkActionableOperation(
                node_id="item-001",
                expected_outputs=["Plan"],
                acceptance_criteria=["Done"],
            )
        ]
    )

    errors = validate_response(
        plan,
        response,
        selected_ids=["item-001"],
        limits=PlanningLimits(),
    )

    assert any("requires a generated title and objective" in error for error in errors)


def test_validate_missing_operation() -> None:
    plan = _plan()
    response = make_agent_response(operations=[])
    errors = validate_response(plan, response, selected_ids=["item-001"], limits=PlanningLimits())
    assert any("at least one operation" in error for error in errors)


def test_validate_duplicate_sibling_title() -> None:
    plan = _plan()
    response = make_agent_response(
        operations=[
            ExpandOperation(
                node_id="item-001",
                title="Generated root",
                objective="Describe the requested plan",
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
    response = make_agent_response(
        operations=[
            MarkActionableOperation(
                node_id="item-001",
                title="Generated root",
                objective="Describe the requested plan",
            )
        ]
    )
    errors = validate_response(plan, response, selected_ids=["item-001"], limits=PlanningLimits())
    assert any("expected_outputs" in error for error in errors)


def test_validate_blocked_requires_fields() -> None:
    plan = _plan()
    response = make_agent_response(
        operations=[
            MarkBlockedOperation(
                node_id="item-001",
                title="Generated root",
                objective="Describe the requested plan",
                reason="blocked",
            )
        ]
    )
    errors = validate_response(plan, response, selected_ids=["item-001"], limits=PlanningLimits())
    assert any("missing_information" in error for error in errors)


def test_validate_max_children_limit() -> None:
    plan = _plan()
    children = [ChildDraft(title=f"C{i}", objective=f"obj {i}") for i in range(3)]
    response = make_agent_response(
        operations=[
            ExpandOperation(
                node_id="item-001",
                title="Generated root",
                objective="Describe the requested plan",
                children=children,
            )
        ]
    )
    errors = validate_response(
        plan,
        response,
        selected_ids=["item-001"],
        limits=PlanningLimits(max_children_per_expansion=2),
    )
    assert any("max children" in error for error in errors)


def test_validate_cumulative_max_items_within_single_response() -> None:
    plan = _plan()
    response = make_agent_response(
        operations=[
            ExpandOperation(
                node_id="item-001",
                title="Generated root",
                objective="Describe the requested plan",
                children=[ChildDraft(title="A", objective="a")],
            )
        ]
    )
    errors = validate_response(
        plan,
        response,
        selected_ids=["item-001"],
        limits=PlanningLimits(max_items=1),
    )
    assert any("max items" in error for error in errors)


def test_validate_wave_responses_checks_combined_item_limit() -> None:
    plan = _plan()
    from top_down_planning.models import PlanItem

    plan.plan.append(
        PlanItem(
            id="item-002",
            parent_id=None,
            title="Sibling",
            objective="sibling",
            depth=0,
            order=2,
        )
    )
    first = make_agent_response(
        plan_digest="wave-digest",
        operations=[
            ExpandOperation(
                node_id="item-001",
                title="Generated root",
                objective="Describe the requested plan",
                children=[ChildDraft(title="A", objective="a")],
            )
        ],
    )
    second = make_agent_response(
        plan_digest="wave-digest",
        operations=[
            ExpandOperation(
                node_id="item-002",
                title="Generated sibling root",
                objective="Describe the sibling plan",
                children=[ChildDraft(title="B", objective="b")],
            )
        ],
    )
    errors = validate_wave_responses(
        plan,
        [
            (["item-001"], first),
            (["item-002"], second),
        ],
        limits=PlanningLimits(max_items=2),
        plan_digest="wave-digest",
    )
    assert any("max items" in error for error in errors)


def test_validate_response_rejects_revise_actionable() -> None:
    plan = _plan()
    response = make_agent_response(
        operations=[
            ReviseActionableOperation(
                node_id="item-001",
                reason="wrong session",
                expected_outputs=["x"],
                acceptance_criteria=["y"],
            )
        ]
    )
    errors = validate_response(plan, response, selected_ids=["item-001"], limits=PlanningLimits())
    assert any("Unsupported operation type" in error for error in errors)


def test_validate_amend_response_accepts_revise_actionable() -> None:
    plan = _plan()
    item = plan.item_by_id("item-001")
    assert item is not None
    item.decomposition_status = DecompositionStatus.ACTIONABLE
    response = make_agent_response(
        operations=[
            ReviseActionableOperation(
                node_id="item-001",
                reason="Apply review fix",
                expected_outputs=["Revised output"],
                acceptance_criteria=["Revised criteria"],
            )
        ]
    )
    assert (
        validate_amend_response(
            plan,
            response,
            selected_ids=["item-001"],
        )
        == []
    )
