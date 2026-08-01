"""Atomic plan mutations and dependency graph checks (proposal §8.2, §8.3, §8.5)."""

from __future__ import annotations

import uuid
from typing import Any

from top_down_planning.domain.dependencies import assert_no_dependency_cycles
from top_down_planning.domain.errors import (
    InvalidMutationError,
    RevisionConflictError,
    UnknownItemError,
)
from top_down_planning.domain.models import (
    ApplyResult,
    Plan,
    PlanItem,
    PlanningLimits,
    Scope,
)
from top_down_planning.domain.plan_tree import (
    children_of,
    clone_plan,
    collect_budget_warnings,
    insert_item_at,
    is_active_item,
    move_item_subtree,
    recompact_active_sibling_order_keys,
)
from top_down_planning.domain.reviews import item_referenced_in_reviews

Operation = dict[str, Any]


def _stable_id(prefix: str = "item") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _resolve_id(item_id: str, id_map: dict[str, str]) -> str:
    return id_map.get(item_id, item_id)


def _require_item(plan: Plan, item_id: str) -> PlanItem:
    if item_id not in plan.items:
        raise UnknownItemError(item_id)
    return plan.items[item_id]


def _require_active_item(plan: Plan, item_id: str) -> PlanItem:
    item = _require_item(plan, item_id)
    if not is_active_item(item):
        raise InvalidMutationError(f"item is not active: {item_id}")
    return item


def _require_active_parent(plan: Plan, parent_id: str | None) -> None:
    if parent_id is None:
        return
    _require_active_item(plan, parent_id)


def _validate_depends_on(
    plan: Plan,
    depends_on: list[str],
    id_map: dict[str, str],
    *,
    item_id: str | None = None,
) -> None:
    for dep in depends_on:
        resolved = _resolve_id(dep, id_map)
        if item_id is not None and resolved == item_id:
            raise InvalidMutationError("self-dependency is not allowed")
        if resolved not in plan.items:
            raise UnknownItemError(resolved)
        if not is_active_item(plan.items[resolved]):
            raise InvalidMutationError(f"dependency target is not active: {resolved}")



def _item_payload_from_op(op: Operation) -> dict[str, Any]:
    if "item" not in op:
        raise InvalidMutationError("add_item requires an item payload")
    return dict(op["item"])


def _build_item(item_id: str, parent_id: str | None, order_key: str, payload: dict[str, Any]) -> PlanItem:
    if payload.get("planning_status") not in (None, "open"):
        raise InvalidMutationError(
            "new items must use planning_status open; use supersede_item or remove_item"
        )
    title = payload.get("title")
    if not title or not str(title).strip():
        raise InvalidMutationError("item title is required")
    kind = payload.get("kind")
    if kind is None:
        raise InvalidMutationError("item kind is required")
    if kind not in ("aggregate", "work"):
        raise InvalidMutationError(f"invalid plan item kind: {kind!r}")
    return PlanItem(
        id=item_id,
        parent_id=parent_id,
        order_key=order_key,
        title=str(title).strip(),
        outcome=payload.get("outcome", ""),
        scope=Scope.from_dict(payload.get("scope")),
        boundaries=list(payload.get("boundaries") or []),
        depends_on=list(payload.get("depends_on") or []),
        acceptance=list(payload.get("acceptance") or []),
        risks=list(payload.get("risks") or []),
        source_refs=list(payload.get("source_refs") or []),
        planning_status="open",
        kind=kind,
    )


def _inbound_dependency_users(plan: Plan, item_id: str) -> list[str]:
    return [
        other.id
        for other in plan.items.values()
        if item_id in other.depends_on and is_active_item(other)
    ]


def _apply_add_item(plan: Plan, op: Operation, id_map: dict[str, str], changed: set[str]) -> None:
    temp_id = op.get("temp_id")
    stable = _stable_id()
    if temp_id:
        id_map[temp_id] = stable

    parent_id = op.get("parent_id")
    if parent_id is not None:
        parent_id = _resolve_id(parent_id, id_map)
    _require_active_parent(plan, parent_id)
    placement = op.get("placement")
    if placement:
        placement = {
            key: _resolve_id(value, id_map) if key in {"before", "after"} else value
            for key, value in placement.items()
        }

    payload = _item_payload_from_op(op)
    depends_on = [_resolve_id(dep, id_map) for dep in payload.get("depends_on") or []]
    _validate_depends_on(plan, depends_on, id_map, item_id=stable)
    payload = dict(payload)
    payload["depends_on"] = depends_on
    item = _build_item(stable, parent_id, "0000000000", payload)
    insert_item_at(plan, item, parent_id, placement)
    changed.add(stable)
    if parent_id is not None:
        changed.add(parent_id)


_UPDATE_ITEM_PATCH_FIELDS = frozenset(
    {
        "title",
        "outcome",
        "scope",
        "boundaries",
        "acceptance",
        "risks",
        "source_refs",
        "planning_status",
        "kind",
    }
)


def _apply_update_item(plan: Plan, op: Operation, id_map: dict[str, str], changed: set[str]) -> None:
    item_id = _resolve_id(op["item_id"], id_map)
    item = _require_active_item(plan, item_id)
    patch = op.get("patch")
    if not patch:
        raise InvalidMutationError("update_item requires a patch payload")

    unknown_fields = sorted(set(patch) - _UPDATE_ITEM_PATCH_FIELDS)
    if unknown_fields:
        joined = ", ".join(unknown_fields)
        raise InvalidMutationError(
            f"update_item patch contains unsupported fields: {joined}"
        )

    if "planning_status" in patch:
        raise InvalidMutationError("update_item cannot change planning_status; use supersede_item or remove_item")

    for field_name in ("title", "outcome", "boundaries", "acceptance", "risks", "source_refs"):
        if field_name in patch:
            value = patch[field_name]
            if field_name == "title" and (not value or not str(value).strip()):
                raise InvalidMutationError("item title is required")
            if field_name in ("boundaries", "acceptance", "risks", "source_refs"):
                if not isinstance(value, list):
                    raise InvalidMutationError(f"update_item {field_name} must be a list")
                value = list(value)
            setattr(item, field_name, value)
    if "scope" in patch:
        item.scope = Scope.from_dict(patch["scope"])
    if "kind" in patch:
        kind = patch["kind"]
        if kind is None:
            raise InvalidMutationError("item kind is required")
        if kind not in ("aggregate", "work"):
            raise InvalidMutationError(f"invalid plan item kind: {kind!r}")
        item.kind = kind
    changed.add(item_id)


_UPDATE_PLAN_PATCH_FIELDS = frozenset(
    {"scope", "boundaries", "constraints", "assumptions", "acceptance", "risks"}
)


def _apply_update_plan(plan: Plan, op: Operation, id_map: dict[str, str], changed: set[str]) -> None:
    del id_map, changed
    patch = op.get("patch")
    if not isinstance(patch, dict) or not patch:
        raise InvalidMutationError("update_plan requires a non-empty patch payload")

    unknown_fields = sorted(set(patch) - _UPDATE_PLAN_PATCH_FIELDS)
    if unknown_fields:
        joined = ", ".join(unknown_fields)
        raise InvalidMutationError(
            f"update_plan patch contains unsupported fields: {joined}"
        )

    if "scope" in patch:
        plan.scope = Scope.from_dict(patch["scope"])
    for field_name in ("boundaries", "constraints", "assumptions", "acceptance", "risks"):
        if field_name in patch:
            value = patch[field_name]
            if not isinstance(value, list):
                raise InvalidMutationError(f"update_plan {field_name} must be a list")
            setattr(plan, field_name, list(value))


def _apply_move_subtree(plan: Plan, op: Operation, id_map: dict[str, str], changed: set[str]) -> None:
    item_id = _resolve_id(op["item_id"], id_map)
    new_parent_id = op.get("new_parent_id")
    if new_parent_id is not None:
        new_parent_id = _resolve_id(new_parent_id, id_map)
    placement = op.get("placement")
    if placement:
        placement = {
            key: _resolve_id(value, id_map) if key in {"before", "after"} else value
            for key, value in placement.items()
        }

    item = _require_active_item(plan, item_id)
    old_parent = item.parent_id
    _require_active_parent(plan, new_parent_id)
    move_item_subtree(plan, item_id, new_parent_id, placement)
    changed.add(item_id)
    if old_parent is not None:
        changed.add(old_parent)
    if new_parent_id is not None:
        changed.add(new_parent_id)


def _apply_supersede_item(plan: Plan, op: Operation, id_map: dict[str, str], changed: set[str]) -> None:
    item_id = _resolve_id(op["item_id"], id_map)
    old_item = _require_active_item(plan, item_id)
    if children_of(plan, item_id):
        raise InvalidMutationError(
            "supersede_item requires the item to have no active children"
        )

    temp_id = op.get("temp_id")
    replacement_id = _stable_id()
    if temp_id:
        id_map[temp_id] = replacement_id

    payload = op.get("replacement")
    if payload is None:
        raise InvalidMutationError("supersede_item requires a replacement payload")
    payload = dict(payload)
    replacement = _build_item(
        replacement_id,
        old_item.parent_id,
        old_item.order_key,
        payload,
    )
    replacement.depends_on = list(old_item.depends_on)
    _validate_depends_on(plan, replacement.depends_on, id_map, item_id=replacement_id)

    old_item.planning_status = "superseded"
    old_item.superseded_by = replacement_id
    plan.items[replacement_id] = replacement

    for other in plan.items.values():
        if other.id == replacement_id:
            continue
        if item_id in other.depends_on:
            other.depends_on = [
                replacement_id if dep == item_id else dep for dep in other.depends_on
            ]
            changed.add(other.id)

    changed.update({item_id, replacement_id})


def _apply_remove_item(
    plan: Plan,
    op: Operation,
    id_map: dict[str, str],
    changed: set[str],
    *,
    reviews: list[dict[str, Any]] | None = None,
) -> None:
    item_id = _resolve_id(op["item_id"], id_map)
    item = _require_active_item(plan, item_id)
    if children_of(plan, item_id):
        raise InvalidMutationError("remove_item requires the item to have no children")
    if _inbound_dependency_users(plan, item_id):
        raise InvalidMutationError("remove_item requires no inbound dependency references")
    if reviews is None:
        raise InvalidMutationError(
            "remove_item requires review history context; pass reviews from the run store"
        )
    if item_referenced_in_reviews(reviews, item_id):
        raise InvalidMutationError(
            "remove_item is not allowed for items with review history; use supersede_item"
        )

    parent_id = item.parent_id
    item.planning_status = "removed"
    recompact_active_sibling_order_keys(plan, parent_id)
    changed.add(item_id)
    if parent_id is not None:
        changed.add(parent_id)


def _apply_add_dependency(plan: Plan, op: Operation, id_map: dict[str, str], changed: set[str]) -> None:
    item_id = _resolve_id(op["item_id"], id_map)
    depends_on = _resolve_id(op["depends_on"], id_map)
    item = _require_active_item(plan, item_id)
    _validate_depends_on(plan, [depends_on], id_map, item_id=item_id)
    if depends_on in item.depends_on:
        raise InvalidMutationError(f"duplicate dependency edge: {item_id} -> {depends_on}")

    item.depends_on.append(depends_on)
    changed.add(item_id)
    assert_no_dependency_cycles(plan)


def _apply_remove_dependency(plan: Plan, op: Operation, id_map: dict[str, str], changed: set[str]) -> None:
    item_id = _resolve_id(op["item_id"], id_map)
    depends_on = _resolve_id(op["depends_on"], id_map)
    item = _require_active_item(plan, item_id)
    if depends_on not in item.depends_on:
        raise InvalidMutationError(f"missing dependency edge: {item_id} -> {depends_on}")
    item.depends_on.remove(depends_on)
    changed.add(item_id)


def _apply_replace_dependencies(
    plan: Plan,
    op: Operation,
    id_map: dict[str, str],
    changed: set[str],
) -> None:
    item_id = _resolve_id(op["item_id"], id_map)
    item = _require_active_item(plan, item_id)
    depends_on = [_resolve_id(dep, id_map) for dep in op.get("depends_on") or []]
    if len(set(depends_on)) != len(depends_on):
        raise InvalidMutationError("duplicate dependency targets in replace_dependencies")
    _validate_depends_on(plan, depends_on, id_map, item_id=item_id)

    item.depends_on = depends_on
    changed.add(item_id)
    assert_no_dependency_cycles(plan)


_APPLY_HANDLERS = {
    "add_item": _apply_add_item,
    "update_item": _apply_update_item,
    "update_plan": _apply_update_plan,
    "move_subtree": _apply_move_subtree,
    "supersede_item": _apply_supersede_item,
    "add_dependency": _apply_add_dependency,
    "remove_dependency": _apply_remove_dependency,
    "replace_dependencies": _apply_replace_dependencies,
}


def apply_operations(
    plan: Plan,
    base_revision: int,
    operations: list[Operation],
    *,
    limits: PlanningLimits | None = None,
    reviews: list[dict[str, Any]] | None = None,
) -> ApplyResult:
    """Apply a list of plan operations atomically against base_revision."""

    if plan.revision != base_revision:
        raise RevisionConflictError(base_revision, plan.revision)

    limits = limits or PlanningLimits()
    working = clone_plan(plan)
    id_map: dict[str, str] = {}
    changed: set[str] = set()

    for op in operations:
        op_name = op.get("op")
        if op_name == "remove_item":
            _apply_remove_item(working, op, id_map, changed, reviews=reviews)
            continue
        handler = _APPLY_HANDLERS.get(op_name)
        if handler is None:
            raise InvalidMutationError(f"unsupported operation: {op_name!r}")
        handler(working, op, id_map, changed)

    working.revision = plan.revision + 1
    warnings, budgets = collect_budget_warnings(working, changed, limits)

    return ApplyResult(
        plan=working,
        revision=working.revision,
        id_map=id_map,
        changed_item_ids=sorted(changed),
        warnings=warnings,
        budgets=budgets,
    )
