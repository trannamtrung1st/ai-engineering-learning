from top_down_planning.completeness import compute_final_status, is_plan_complete, limit_reached
from top_down_planning.models import (
    AgentResponse,
    ChildDraft,
    DecompositionStatus,
    ExpandOperation,
    FinalStatus,
    MarkActionableOperation,
    PlanningLimits,
)
from top_down_planning.scheduler import select_batch
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
        AgentResponse(
            operations=[
                MarkActionableOperation(
                    node_id="item-001",
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
        AgentResponse(
            operations=[
                ExpandOperation(
                    node_id="item-001",
                    children=[
                        ChildDraft(title="Area A", objective="A"),
                        ChildDraft(title="Area B", objective="B"),
                    ],
                )
            ]
        ),
    )
    batch = select_batch(plan, PlanningLimits(batch_size=10))
    assert {item.depth for item in batch} == {1}
    plan = apply_response(
        plan,
        AgentResponse(
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
