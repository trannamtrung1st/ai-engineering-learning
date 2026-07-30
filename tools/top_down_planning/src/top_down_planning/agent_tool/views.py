"""Concise plan views for agent snapshot responses (proposal §8.1)."""

from __future__ import annotations

from typing import Any, Literal

from top_down_planning.domain.dispositions import DispositionMap
from top_down_planning.domain.models import Plan, PlanItem, PlanningLimits
from top_down_planning.domain.plan_tree import (
    compute_planning_budget,
    descendants_of,
    display_traversal,
    item_depth,
    walk_active_tree,
)
from top_down_planning.domain.readiness import compute_ready_view
from top_down_planning.domain.validators import ValidationMode, ValidationResult, validate_plan

PlanView = Literal["tree", "ready", "issues"]


def item_snapshot(item: PlanItem, display_number: str) -> dict[str, Any]:
    return {
        "id": item.id,
        "display_number": display_number,
        "parent_id": item.parent_id,
        "title": item.title,
        "outcome": item.outcome,
        "depends_on": list(item.depends_on),
        "planning_status": item.planning_status,
    }


def _visible_item_ids(
    plan: Plan,
    *,
    root_id: str | None,
    depth: int | None,
) -> set[str]:
    if root_id is None:
        visible = {item_id for item_id, _ in walk_active_tree(plan).rows}
    else:
        if root_id not in plan.items:
            return set()
        visible = {root_id, *descendants_of(plan, root_id)}

    if depth is None:
        return visible

    if root_id is None:
        base_depth = 0
    else:
        base_depth = item_depth(plan, root_id)

    return {
        item_id
        for item_id in visible
        if item_depth(plan, item_id) - base_depth <= depth
    }


def build_tree_view(
    plan: Plan,
    *,
    limits: PlanningLimits,
    root_id: str | None = None,
    depth: int | None = None,
) -> dict[str, Any]:
    visible = _visible_item_ids(plan, root_id=root_id, depth=depth)
    items: list[dict[str, Any]] = []
    budgets: list[dict[str, Any]] = []

    for item_id, display_number in display_traversal(plan):
        if item_id not in visible:
            continue
        item = plan.items[item_id]
        items.append(item_snapshot(item, display_number))
        budgets.append(compute_planning_budget(plan, item_id, limits).to_dict())

    return {
        "view": "tree",
        "revision": plan.revision,
        "items": items,
        "planning_budget": budgets,
    }


def build_ready_view(
    plan: Plan,
    dispositions: DispositionMap | None = None,
) -> dict[str, Any]:
    ready = compute_ready_view(plan, dispositions)
    return {
        "view": "ready",
        "revision": plan.revision,
        **ready.to_dict(),
    }


def build_issues_view(
    plan: Plan,
    *,
    limits: PlanningLimits,
    mode: ValidationMode = "draft",
    dispositions: DispositionMap | None = None,
) -> dict[str, Any]:
    validation = validate_plan(plan, limits=limits, dispositions=dispositions, mode=mode)
    return {
        "view": "issues",
        "revision": plan.revision,
        "mode": mode,
        **validation.to_dict(),
    }


def build_changed_subtree_view(
    plan: Plan,
    changed_item_ids: list[str],
    *,
    limits: PlanningLimits,
) -> dict[str, Any]:
    visible: set[str] = set()
    for item_id in changed_item_ids:
        visible.add(item_id)
        visible.update(descendants_of(plan, item_id))

    items: list[dict[str, Any]] = []
    budgets: list[dict[str, Any]] = []
    for item_id, display_number in display_traversal(plan):
        if item_id not in visible:
            continue
        items.append(item_snapshot(plan.items[item_id], display_number))
        budgets.append(compute_planning_budget(plan, item_id, limits).to_dict())

    return {
        "changed_item_ids": list(changed_item_ids),
        "items": items,
        "planning_budget": budgets,
    }


def ready_item_changes(
    before: Plan,
    after: Plan,
    dispositions: DispositionMap | None = None,
) -> dict[str, list[str]]:
    before_ready = set(compute_ready_view(before, dispositions).ready_item_ids)
    after_ready = set(compute_ready_view(after, dispositions).ready_item_ids)
    return {
        "newly_ready": sorted(after_ready - before_ready),
        "no_longer_ready": sorted(before_ready - after_ready),
    }


def validation_warnings(validation: ValidationResult) -> list[str]:
    return [
        issue.message
        for issue in validation.issues
        if issue.severity == "warning"
    ]
