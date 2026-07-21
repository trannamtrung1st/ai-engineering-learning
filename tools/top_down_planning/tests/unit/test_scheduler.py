from top_down_planning.models import DecompositionStatus, PlanningLimits, ReadinessStatus
from top_down_planning.scheduler import select_batch
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
    assert root.readiness_status == ReadinessStatus.PENDING


def test_bfs_selects_shallowest_first() -> None:
    plan = make_root_plan(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="a",
        output_goal_digest="b",
    )
    from top_down_planning.models import PlanItem

    plan.plan.extend(
        [
            PlanItem(
                id="item-002",
                parent_id="item-001",
                title="Deep",
                objective="deep",
                depth=2,
                order=2,
            ),
            PlanItem(
                id="item-003",
                parent_id="item-001",
                title="Shallow",
                objective="shallow",
                depth=1,
                order=3,
            ),
        ]
    )
    batch = select_batch(plan, PlanningLimits(batch_size=10))
    assert [item.id for item in batch] == ["item-001"]


def test_batch_size_respected() -> None:
    plan = make_root_plan(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="a",
        output_goal_digest="b",
    )
    from top_down_planning.models import PlanItem

    plan.plan.extend(
        [
            PlanItem(
                id="item-002",
                parent_id=None,
                title="Sibling A",
                objective="a",
                depth=0,
                order=2,
            ),
            PlanItem(
                id="item-003",
                parent_id=None,
                title="Sibling B",
                objective="b",
                depth=0,
                order=3,
            ),
        ]
    )
    batch = select_batch(plan, PlanningLimits(batch_size=2))
    assert len(batch) == 2
    assert batch[0].order <= batch[1].order
