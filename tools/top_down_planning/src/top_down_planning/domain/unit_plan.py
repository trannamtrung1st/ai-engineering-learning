"""Build unit plan snapshots from approved parent plan subtrees (proposal §9)."""

from __future__ import annotations

from dataclasses import replace

from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.plan_tree import (
    PLAN_ROOT_ITEM_ID,
    active_children_of,
    is_active_item,
    seed_plan_root_item,
)
from top_down_planning.domain.sub_tdp_units import SubTdpUnit


def collect_assigned_item_ids(plan: Plan, unit_root_id: str) -> list[str]:
    """Return unit root and all active descendants in stable depth-first order."""

    if unit_root_id not in plan.items:
        raise ValueError(f"unknown unit root item: {unit_root_id!r}")
    collected: list[str] = []

    def walk(item_id: str) -> None:
        item = plan.items.get(item_id)
        if item is None or not is_active_item(item):
            return
        collected.append(item_id)
        for child in active_children_of(plan, item_id):
            walk(child.id)

    walk(unit_root_id)
    return collected


def build_unit_plan_snapshot(parent_plan: Plan, unit: SubTdpUnit) -> Plan:
    """Materialize the executable contract for one prepared unit."""

    unit_root_id = unit.plan_item_id
    assigned_ids = collect_assigned_item_ids(parent_plan, unit_root_id)
    if unit_root_id not in assigned_ids:
        raise ValueError(f"unit root {unit_root_id!r} is not active in parent plan")

    root_item = seed_plan_root_item()
    items: dict[str, PlanItem] = {PLAN_ROOT_ITEM_ID: root_item}
    unit_root = parent_plan.items[unit_root_id]

    for item_id in assigned_ids:
        source = parent_plan.items[item_id]
        parent_id = PLAN_ROOT_ITEM_ID if item_id == unit_root_id else source.parent_id
        if parent_id not in assigned_ids and parent_id != PLAN_ROOT_ITEM_ID:
            raise ValueError(
                f"assigned item {item_id!r} parent {parent_id!r} is outside unit subtree"
            )
        items[item_id] = replace(source, parent_id=parent_id)

    local_goal = unit_root.outcome.strip() or parent_plan.output_goal
    return Plan(
        id=f"plan-unit-{unit_root_id}",
        revision=parent_plan.revision,
        output_goal=local_goal,
        items=items,
        input_refs=list(parent_plan.input_refs),
        scope=parent_plan.scope,
        boundaries=list(parent_plan.boundaries),
        constraints=list(parent_plan.constraints),
        assumptions=list(parent_plan.assumptions),
        acceptance=list(parent_plan.acceptance),
        risks=list(parent_plan.risks),
        schema_version=parent_plan.schema_version,
    )


__all__ = [
    "build_unit_plan_snapshot",
    "collect_assigned_item_ids",
]
