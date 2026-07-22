"""Selection of expandable planning items for sequential and concurrent batches."""

from __future__ import annotations

from top_down_planning.models import DecompositionStatus, PlanItem, PlanState, PlanningLimits, SourceMetadata


def expandable_items(plan: PlanState) -> list[PlanItem]:
    return [
        item
        for item in plan.plan
        if item.decomposition_status == DecompositionStatus.NEEDS_EXPANSION
    ]


def is_ancestor(plan: PlanState, ancestor_id: str, item_id: str) -> bool:
    current = plan.item_by_id(item_id)
    while current is not None and current.parent_id is not None:
        if current.parent_id == ancestor_id:
            return True
        current = plan.item_by_id(current.parent_id)
    return False


def are_independent(plan: PlanState, left: PlanItem, right: PlanItem) -> bool:
    if left.id == right.id:
        return False
    return not is_ancestor(plan, left.id, right.id) and not is_ancestor(
        plan, right.id, left.id
    )


def _ordered_expandable_items(plan: PlanState) -> list[PlanItem]:
    return sorted(expandable_items(plan), key=lambda item: (item.depth, item.order))


def select_concurrent_batches(
    plan: PlanState,
    limits: PlanningLimits,
    *,
    max_batches: int,
) -> list[list[PlanItem]]:
    """Return up to ``max_batches`` disjoint batches from independent expandable items."""
    if max_batches <= 0:
        return []

    candidates = _ordered_expandable_items(plan)
    if not candidates:
        return []

    max_items = max_batches * limits.batch_size
    candidates = candidates[:max_items]

    batches: list[list[PlanItem]] = []
    for item in candidates:
        placed = False
        for batch in batches:
            if len(batch) >= limits.batch_size:
                continue
            if all(are_independent(plan, item, other) for other in batch):
                batch.append(item)
                placed = True
                break
        if not placed and len(batches) < max_batches:
            batches.append([item])

    return [batch for batch in batches if batch]


def select_batch(plan: PlanState, limits: PlanningLimits) -> list[PlanItem]:
    """Return the first concurrent batch for single-batch scheduling."""
    batches = select_concurrent_batches(plan, limits, max_batches=1)
    return batches[0] if batches else []


def wave_batch_budget(limits: PlanningLimits, *, remaining_iterations: int) -> int:
    if remaining_iterations <= 0:
        return 0
    return min(limits.concurrent_batches, remaining_iterations)


def next_item_id(plan: PlanState) -> str:
    max_num = 0
    for item in plan.plan:
        if item.id.startswith("item-"):
            suffix = item.id.removeprefix("item-")
            if suffix.isdigit():
                max_num = max(max_num, int(suffix))
    return f"item-{max_num + 1:03d}"


def next_order(plan: PlanState) -> int:
    if not plan.plan:
        return 1
    return max(item.order for item in plan.plan) + 1


def initialize_root_plan(*, source: SourceMetadata) -> PlanState:
    from top_down_planning.models import ReadinessStatus, ResultMetadata

    root = PlanItem(
        id="item-001",
        parent_id=None,
        title="Understand and plan the requested work",
        objective="Transform the input into the requested final plan",
        depth=0,
        order=1,
        decomposition_status=DecompositionStatus.NEEDS_EXPANSION,
        readiness_status=ReadinessStatus.PENDING,
    )
    return PlanState(
        source=source,
        plan=[root],
        result=ResultMetadata(),
    )
