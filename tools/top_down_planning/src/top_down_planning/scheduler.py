"""Helpers for planning item eligibility and graph relationships."""

from __future__ import annotations

from top_down_planning.models import DecompositionStatus, PlanItem, PlanState, SourceMetadata


def expandable_items(plan: PlanState) -> list[PlanItem]:
    """Return incomplete items at the shallowest depth only, stably sorted."""
    candidates = [
        item
        for item in plan.plan
        if item.decomposition_status == DecompositionStatus.NEEDS_EXPANSION
    ]
    if not candidates:
        return []
    min_depth = min(item.depth for item in candidates)
    return sorted(
        (item for item in candidates if item.depth == min_depth),
        key=lambda item: (item.order, item.id),
    )


def amendable_items(plan: PlanState, node_ids: list[str]) -> list[PlanItem]:
    """Return actionable items eligible for in-place revision."""
    allowed = set(node_ids)
    return sorted(
        [
            item
            for item in plan.plan
            if item.id in allowed
            and item.decomposition_status == DecompositionStatus.ACTIONABLE
        ],
        key=lambda item: (item.depth, item.order),
    )


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
    from top_down_planning.models import PlanItem, PlanState, ResultMetadata

    root = PlanItem(
        id="item-001",
        parent_id=None,
        title="Planning root",
        objective="Top-level planning container for the requested output.",
        depth=0,
        order=1,
        decomposition_status=DecompositionStatus.NEEDS_EXPANSION,
    )
    return PlanState(source=source, plan=[root], result=ResultMetadata())
