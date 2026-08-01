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
    is_active_item,
    item_depth,
    walk_active_tree,
)
from top_down_planning.domain.readiness import compute_ready_view
from top_down_planning.domain.reviews import build_is_review_blocked_fn
from top_down_planning.domain.validators import ValidationResult

PlanView = Literal["active", "audit", "ready", "issues"]


def item_snapshot(item: PlanItem, display_number: str, *, depth: int) -> dict[str, Any]:
    payload = {
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
    if item.superseded_by is not None:
        payload["superseded_by"] = item.superseded_by
    return payload


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


def _plan_metadata(plan: Plan) -> dict[str, Any]:
    return {
        "scope": plan.scope.to_dict(),
        "boundaries": list(plan.boundaries),
        "constraints": list(plan.constraints),
        "assumptions": list(plan.assumptions),
        "acceptance": list(plan.acceptance),
    }


def build_hierarchy_snapshot(
    plan: Plan,
    *,
    limits: PlanningLimits,
    view: str,
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
        "view": view,
        "revision": plan.revision,
        "items": items,
        "planning_budget": budgets,
        **_plan_metadata(plan),
    }


def build_active_view(
    plan: Plan,
    *,
    limits: PlanningLimits,
    root_id: str | None = None,
    depth: int | None = None,
) -> dict[str, Any]:
    """Active inspection view: current hierarchy only (excludes removed/superseded)."""

    return build_hierarchy_snapshot(
        plan,
        limits=limits,
        view="active",
        root_id=root_id,
        depth=depth,
    )


def _inactive_items_related_to_subtree(
    inactive: list[PlanItem],
    related: set[str],
) -> list[PlanItem]:
    """Include inactive records reachable from the visible subtree via parent links."""

    expanded = set(related)
    changed = True
    while changed:
        changed = False
        for item in inactive:
            if item.id in expanded:
                continue
            if item.parent_id in expanded:
                expanded.add(item.id)
                changed = True
                continue
            if item.superseded_by is not None and item.superseded_by in expanded:
                expanded.add(item.id)
                changed = True
    return [item for item in inactive if item.id in expanded]


def build_audit_view(
    plan: Plan,
    *,
    limits: PlanningLimits,
    root_id: str | None = None,
    depth: int | None = None,
) -> dict[str, Any]:
    """Audit inspection view: active tree plus inactive records and supersession links."""

    payload = build_hierarchy_snapshot(
        plan, limits=limits, view="audit", root_id=root_id, depth=depth
    )

    active_ids = {item["id"] for item in payload["items"]}
    inactive = sorted(
        (
            item
            for item in plan.items.values()
            if item.id not in active_ids and not is_active_item(item)
        ),
        key=lambda item: item.id,
    )
    # When a subtree root filter is set, walk inactive ancestry so supersession
    # chains under inactive parents remain inspectable.
    if root_id is not None:
        related = set(active_ids)
        related.add(root_id)
        inactive = _inactive_items_related_to_subtree(inactive, related)

    for item in inactive:
        payload["items"].append(
            item_snapshot(
                item,
                display_number="",
                depth=item_depth(plan, item.id),
            )
        )
    return payload


def build_plan_review_snapshot(
    plan: Plan,
    *,
    limits: PlanningLimits,
) -> dict[str, Any]:
    """Bounded plan artifact for reviewer packages (proposal §4.3, §5.2)."""

    snapshot = build_active_view(plan, limits=limits)
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


def build_run_status_view(
    run: dict[str, Any],
    *,
    plan_revision: int | None = None,
) -> dict[str, Any]:
    """Agent-facing run status projection (proposal §8, §22)."""

    digests = dict(run.get("digests") or {})
    payload: dict[str, Any] = {
        "id": run["id"],
        "revision": run["revision"],
        "schema_version": run.get("schema_version"),
        "status": run.get("status"),
        "phase": run.get("phase"),
        "outcome": run.get("outcome"),
        "phase_action_id": run.get("phase_action_id"),
        "digests": {
            "config_contract": digests.get("config_contract"),
            "config_execution": digests.get("config_execution"),
            "plan": digests.get("plan"),
            "output": digests.get("output"),
        },
    }
    if plan_revision is not None:
        payload["plan_revision"] = plan_revision
    stop = run.get("stop")
    if isinstance(stop, dict):
        payload["stop"] = dict(stop)
    return payload
