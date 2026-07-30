"""Plan tree traversal, ordering, and planning-budget hints (proposal §6.4, §8.4)."""

from __future__ import annotations

from typing import Any

from top_down_planning.domain.errors import InvalidMutationError, UnknownItemError
from top_down_planning.domain.models import Plan, PlanItem, PlanningBudget, PlanningLimits

Placement = dict[str, Any]

ACTIVE_PLANNING_STATUS = "open"


def is_active_item(item: PlanItem) -> bool:
    return item.planning_status == ACTIVE_PLANNING_STATUS


def active_children_of(plan: Plan, parent_id: str | None) -> list[PlanItem]:
    siblings = [
        item
        for item in plan.items.values()
        if item.parent_id == parent_id and is_active_item(item)
    ]
    siblings.sort(key=lambda item: item.order_key)
    return siblings


def serialized_plan_items(plan: Plan) -> list[dict[str, Any]]:
    """Serialize items: active tree order first, then inactive audit records."""

    active_ids = {item_id for item_id, _ in display_traversal(plan)}
    ordered = [plan.items[item_id].to_dict() for item_id, _ in display_traversal(plan)]
    inactive = sorted(
        (item for item in plan.items.values() if item.id not in active_ids),
        key=lambda item: item.id,
    )
    ordered.extend(item.to_dict() for item in inactive)
    return ordered


def clone_plan(plan: Plan) -> Plan:
    return Plan.from_dict(plan.to_dict())


def item_depth(plan: Plan, item_id: str) -> int:
    depth = 0
    current = plan.items.get(item_id)
    while current is not None and current.parent_id is not None:
        depth += 1
        current = plan.items.get(current.parent_id)
    return depth


def children_of(plan: Plan, parent_id: str | None) -> list[PlanItem]:
    """Return active child items in sibling order (proposal §9.3 display view)."""
    return active_children_of(plan, parent_id)


def descendants_of(plan: Plan, item_id: str) -> set[str]:
    found: set[str] = set()

    def walk(node_id: str) -> None:
        for child in active_children_of(plan, node_id):
            found.add(child.id)
            walk(child.id)

    walk(item_id)
    return found


def display_traversal(plan: Plan) -> list[tuple[str, str]]:
    """Depth-first preorder traversal returning (item_id, display_number)."""

    rows: list[tuple[str, str]] = []

    def walk(parent_id: str | None, prefix: str) -> None:
        for index, child in enumerate(children_of(plan, parent_id), start=1):
            number = f"{prefix}{index}" if prefix else str(index)
            rows.append((child.id, number))
            walk(child.id, f"{number}.")

    walk(None, "")
    return rows


def resolve_placement_index(
    plan: Plan,
    parent_id: str | None,
    placement: Placement | None,
) -> int:
    siblings = children_of(plan, parent_id)
    if not placement:
        return len(siblings)

    if placement.get("first_child"):
        return 0
    if placement.get("last_child"):
        return len(siblings)

    if "before" in placement:
        sibling_id = placement["before"]
        for index, sibling in enumerate(siblings):
            if sibling.id == sibling_id:
                return index
        raise UnknownItemError(sibling_id)

    if "after" in placement:
        sibling_id = placement["after"]
        for index, sibling in enumerate(siblings):
            if sibling.id == sibling_id:
                return index + 1
        raise UnknownItemError(sibling_id)

    raise InvalidMutationError(f"unsupported placement: {placement!r}")


def insert_item_at(
    plan: Plan,
    item: PlanItem,
    parent_id: str | None,
    placement: Placement | None,
) -> None:
    if parent_id is not None and parent_id not in plan.items:
        raise UnknownItemError(parent_id)
    if parent_id is not None and not is_active_item(plan.items[parent_id]):
        raise InvalidMutationError(f"parent item is not active: {parent_id}")

    siblings = children_of(plan, parent_id)
    index = resolve_placement_index(plan, parent_id, placement)
    siblings.insert(index, item)
    item.parent_id = parent_id
    plan.items[item.id] = item
    for sibling_index, child in enumerate(siblings):
        child.order_key = f"{sibling_index:010d}"


def move_item_subtree(
    plan: Plan,
    item_id: str,
    new_parent_id: str | None,
    placement: Placement | None,
) -> None:
    if item_id not in plan.items:
        raise UnknownItemError(item_id)
    if new_parent_id == item_id:
        raise InvalidMutationError("cannot parent an item to itself")
    if new_parent_id is not None:
        if new_parent_id not in plan.items:
            raise UnknownItemError(new_parent_id)
        if new_parent_id in descendants_of(plan, item_id):
            raise InvalidMutationError("cannot move an item under one of its descendants")

    item = plan.items[item_id]
    old_parent_id = item.parent_id
    siblings = [child for child in children_of(plan, old_parent_id) if child.id != item_id]
    for index, child in enumerate(siblings):
        child.order_key = f"{index:010d}"

    insert_item_at(plan, item, new_parent_id, placement)


def compute_planning_budget(
    plan: Plan,
    item_id: str,
    limits: PlanningLimits,
) -> PlanningBudget:
    if item_id not in plan.items:
        raise UnknownItemError(item_id)

    depth = item_depth(plan, item_id)
    direct_children = len(children_of(plan, item_id))
    depth_remaining = limits.max_depth - depth
    expansion_remaining = limits.max_expansion_per_item - direct_children

    warnings: list[str] = []
    if depth > limits.max_depth:
        warnings.append("exceeded_depth_limit")
    elif depth_remaining <= 0:
        warnings.append("at_depth_limit")
    elif depth_remaining == 1:
        warnings.append("near_depth_limit")

    if direct_children > limits.max_expansion_per_item:
        warnings.append("exceeded_expansion_limit")
    elif expansion_remaining <= 0:
        warnings.append("at_expansion_limit")
    elif expansion_remaining == 1:
        warnings.append("near_expansion_limit")

    return PlanningBudget(
        item_id=item_id,
        depth=depth,
        max_depth=limits.max_depth,
        depth_remaining=depth_remaining,
        direct_children=direct_children,
        max_expansion_per_item=limits.max_expansion_per_item,
        expansion_remaining=expansion_remaining,
        warnings=warnings,
    )


def collect_budget_warnings(
    plan: Plan,
    item_ids: set[str],
    limits: PlanningLimits,
) -> tuple[list[str], list[PlanningBudget]]:
    warnings: list[str] = []
    budgets: list[PlanningBudget] = []
    for item_id in sorted(item_ids):
        budget = compute_planning_budget(plan, item_id, limits)
        budgets.append(budget)
        for code in budget.warnings:
            warnings.append(f"{item_id}: {code}")
    return warnings, budgets
