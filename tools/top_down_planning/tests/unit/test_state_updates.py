from top_down_planning.models import (
    AgentResponse,
    ChildDraft,
    DecompositionStatus,
    ExpandOperation,
    MarkActionableOperation,
    PlanItem,
    UpdateItemOperation,
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
    assert root.decomposition_status == DecompositionStatus.EXPANDED
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


def test_apply_update_item_replaces_and_clears_fields() -> None:
    plan = _plan()
    plan.plan[0].decomposition_status = DecompositionStatus.EXPANDED
    plan.plan[0].notes = ["old note"]
    plan.plan[0].dependencies = ["item-999"]
    plan.plan.append(
        PlanItem(
            id="item-002",
            parent_id="item-001",
            title="Sibling",
            objective="sibling work",
            depth=1,
            order=2,
            decomposition_status=DecompositionStatus.NEEDS_EXPANSION,
        )
    )
    response = make_agent_response(
        operations=[
            ExpandOperation(
                node_id="item-002",
                children=[ChildDraft(title="Child", objective="child work")],
            )
        ],
        updates=[
            UpdateItemOperation(
                node_id="item-001",
                reason="Align parent notes with the new branch.",
                notes=["updated note"],
                dependencies=[],
            )
        ],
    )
    updated = apply_response(plan, response)
    parent = updated.item_by_id("item-001")
    assert parent is not None
    assert parent.notes == ["updated note"]
    assert parent.dependencies == []


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


def test_expand_marks_parent_expanded_and_passes_structural_validation() -> None:
    plan = _plan()
    plan = apply_response(
        plan,
        make_agent_response(
            operations=[
                ExpandOperation(
                    node_id="item-001",
                    title="Generated root",
                    objective="Describe the requested plan",
                    children=[
                        ChildDraft(
                            ref="child-1",
                            title="First",
                            objective="first",
                        ),
                        ChildDraft(
                            ref="child-2",
                            title="Second",
                            objective="second",
                            dependencies=["item-001"],
                        ),
                    ],
                )
            ]
        ),
    )
    root = plan.item_by_id("item-001")
    assert root is not None
    assert root.decomposition_status == DecompositionStatus.EXPANDED
    from top_down_planning.completeness import structural_errors

    assert structural_errors(plan) == []
