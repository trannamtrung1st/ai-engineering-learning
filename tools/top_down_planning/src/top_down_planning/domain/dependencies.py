"""Dependency graph helpers and cycle detection (proposal §7.3, §9.2)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from top_down_planning.domain.errors import DependencyCycleError
from top_down_planning.domain.models import Plan
from top_down_planning.domain.plan_tree import is_active_item


@dataclass(frozen=True)
class DependencyCycleIssue:
    code: Literal["dependency_cycle"]
    path: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "path": list(self.path)}


def active_dependency_edges(plan: Plan) -> dict[str, list[str]]:
    edges: dict[str, list[str]] = {}
    for item_id, item in plan.items.items():
        if not is_active_item(item):
            continue
        edges[item_id] = [
            dep
            for dep in item.depends_on
            if dep in plan.items and is_active_item(plan.items[dep])
        ]
    return edges


def dependency_cycle_path(edges: dict[str, list[str]], start_id: str) -> list[str] | None:
    visited: set[str] = set()
    stack: list[str] = []

    def dfs(node_id: str) -> list[str] | None:
        if node_id in stack:
            cycle_start = stack.index(node_id)
            return stack[cycle_start:] + [node_id]
        if node_id in visited:
            return None
        visited.add(node_id)
        stack.append(node_id)
        for dep_id in edges.get(node_id, []):
            cycle = dfs(dep_id)
            if cycle is not None:
                return cycle
        stack.pop()
        return None

    return dfs(start_id)


def find_dependency_cycle(plan: Plan) -> list[str] | None:
    edges = active_dependency_edges(plan)
    for item_id in edges:
        cycle = dependency_cycle_path(edges, item_id)
        if cycle is not None:
            return cycle
    return None


def dependency_cycle_issue(plan: Plan) -> DependencyCycleIssue | None:
    cycle = find_dependency_cycle(plan)
    if cycle is None:
        return None
    return DependencyCycleIssue(code="dependency_cycle", path=cycle)


def assert_no_dependency_cycles(plan: Plan) -> None:
    cycle = find_dependency_cycle(plan)
    if cycle is not None:
        raise DependencyCycleError(cycle)


def active_dependencies(plan: Plan, item_id: str) -> list[str]:
    return list(active_dependency_edges(plan).get(item_id, []))
