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
    PLAN_ROOT_ITEM_ID,
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

_EXPAND_BRANCH_HINT = "See tdp agent example expand-branch for inline depends_on with temp ids."


def _stable_id(prefix: str = "item") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _resolve_id(item_id: str, id_map: dict[str, str]) -> str:
    return id_map.get(item_id, item_id)


def _normalize_depends_on(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return list(raw)
    raise InvalidMutationError(
        "depends_on must be a string or array of item ids or temp_id values"
    )


def _normalize_single_dependency(raw: Any, *, field: str = "depends_on") -> str:
    values = _normalize_depends_on(raw)
    if len(values) != 1:
        raise InvalidMutationError(
            f"{field} requires exactly one dependency target (string or single-element array)"
        )
    return values[0]


def _claim_temp_id(temp_id: str | None, materialized_temp_ids: set[str]) -> None:
    if not temp_id:
        return
    if temp_id in materialized_temp_ids:
        raise InvalidMutationError(f"duplicate temp_id in transaction: {temp_id!r}")
    materialized_temp_ids.add(temp_id)


def _preregister_temp_ids(operations: list[Operation], id_map: dict[str, str]) -> None:
    for op in operations:
        if op.get("op") not in {"add_item", "supersede_item"}:
            continue
        temp_id = op.get("temp_id")
        if temp_id and temp_id not in id_map:
            id_map[temp_id] = _stable_id()


def _dependency_error_hint(dep_raw: str, resolved: str, id_map: dict[str, str]) -> str:
    del id_map
    if dep_raw != resolved:
        return (
            f"Unknown temp_id {dep_raw!r}; reference temp_id values from add_item ops "
            f"in the same batch. {_EXPAND_BRANCH_HINT}"
        )
    return _EXPAND_BRANCH_HINT


def _raise_unknown_dependency(dep_raw: str, resolved: str, id_map: dict[str, str]) -> None:
    raise UnknownItemError(resolved, hint=_dependency_error_hint(dep_raw, resolved, id_map))


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
        raise InvalidMutationError(
            "parent_id is required; only the canonical root may have no parent"
        )
    _require_active_item(plan, parent_id)


def _guard_canonical_root(item_id: str, operation: str) -> None:
    if item_id == PLAN_ROOT_ITEM_ID:
        raise InvalidMutationError(
            f"{operation} is not allowed on the canonical root {PLAN_ROOT_ITEM_ID!r}"
        )


def _validate_depends_on(
    plan: Plan,
    depends_on: list[str],
    id_map: dict[str, str],
    *,
    item_id: str | None = None,
    dep_raw_values: list[str] | None = None,
) -> None:
    pending_stable_ids = set(id_map.values())
    raw_values = dep_raw_values if dep_raw_values is not None else depends_on

    for index, dep in enumerate(depends_on):
        dep_raw = raw_values[index] if index < len(raw_values) else dep
        resolved = _resolve_id(dep_raw, id_map)
        if item_id is not None and resolved == item_id:
            raise InvalidMutationError("self-dependency is not allowed")
        if resolved not in plan.items:
            if resolved in pending_stable_ids:
                continue
            _raise_unknown_dependency(dep_raw, resolved, id_map)
        if not is_active_item(plan.items[resolved]):
            raise InvalidMutationError(f"dependency target is not active: {resolved}")


def _item_payload_from_op(op: Operation) -> dict[str, Any]:
    if "item" not in op:
        raise InvalidMutationError("add_item requires an item payload")
    return dict(op["item"])


def _build_item(item_id: str, parent_id: str | None, order_key: str, payload: dict[str, Any]) -> PlanItem:
    from top_down_planning.domain.plan_schema import normalize_plan_item_payload

    if payload.get("planning_status") not in (None, "open"):
        raise InvalidMutationError(
            "new items must use planning_status open; use supersede_item or remove_item"
        )
    try:
        normalized = normalize_plan_item_payload(
            {
                **payload,
                "id": item_id,
                "parent_id": parent_id,
                "order_key": order_key,
                "planning_status": "open",
            }
        )
    except ValueError as exc:
        raise InvalidMutationError(str(exc)) from exc
    return PlanItem(
        id=normalized["id"],
        parent_id=normalized["parent_id"],
        order_key=normalized["order_key"],
        title=normalized["title"],
        outcome=normalized["outcome"],
        scope=Scope.from_dict(normalized["scope"]),
        boundaries=list(normalized["boundaries"]),
        depends_on=list(normalized["depends_on"]),
        acceptance=list(normalized["acceptance"]),
        risks=list(normalized["risks"]),
        source_refs=list(normalized["source_refs"]),
        planning_status=normalized["planning_status"],  # type: ignore[arg-type]
        kind=normalized["kind"],  # type: ignore[arg-type]
    )


def _inbound_dependency_users(plan: Plan, item_id: str) -> list[str]:
    return [
        other.id
        for other in plan.items.values()
        if item_id in other.depends_on and is_active_item(other)
    ]


def _stable_id_for_temp(temp_id: str | None, id_map: dict[str, str]) -> str:
    if temp_id:
        if temp_id not in id_map:
            id_map[temp_id] = _stable_id()
        return id_map[temp_id]
    return _stable_id()


def _apply_add_item(
    plan: Plan,
    op: Operation,
    id_map: dict[str, str],
    changed: set[str],
    *,
    materialized_temp_ids: set[str],
) -> None:
    temp_id = op.get("temp_id")
    _claim_temp_id(temp_id, materialized_temp_ids)
    stable = _stable_id_for_temp(temp_id, id_map)

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
    raw_depends_on = _normalize_depends_on(payload.get("depends_on"))
    depends_on = [_resolve_id(dep, id_map) for dep in raw_depends_on]
    _validate_depends_on(
        plan,
        depends_on,
        id_map,
        item_id=stable,
        dep_raw_values=raw_depends_on,
    )
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
    if item_id == PLAN_ROOT_ITEM_ID and "kind" in patch:
        kind = patch["kind"]
        if kind != "aggregate":
            raise InvalidMutationError(
                f"canonical root {PLAN_ROOT_ITEM_ID!r} must remain kind aggregate"
            )

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
    _guard_canonical_root(item_id, "move_subtree")
    old_parent = item.parent_id
    _require_active_parent(plan, new_parent_id)
    move_item_subtree(plan, item_id, new_parent_id, placement)
    changed.add(item_id)
    if old_parent is not None:
        changed.add(old_parent)
    if new_parent_id is not None:
        changed.add(new_parent_id)


def _apply_supersede_item(
    plan: Plan,
    op: Operation,
    id_map: dict[str, str],
    changed: set[str],
    *,
    materialized_temp_ids: set[str],
) -> None:
    item_id = _resolve_id(op["item_id"], id_map)
    _guard_canonical_root(item_id, "supersede_item")
    old_item = _require_active_item(plan, item_id)
    if children_of(plan, item_id):
        raise InvalidMutationError(
            "supersede_item requires the item to have no active children"
        )

    replacement_temp_id = op.get("temp_id")
    _claim_temp_id(replacement_temp_id, materialized_temp_ids)
    replacement_id = _stable_id_for_temp(replacement_temp_id, id_map)

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
    _guard_canonical_root(item_id, "remove_item")
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
    dep_raw = _normalize_single_dependency(op["depends_on"])
    depends_on = _resolve_id(dep_raw, id_map)
    item = _require_active_item(plan, item_id)
    _validate_depends_on(
        plan,
        [depends_on],
        id_map,
        item_id=item_id,
        dep_raw_values=[dep_raw],
    )
    if depends_on in item.depends_on:
        raise InvalidMutationError(f"duplicate dependency edge: {item_id} -> {depends_on}")

    item.depends_on.append(depends_on)
    changed.add(item_id)
    assert_no_dependency_cycles(plan)


def _apply_remove_dependency(plan: Plan, op: Operation, id_map: dict[str, str], changed: set[str]) -> None:
    item_id = _resolve_id(op["item_id"], id_map)
    dep_raw = _normalize_single_dependency(op["depends_on"])
    depends_on = _resolve_id(dep_raw, id_map)
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
    raw_depends_on = _normalize_depends_on(op.get("depends_on"))
    depends_on = [_resolve_id(dep, id_map) for dep in raw_depends_on]
    if len(set(depends_on)) != len(depends_on):
        raise InvalidMutationError("duplicate dependency targets in replace_dependencies")
    _validate_depends_on(
        plan,
        depends_on,
        id_map,
        item_id=item_id,
        dep_raw_values=raw_depends_on,
    )

    item.depends_on = depends_on
    changed.add(item_id)
    assert_no_dependency_cycles(plan)


_APPLY_HANDLERS = {
    "update_item": _apply_update_item,
    "update_plan": _apply_update_plan,
    "move_subtree": _apply_move_subtree,
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
    materialized_temp_ids: set[str] = set()

    _preregister_temp_ids(operations, id_map)

    for op in operations:
        op_name = op.get("op")
        if op_name == "remove_item":
            _apply_remove_item(working, op, id_map, changed, reviews=reviews)
            continue
        if op_name == "add_item":
            _apply_add_item(
                working,
                op,
                id_map,
                changed,
                materialized_temp_ids=materialized_temp_ids,
            )
            continue
        if op_name == "supersede_item":
            _apply_supersede_item(
                working,
                op,
                id_map,
                changed,
                materialized_temp_ids=materialized_temp_ids,
            )
            continue
        handler = _APPLY_HANDLERS.get(op_name)
        if handler is None:
            raise InvalidMutationError(f"unsupported operation: {op_name!r}")
        handler(working, op, id_map, changed)

    assert_no_dependency_cycles(working)

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
