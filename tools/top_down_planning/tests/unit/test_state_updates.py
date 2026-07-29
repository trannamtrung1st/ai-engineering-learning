from top_down_planning.models import (
    AgentResponse,
    ChildDraft,
    DecompositionStatus,
    ExpandOperation,
    MarkActionableOperation,
    PlanItem,
)
from top_down_planning.scheduler import initialize_root_plan
from tests.helpers import default_generation, make_agent_response
from tests.plan_factory import make_root_plan
from top_down_planning.state_updates import apply_response, detect_dependency_cycles


def _plan():
    return make_root_plan(
        input_file="./idea.md",
        output_goal="Produce an actionable implementation plan",
        input_digest="a",
        output_goal_digest="b",
    )


def test_apply_expand_assigns_ids_and_dependencies() -> None:
    plan = _plan()
    response = make_agent_response(
        operations=[
            ExpandOperation(
                node_id="item-001",
                title="Build the CSV conversion CLI",
                objective="Plan a reliable CLI for converting CSV input.",
                children=[
                    ChildDraft(ref="child-1", title="First", objective="first"),
                    ChildDraft(
                        ref="child-2",
                        title="Second",
                        objective="second",
                        dependencies=["child-1"],
                    ),
                ],
            )
        ]
    )
    updated = apply_response(plan, response)
    root = updated.item_by_id("item-001")
    assert root is not None
    assert root.decomposition_status == DecompositionStatus.ACTIONABLE
    assert root.title == "Build the CSV conversion CLI"
    assert root.objective == "Plan a reliable CLI for converting CSV input."
    children = updated.children_of("item-001")
    assert len(children) == 2
    assert children[0].id == "item-002"
    assert children[1].dependencies == ["item-002"]


def test_apply_actionable() -> None:
    plan = _plan()
    response = make_agent_response(
        operations=[
            MarkActionableOperation(
                node_id="item-001",
                title="Plan the requested work",
                objective="Produce the requested implementation plan.",
                expected_outputs=["Spec"],
                acceptance_criteria=["Complete"],
            )
        ]
    )
    updated = apply_response(plan, response)
    item = updated.item_by_id("item-001")
    assert item is not None
    assert item.decomposition_status == DecompositionStatus.ACTIONABLE
    assert item.expected_outputs == ["Spec"]


def test_cycle_detection() -> None:
    plan = make_root_plan(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="a",
        output_goal_digest="b",
    )
    plan.plan.extend(
        [
            PlanItem(
                id="item-002",
                parent_id="item-001",
                title="A",
                objective="a",
                depth=1,
                order=2,
                dependencies=["item-003"],
            ),
            PlanItem(
                id="item-003",
                parent_id="item-001",
                title="B",
                objective="b",
                depth=1,
                order=3,
                dependencies=["item-002"],
            ),
        ]
    )
    cycles = detect_dependency_cycles(plan)
    assert cycles
