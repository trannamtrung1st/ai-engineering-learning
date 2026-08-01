"""Item production contracts with plan-level scope/boundary merge."""

from __future__ import annotations

from typing import Any

from top_down_planning.domain.models import Plan, PlanItem, Scope


def merge_string_lists(*lists: list[str]) -> list[str]:
    """Concatenate lists in order, skipping blanks and case-insensitive duplicates."""

    merged: list[str] = []
    seen: set[str] = set()
    for entries in lists:
        for entry in entries:
            normalized = entry.strip()
            if not normalized:
                continue
            key = normalized.casefold()
            if key in seen:
                continue
            seen.add(key)
            merged.append(normalized)
    return merged


def has_meaningful_list_entries(entries: list[str]) -> bool:
    return any(entry.strip() for entry in entries)


def has_item_scope_contract(item: PlanItem) -> bool:
    return (
        has_meaningful_list_entries(item.scope.includes)
        or has_meaningful_list_entries(item.scope.excludes)
        or has_meaningful_list_entries(item.boundaries)
    )


def effective_scope(plan: Plan, item: PlanItem) -> Scope:
    """Merge plan-level and item-level scope (plan first, then item)."""

    return Scope(
        includes=merge_string_lists(plan.scope.includes, item.scope.includes),
        excludes=merge_string_lists(plan.scope.excludes, item.scope.excludes),
    )


def effective_boundaries(plan: Plan, item: PlanItem) -> list[str]:
    """Merge plan-level and item-level boundaries (plan first, then item)."""

    return merge_string_lists(plan.boundaries, item.boundaries)


def build_item_production_contract(
    plan: Plan,
    item_id: str,
    *,
    include_ancestor_path: bool = False,
) -> dict[str, Any]:
    """Canonical item contract for production manifests, ready snapshots, and review traceability."""

    item = plan.items[item_id]
    resolved_scope = effective_scope(plan, item)
    payload: dict[str, Any] = {
        "id": item.id,
        "title": item.title,
        "outcome": item.outcome,
        "kind": item.kind,
        "scope": item.scope.to_dict(),
        "boundaries": list(item.boundaries),
        "effective_scope": resolved_scope.to_dict(),
        "effective_boundaries": effective_boundaries(plan, item),
        "acceptance": list(item.acceptance),
        "risks": list(item.risks),
        "source_refs": list(item.source_refs),
        "depends_on": list(item.depends_on),
    }
    if include_ancestor_path:
        from top_down_planning.domain.plan_tree import ancestor_path

        payload["ancestor_path"] = ancestor_path(plan, item_id)
    return payload


__all__ = [
    "build_item_production_contract",
    "effective_boundaries",
    "effective_scope",
    "has_item_scope_contract",
    "has_meaningful_list_entries",
    "merge_string_lists",
]
