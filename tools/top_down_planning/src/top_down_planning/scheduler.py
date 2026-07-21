"""Breadth-first selection of expandable planning items."""

from __future__ import annotations

from top_down_planning.models import DecompositionStatus, PlanItem, PlanState, PlanningLimits, SourceMetadata


def expandable_items(plan: PlanState) -> list[PlanItem]:
    return [
        item
        for item in plan.plan
        if item.decomposition_status == DecompositionStatus.NEEDS_EXPANSION
    ]


def select_batch(plan: PlanState, limits: PlanningLimits) -> list[PlanItem]:
    """Return the shallowest incomplete items, ordered deterministically."""
    candidates = expandable_items(plan)
    if not candidates:
        return []
    min_depth = min(item.depth for item in candidates)
    shallow = [item for item in candidates if item.depth == min_depth]
    shallow.sort(key=lambda item: item.order)
    return shallow[: limits.batch_size]


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
