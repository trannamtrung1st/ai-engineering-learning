from top_down_planning.models import DecompositionStatus, PlanItem
from top_down_planning.scheduler import are_independent, initialize_root_plan
from tests.plan_factory import make_root_plan


def test_initialize_root_plan() -> None:
    plan = make_root_plan(
        input_file="./idea.md",
        output_goal="Produce an actionable implementation plan",
        input_digest="abc",
        output_goal_digest="def",
    )
    assert len(plan.plan) == 1
    root = plan.plan[0]
    assert root.id == "item-001"
    assert root.parent_id is None
    assert root.depth == 0
    assert root.decomposition_status == DecompositionStatus.NEEDS_EXPANSION


def test_are_independent_rejects_ancestor_pairs() -> None:
    plan = make_root_plan(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="a",
        output_goal_digest="b",
    )
    child = PlanItem(
        id="item-002",
        parent_id="item-001",
        title="Child",
        objective="child",
        depth=1,
        order=2,
    )
    plan.plan.append(child)
    root = plan.plan[0]
    assert not are_independent(plan, root, child)
    assert are_independent(plan, root, root) is False
