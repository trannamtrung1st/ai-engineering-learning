"""Plan tree traversal, ordering, and planning-budget hints (proposal §6.4, §8.4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from top_down_planning.domain.errors import InvalidMutationError, UnknownItemError
from top_down_planning.domain.models import Plan, PlanItem, PlanningBudget, PlanningLimits

Placement = dict[str, Any]

ACTIVE_PLANNING_STATUS = "open"
PLAN_ROOT_ITEM_ID = "item-root"
DEFAULT_PLAN_ROOT_TITLE = "Root"

PLAN_ROOT_PLANNER_INSTRUCTION = (
    f"Seeded root contract: the run seeds aggregate {PLAN_ROOT_ITEM_ID} "
    f"(title {DEFAULT_PLAN_ROOT_TITLE!r}). Before adding decomposition children "
    f"under {PLAN_ROOT_ITEM_ID}, use update_item on {PLAN_ROOT_ITEM_ID} to set a "
    "meaningful title and outcome that top-level children will decompose. Use "
    "update_plan for plan-level scope, boundaries, constraints, assumptions, "
    "acceptance, and risks — do not duplicate those fields on the root unless "
    "item-owned."
)

PLAN_ROOT_REVIEWER_INSTRUCTION = (
    f"Root contract: when {PLAN_ROOT_ITEM_ID} has active child items, it must "
    f"not keep the seeded title {DEFAULT_PLAN_ROOT_TITLE!r} and must have a "
    "non-empty outcome that its children genuinely decompose."
)


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


@dataclass(frozen=True)
class TraversalWalk:
    rows: list[tuple[str, str, int]]
    duplicate_ids: list[str]


def walk_active_tree(plan: Plan) -> TraversalWalk:
    """Depth-first preorder walk; tolerates corrupt trees without infinite recursion."""

    rows: list[tuple[str, str, int]] = []
    duplicate_ids: list[str] = []
    seen_global: set[str] = set()
    visiting: set[str] = set()

    def walk(parent_id: str | None, prefix: str, depth: int) -> None:
        for index, child in enumerate(children_of(plan, parent_id), start=1):
            if child.id in visiting or child.id in seen_global:
                if child.id not in duplicate_ids:
                    duplicate_ids.append(child.id)
                continue
            visiting.add(child.id)
            seen_global.add(child.id)
            number = f"{prefix}{index}" if prefix else str(index)
            rows.append((child.id, number, depth))
            walk(child.id, f"{number}.", depth + 1)
            visiting.remove(child.id)

    walk(None, "", 0)
    return TraversalWalk(rows=rows, duplicate_ids=duplicate_ids)


def serialize_plan_item(item: PlanItem, *, depth: int) -> dict[str, Any]:
    """Serialize a plan item for persistence with tree depth after parent_id."""

    base = item.to_dict()
    payload: dict[str, Any] = {
        "id": base["id"],
        "parent_id": base["parent_id"],
        "depth": depth,
    }
    for key, value in base.items():
        if key not in payload:
            payload[key] = value
    return payload


def serialized_plan_items(plan: Plan) -> list[dict[str, Any]]:
    """Serialize items: active tree order first, then inactive audit records."""

    walk = walk_active_tree(plan)
    active_ids = {item_id for item_id, _, _ in walk.rows}
    ordered = [
        serialize_plan_item(plan.items[item_id], depth=depth)
        for item_id, _, depth in walk.rows
    ]
    inactive = sorted(
        (item for item in plan.items.values() if item.id not in active_ids),
        key=lambda item: item.id,
    )
    ordered.extend(
        serialize_plan_item(item, depth=item_depth(plan, item.id)) for item in inactive
    )
    return ordered


def validate_persisted_item_depths(plan: Plan, raw_items: list[dict[str, Any]]) -> None:
    """Require each persisted item to carry depth matching its parent chain."""

    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            raise ValueError("each plan item must be an object")
        item_id = str(raw_item.get("id", ""))
        if "depth" not in raw_item:
            raise ValueError(f"plan item {item_id!r} missing required field: depth")
        expected = item_depth(plan, item_id)
        actual = int(raw_item["depth"])
        if actual != expected:
            raise ValueError(
                f"plan item {item_id!r} depth {actual} does not match hierarchy depth {expected}"
            )


def clone_plan(plan: Plan) -> Plan:
    return Plan.from_dict(plan.to_dict())


def item_depth(plan: Plan, item_id: str) -> int:
    depth = 0
    seen: set[str] = {item_id}
    current = plan.items.get(item_id)
    while current is not None and current.parent_id is not None:
        parent_id = current.parent_id
        if parent_id in seen:
            break
        seen.add(parent_id)
        depth += 1
        current = plan.items.get(parent_id)
        if current is None:
            break
    return depth


def ancestor_path(plan: Plan, item_id: str) -> list[str]:
    """Return root-to-parent ancestor ids for ``item_id`` (excluding the item itself)."""

    path: list[str] = []
    seen: set[str] = {item_id}
    current = plan.items.get(item_id)
    while current is not None and current.parent_id is not None:
        parent_id = current.parent_id
        if parent_id in seen:
            break
        seen.add(parent_id)
        path.append(parent_id)
        current = plan.items.get(parent_id)
        if current is None:
            break
    path.reverse()
    return path


def children_of(plan: Plan, parent_id: str | None) -> list[PlanItem]:
    """Return active child items in sibling order (proposal §9.3 display view)."""
    return active_children_of(plan, parent_id)


def descendants_of(plan: Plan, item_id: str) -> set[str]:
    found: set[str] = set()
    visiting: set[str] = set()

    def walk(node_id: str) -> None:
        if node_id in visiting:
            return
        visiting.add(node_id)
        for child in active_children_of(plan, node_id):
            found.add(child.id)
            walk(child.id)
        visiting.remove(node_id)

    walk(item_id)
    return found


def find_hierarchy_cycle(plan: Plan, item_id: str) -> list[str] | None:
    if item_id not in plan.items:
        return None

    path = [item_id]
    seen = {item_id}
    current = plan.items[item_id]
    while current.parent_id is not None:
        parent_id = current.parent_id
        if parent_id in seen:
            cycle_start = path.index(parent_id)
            return path[cycle_start:] + [parent_id]
        if parent_id not in plan.items:
            return None
        path.append(parent_id)
        seen.add(parent_id)
        current = plan.items[parent_id]
    return None


def display_traversal(plan: Plan) -> list[tuple[str, str]]:
    """Depth-first preorder traversal returning (item_id, display_number)."""
    return [(item_id, number) for item_id, number, _ in walk_active_tree(plan).rows]


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


def recompact_active_sibling_order_keys(plan: Plan, parent_id: str | None) -> None:
    """Renumber active sibling order_keys after a removal leaves a gap."""

    for index, child in enumerate(children_of(plan, parent_id)):
        child.order_key = f"{index:010d}"


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


def seed_plan_root_item() -> PlanItem:
    """Return the minimal aggregate root seeded at run creation."""

    return PlanItem(
        id=PLAN_ROOT_ITEM_ID,
        parent_id=None,
        order_key="0000000000",
        title=DEFAULT_PLAN_ROOT_TITLE,
        kind="aggregate",
    )
