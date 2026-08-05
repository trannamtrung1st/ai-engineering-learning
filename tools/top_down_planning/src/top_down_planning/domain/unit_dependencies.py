"""Derive unit-level dependency graphs from approved plan item edges."""

from __future__ import annotations

from typing import Any

from top_down_planning.domain.models import Plan
from top_down_planning.domain.plan_tree import is_active_item
from top_down_planning.domain.sub_tdp_units import SubTdpUnit
from top_down_planning.domain.unit_plan import collect_assigned_item_ids


class UnitDependencyCycleError(ValueError):
    """Raised when prepared unit dependencies form a cycle."""


def item_to_owning_unit(plan: Plan, units: list[SubTdpUnit]) -> dict[str, str]:
    """Map each assigned active item to its owning unit root id."""

    ownership: dict[str, str] = {}
    for unit in units:
        for item_id in collect_assigned_item_ids(plan, unit.plan_item_id):
            if item_id in ownership and ownership[item_id] != unit.plan_item_id:
                raise ValueError(
                    f"item {item_id!r} assigned to multiple units: "
                    f"{ownership[item_id]!r} and {unit.plan_item_id!r}"
                )
            ownership[item_id] = unit.plan_item_id
    return ownership


def derive_unit_dependencies(
    plan: Plan,
    units: list[SubTdpUnit],
) -> dict[str, list[str]]:
    """
    Build unit_id -> sorted unique depends_on unit ids from item edges.

    Self-dependencies after normalization are dropped. Cross-unit edges are
    taken whenever an assigned item depends on an item owned by another unit.
    """

    ownership = item_to_owning_unit(plan, units)
    edges: dict[str, set[str]] = {unit.plan_item_id: set() for unit in units}

    for unit in units:
        for item_id in collect_assigned_item_ids(plan, unit.plan_item_id):
            item = plan.items.get(item_id)
            if item is None or not is_active_item(item):
                continue
            for dep_id in item.depends_on:
                dep_item = plan.items.get(dep_id)
                if dep_item is None or not is_active_item(dep_item):
                    continue
                owner = ownership.get(dep_id)
                if owner is None:
                    continue
                if owner != unit.plan_item_id:
                    edges[unit.plan_item_id].add(owner)

    return {
        unit_id: sorted(dep_ids)
        for unit_id, dep_ids in edges.items()
    }


def detect_unit_dependency_cycles(unit_deps: dict[str, list[str]]) -> None:
    """Raise UnitDependencyCycleError when the unit graph contains a cycle."""

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visited:
            return
        if node in visiting:
            raise UnitDependencyCycleError(
                f"unit dependency cycle detected involving {node!r}"
            )
        visiting.add(node)
        for dep in unit_deps.get(node) or []:
            visit(dep)
        visiting.remove(node)
        visited.add(node)

    for unit_id in sorted(unit_deps):
        visit(unit_id)


def classify_item_dependencies(
    plan: Plan,
    unit: SubTdpUnit,
    units: list[SubTdpUnit],
) -> dict[str, dict[str, Any]]:
    """
    For each assigned item, split depends_on into internal vs external.

    External prerequisites reference items owned by other units.
    """

    ownership = item_to_owning_unit(plan, units)
    assigned = set(collect_assigned_item_ids(plan, unit.plan_item_id))
    classified: dict[str, dict[str, Any]] = {}

    for item_id in collect_assigned_item_ids(plan, unit.plan_item_id):
        item = plan.items.get(item_id)
        if item is None:
            continue
        internal: list[str] = []
        external: list[dict[str, str]] = []
        for dep_id in item.depends_on:
            if dep_id in assigned:
                internal.append(dep_id)
                continue
            owner = ownership.get(dep_id)
            if owner is None or owner == unit.plan_item_id:
                continue
            external.append(
                {
                    "dependency_item_id": dep_id,
                    "owning_unit_id": owner,
                }
            )
        if internal or external:
            classified[item_id] = {"internal": internal, "external": external}
    return classified


def external_prerequisites_for_unit(
    plan: Plan,
    unit: SubTdpUnit,
    units: list[SubTdpUnit],
    *,
    owning_unit_contract_digests: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Deduplicated external prerequisite contracts for a unit snapshot.

    ``upstream_contract_digest`` is the owning unit's assigned-subtree contract
    digest (known at prepare time). Accepted child output digests are bound
    later at execution time as ``accepted_result`` attestations.
    """

    contracts = owning_unit_contract_digests or {}
    classified = classify_item_dependencies(plan, unit, units)
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for entry in classified.values():
        for ext in entry.get("external") or []:
            key = (ext["dependency_item_id"], ext["owning_unit_id"])
            if key in seen:
                continue
            seen.add(key)
            owner = ext["owning_unit_id"]
            contract = str(contracts.get(owner) or "").strip()
            if not contract:
                raise ValueError(
                    f"missing assigned-subtree contract digest for owning unit {owner!r}"
                )
            result.append(
                {
                    "dependency_item_id": ext["dependency_item_id"],
                    "owning_unit_id": owner,
                    "upstream_contract_digest": contract,
                    "required_output_refs": [],
                }
            )
    result.sort(key=lambda row: (row["owning_unit_id"], row["dependency_item_id"]))
    return result


__all__ = [
    "UnitDependencyCycleError",
    "classify_item_dependencies",
    "derive_unit_dependencies",
    "detect_unit_dependency_cycles",
    "external_prerequisites_for_unit",
    "item_to_owning_unit",
]
