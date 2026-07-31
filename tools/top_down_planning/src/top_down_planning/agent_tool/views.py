"""Concise plan views for agent snapshot responses (proposal §8.1)."""

from __future__ import annotations

from typing import Any, Literal

from top_down_planning.domain.dispositions import DispositionMap
from top_down_planning.domain.models import Plan, PlanItem, PlanningLimits
from top_down_planning.domain.plan_tree import (
    ancestor_path,
    compute_planning_budget,
    descendants_of,
    display_traversal,
    item_depth,
    walk_active_tree,
)
from top_down_planning.domain.readiness import compute_ready_view
from top_down_planning.domain.reviews import build_is_review_blocked_fn
from top_down_planning.domain.validators import ValidationResult

PlanView = Literal["tree", "ready", "issues"]


def item_snapshot(item: PlanItem, display_number: str, *, depth: int) -> dict[str, Any]:
    return {
        "id": item.id,
        "display_number": display_number,
        "parent_id": item.parent_id,
        "depth": depth,
        "title": item.title,
        "outcome": item.outcome,
        "kind": item.kind,
        "scope": item.scope.to_dict(),
        "boundaries": list(item.boundaries),
        "acceptance": list(item.acceptance),
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
        visible = {item_id for item_id, _, _ in walk_active_tree(plan).rows}
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
        items.append(
            item_snapshot(item, display_number, depth=item_depth(plan, item_id))
        )
        budgets.append(compute_planning_budget(plan, item_id, limits).to_dict())

    return {
        "view": "tree",
        "revision": plan.revision,
        "items": items,
        "planning_budget": budgets,
        "scope": plan.scope.to_dict(),
        "boundaries": list(plan.boundaries),
        "constraints": list(plan.constraints),
        "assumptions": list(plan.assumptions),
        "acceptance": list(plan.acceptance),
    }


def build_plan_review_snapshot(
    plan: Plan,
    *,
    limits: PlanningLimits,
) -> dict[str, Any]:
    """Bounded plan artifact for reviewer packages (proposal §4.3, §5.2)."""

    snapshot = build_tree_view(plan, limits=limits)
    snapshot["output_goal"] = plan.output_goal
    return snapshot


def ready_item_contract(plan: Plan, item_id: str) -> dict[str, Any]:
    """Compact work-item contract for production ready snapshots."""

    item = plan.items[item_id]
    return {
        "id": item.id,
        "title": item.title,
        "outcome": item.outcome,
        "kind": item.kind,
        "scope": item.scope.to_dict(),
        "boundaries": list(item.boundaries),
        "acceptance": list(item.acceptance),
        "depends_on": list(item.depends_on),
        "ancestor_path": ancestor_path(plan, item_id),
    }


def build_ready_view(
    plan: Plan,
    dispositions: DispositionMap | None = None,
    *,
    reviews: list[dict[str, Any]] | None = None,
    review_types: frozenset[str] | None = None,
) -> dict[str, Any]:
    is_review_blocked = build_is_review_blocked_fn(reviews, review_types=review_types)
    ready = compute_ready_view(
        plan,
        dispositions,
        is_review_blocked=is_review_blocked,
    )
    payload = {
        "view": "ready",
        "revision": plan.revision,
        **ready.to_dict(),
    }
    payload["ready_items"] = [
        ready_item_contract(plan, item_id) for item_id in ready.ready_item_ids
    ]
    return payload


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
        items.append(
            item_snapshot(
                plan.items[item_id],
                display_number,
                depth=item_depth(plan, item_id),
            )
        )
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
    *,
    reviews: list[dict[str, Any]] | None = None,
    review_types: frozenset[str] | None = None,
) -> dict[str, list[str]]:
    is_review_blocked = build_is_review_blocked_fn(reviews, review_types=review_types)
    before_ready = set(
        compute_ready_view(
            before,
            dispositions,
            is_review_blocked=is_review_blocked,
        ).ready_item_ids
    )
    after_ready = set(
        compute_ready_view(
            after,
            dispositions,
            is_review_blocked=is_review_blocked,
        ).ready_item_ids
    )
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


def validation_issues(validation: ValidationResult) -> list[dict[str, Any]]:
    return [
        issue.to_dict()
        for issue in validation.issues
        if issue.severity == "error"
    ]
