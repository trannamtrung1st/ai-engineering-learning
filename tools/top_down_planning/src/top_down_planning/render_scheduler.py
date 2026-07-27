"""Breadth-first per-node render scheduling."""

from __future__ import annotations

from collections import defaultdict, deque

from top_down_planning.models import (
    DecompositionStatus,
    PlanItem,
    PlanState,
    RenderConfig,
    RenderManifestItem,
    RenderNodePhase,
    RenderScope,
)
from top_down_planning.render_brief import (
    deterministic_skip_decision,
    eligible_render_nodes,
    is_render_eligible,
)


def build_progressive_schedule(
    plan: PlanState,
    *,
    render_config: RenderConfig,
    phase: RenderNodePhase = RenderNodePhase.RENDER,
    render_dependencies: dict[str, list[str]] | None = None,
) -> tuple[list[RenderManifestItem], list[str]]:
    errors: list[str] = []
    nodes = _nodes_in_scope(plan, render_config.scope)
    if not nodes:
        return [], errors

    node_by_id = {item.id: item for item in nodes}
    depth_by_id = {item.id: item.depth for item in nodes}
    parent_by_id = {item.id: item.parent_id for item in nodes}

    render_deps = render_dependencies or {}
    for node_id, deps in render_deps.items():
        for dep in deps:
            if dep not in node_by_id:
                errors.append(f"unknown render dependency {dep!r} for {node_id!r}")
            elif depth_by_id.get(dep, 0) > depth_by_id.get(node_id, 0):
                errors.append(
                    f"invalid render dependency: {node_id!r} is shallower than {dep!r}"
                )

    if errors:
        return [], errors

    cycle_error = _detect_dependency_cycle(render_deps)
    if cycle_error:
        errors.append(cycle_error)
        return [], errors

    waves = _group_by_depth(nodes)
    items: list[RenderManifestItem] = []
    order_counter = 0

    for wave, wave_nodes in enumerate(waves):
        groups = _generation_groups_for_wave(
            wave_nodes,
            parent_by_id=parent_by_id,
            render_deps=render_deps,
        )
        for group_index, group_nodes in enumerate(groups):
            for item in group_nodes:
                order_counter += 1
                items.append(
                    RenderManifestItem(
                        plan_item_id=item.id,
                        parent_id=item.parent_id,
                        depth=item.depth,
                        order=order_counter,
                        wave=wave,
                        generation_group=group_index,
                        phase=phase,
                        title=item.title,
                        dependencies=list(render_deps.get(item.id, [])),
                        top_level_branch_id=_top_level_branch_id(plan, item),
                    )
                )

    return items, errors


def _nodes_in_scope(plan: PlanState, scope: RenderScope) -> list[PlanItem]:
    if scope == RenderScope.ACTIONABLE_NODES:
        return sorted(
            [
                item
                for item in plan.plan
                if item.decomposition_status == DecompositionStatus.ACTIONABLE
            ],
            key=lambda entry: (entry.depth, entry.order, entry.id),
        )
    return eligible_render_nodes(plan)


def _group_by_depth(nodes: list[PlanItem]) -> list[list[PlanItem]]:
    by_depth: dict[int, list[PlanItem]] = defaultdict(list)
    for item in nodes:
        by_depth[item.depth].append(item)
    return [
        sorted(by_depth[depth], key=lambda entry: (entry.order, entry.id))
        for depth in sorted(by_depth.keys())
    ]


def _generation_groups_for_wave(
    wave_nodes: list[PlanItem],
    *,
    parent_by_id: dict[str, str | None],
    render_deps: dict[str, list[str]],
) -> list[list[PlanItem]]:
    node_ids = {item.id for item in wave_nodes}
    indegree: dict[str, int] = {item.id: 0 for item in wave_nodes}
    adjacency: dict[str, list[str]] = defaultdict(list)

    for item in wave_nodes:
        prereqs: set[str] = set()
        parent = parent_by_id.get(item.id)
        if parent and parent in node_ids:
            prereqs.add(parent)
        for dep in render_deps.get(item.id, []):
            if dep in node_ids:
                prereqs.add(dep)
        for prereq in prereqs:
            adjacency[prereq].append(item.id)
            indegree[item.id] += 1

    queue = deque(
        sorted(
            [item for item in wave_nodes if indegree[item.id] == 0],
            key=lambda entry: (entry.order, entry.id),
        )
    )
    groups: list[list[PlanItem]] = []
    while queue:
        current_group = list(queue)
        queue.clear()
        groups.append(current_group)
        for item in current_group:
            for dependent in sorted(adjacency[item.id]):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    dependent_item = next(
                        node for node in wave_nodes if node.id == dependent
                    )
                    queue.append(dependent_item)
        queue = deque(sorted(queue, key=lambda entry: (entry.order, entry.id)))

    if sum(len(group) for group in groups) != len(wave_nodes):
        return [wave_nodes]
    return groups


def _detect_dependency_cycle(render_deps: dict[str, list[str]]) -> str | None:
    visited: set[str] = set()
    stack: set[str] = set()

    def visit(node_id: str) -> str | None:
        if node_id in stack:
            return f"render dependency cycle detected at {node_id!r}"
        if node_id in visited:
            return None
        visited.add(node_id)
        stack.add(node_id)
        for dep in render_deps.get(node_id, []):
            error = visit(dep)
            if error:
                return error
        stack.remove(node_id)
        return None

    for node_id in render_deps:
        error = visit(node_id)
        if error:
            return error
    return None


def _top_level_branch_id(plan: PlanState, item: PlanItem) -> str:
    current = item
    while current.parent_id is not None:
        parent = plan.item_by_id(current.parent_id)
        if parent is None:
            break
        current = parent
    return current.id


def unique_waves(items: list[RenderManifestItem]) -> list[int]:
    return sorted({item.wave for item in items})


def groups_in_wave(items: list[RenderManifestItem], wave: int) -> list[int]:
    return sorted({item.generation_group for item in items if item.wave == wave})


def build_rollup_schedule(
    plan: PlanState,
    *,
    render_config: RenderConfig,
) -> tuple[list[RenderManifestItem], list[str]]:
    nodes = _nodes_in_scope(plan, render_config.scope)
    if not nodes:
        return [], []
    by_depth: dict[int, list[PlanItem]] = defaultdict(list)
    for item in nodes:
        by_depth[item.depth].append(item)
    items: list[RenderManifestItem] = []
    order_counter = 0
    reverse_depths = sorted(by_depth.keys(), reverse=True)
    for wave_index, depth in enumerate(reverse_depths):
        wave_nodes = sorted(by_depth[depth], key=lambda entry: (entry.order, entry.id))
        for item in wave_nodes:
            order_counter += 1
            items.append(
                RenderManifestItem(
                    plan_item_id=item.id,
                    parent_id=item.parent_id,
                    depth=item.depth,
                    order=order_counter,
                    wave=wave_index,
                    generation_group=0,
                    phase=RenderNodePhase.ROLLUP,
                    title=item.title,
                    top_level_branch_id=_top_level_branch_id(plan, item),
                )
            )
    return items, []
