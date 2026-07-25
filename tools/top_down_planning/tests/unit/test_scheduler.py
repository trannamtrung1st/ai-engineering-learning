from top_down_planning.models import BatchStrategy, DecompositionStatus, GenerationConfig, PlanItem
from top_down_planning.scheduler import (
    are_independent,
    select_batch,
    select_concurrent_batches,
    wave_batch_budget,
)
from tests.helpers import default_generation
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


def test_shallow_first_ordering_in_batch() -> None:
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
    batch = select_batch(plan, default_generation(batch_size=10))
    assert [item.id for item in batch] == ["item-001", "item-002", "item-003"]


def test_batch_size_respected() -> None:
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
    batch = select_batch(plan, default_generation(batch_size=2))
    assert len(batch) == 2
    assert batch[0].order <= batch[1].order


def test_select_concurrent_batches_respects_limits() -> None:
    plan = make_root_plan(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="a",
        output_goal_digest="b",
    )
    for index in range(2, 8):
        plan.plan.append(
            PlanItem(
                id=f"item-{index:03d}",
                parent_id=None,
                title=f"Sibling {index}",
                objective=f"obj {index}",
                depth=0,
                order=index,
            )
        )

    generation = default_generation(batch_size=2)
    batches = select_concurrent_batches(plan, generation, max_batches=3)
    assert len(batches) == 3
    assert all(len(batch) == 2 for batch in batches)
    scheduled = [item.id for batch in batches for item in batch]
    assert len(scheduled) == len(set(scheduled))


def test_select_concurrent_batches_prefers_shallow_items() -> None:
    plan = make_root_plan(
        input_file="./idea.md",
        output_goal="goal",
        input_digest="a",
        output_goal_digest="b",
    )
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    plan.plan.extend(
        [
            PlanItem(
                id="item-002",
                parent_id="item-001",
                title="Branch child",
                objective="branch",
                depth=1,
                order=2,
            ),
            PlanItem(
                id="item-003",
                parent_id=None,
                title="Separate root",
                objective="root",
                depth=0,
                order=3,
            ),
        ]
    )
    generation = default_generation(batch_size=1)
    batches = select_concurrent_batches(plan, generation, max_batches=2)
    assert len(batches) == 2
    assert batches[0][0].id == "item-003"
    assert batches[1][0].id == "item-002"


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


def test_wave_batch_budget_caps_by_remaining_iterations() -> None:
    generation = default_generation(concurrent_batches=3)
    assert wave_batch_budget(generation, remaining_iterations=2) == 2
    assert wave_batch_budget(generation, remaining_iterations=0) == 0
