from top_down_planning.completeness import (
    compute_final_status,
    count_by_status,
    is_plan_complete,
    limit_reached,
    structural_errors,
)
from top_down_planning.models import (
    AgentResponse,
    ChildDraft,
    DecompositionStatus,
    ExpandOperation,
    FinalStatus,
    MarkActionableOperation,
    PlanItem,
    PlanningLimits,
)
from top_down_planning.scheduler import select_batch
from tests.helpers import default_generation, make_agent_response
from tests.plan_factory import make_root_plan
from top_down_planning.state_updates import apply_response


def _plan():
    return make_root_plan(
        input_file="./idea.md",
        output_goal="Produce an actionable implementation plan",
        input_digest="a",
        output_goal_digest="b",
    )


def test_complete_when_no_expandable_items() -> None:
    plan = _plan()
    plan = apply_response(
        plan,
        make_agent_response(
            operations=[
                MarkActionableOperation(
                    node_id="item-001",
                    title="Plan the requested work",
                    objective="Produce the requested implementation plan.",
                    expected_outputs=["Plan"],
                    acceptance_criteria=["Done"],
                )
            ]
        ),
    )
    assert is_plan_complete(plan)
    assert compute_final_status(plan) == FinalStatus.COMPLETE


def test_limit_reached_by_iterations() -> None:
    plan = _plan()
    limits = PlanningLimits(max_iterations=1)
    assert limit_reached(iteration=1, plan=plan, limits=limits)


def test_incomplete_limit_status() -> None:
    plan = _plan()
    status = compute_final_status(plan, limit_reached=True)
    assert status == FinalStatus.INCOMPLETE_LIMIT_REACHED


def test_multi_level_bfs_expansion() -> None:
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
                        ChildDraft(title="Area A", objective="A"),
                        ChildDraft(title="Area B", objective="B"),
                    ],
                )
            ]
        ),
    )
    batch = select_batch(plan, default_generation())
    assert {item.depth for item in batch} == {1}
    plan = apply_response(
        plan,
        make_agent_response(
            operations=[
                MarkActionableOperation(
                    node_id=item.id,
                    expected_outputs=["Out"],
                    acceptance_criteria=["Done"],
                )
                for item in batch
            ]
        ),
    )
    assert is_plan_complete(plan)


def test_complete_plan_with_expanded_internal_nodes() -> None:
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
                        ChildDraft(title="Area A", objective="A"),
                        ChildDraft(title="Area B", objective="B"),
                    ],
                )
            ]
        ),
    )
    root = plan.item_by_id("item-001")
    assert root is not None
    assert root.decomposition_status == DecompositionStatus.EXPANDED
    for child in plan.children_of("item-001"):
        plan = apply_response(
            plan,
            make_agent_response(
                operations=[
                    MarkActionableOperation(
                        node_id=child.id,
                        expected_outputs=["Out"],
                        acceptance_criteria=["Done"],
                    )
                ]
            ),
        )
    counts = count_by_status(plan)
    assert counts["expanded"] == 1
    assert counts["actionable"] == 2
    assert is_plan_complete(plan)


def test_structural_errors_reject_actionable_non_leaf() -> None:
    plan = _plan()
    plan.plan.append(
        PlanItem(
            id="item-002",
            parent_id="item-001",
            title="Child",
            objective="child",
            depth=1,
            order=2,
        )
    )
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    errors = structural_errors(plan)
    assert any("actionable but is not a leaf" in error for error in errors)


def test_structural_errors_reject_expanded_without_children() -> None:
    plan = _plan()
    plan.plan[0].decomposition_status = DecompositionStatus.EXPANDED
    errors = structural_errors(plan)
    assert any("expanded but has no children" in error for error in errors)
