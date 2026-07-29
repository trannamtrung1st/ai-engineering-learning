"""Derive render instructions and coverage checks from canonical plan state."""

from __future__ import annotations

from top_down_planning.item_format import format_leaf_brief_section
from top_down_planning.models import (
    DecompositionStatus,
    PlanItem,
    PlanState,
)


def _is_leaf(plan: PlanState, item_id: str) -> bool:
    return not any(child.parent_id == item_id for child in plan.plan)


def actionable_leaf_items(plan: PlanState) -> list[PlanItem]:
    """Return actionable leaf items in dependency-safe topological order."""
    leaves = [
        item
        for item in plan.plan
        if item.decomposition_status == DecompositionStatus.ACTIONABLE
        and _is_leaf(plan, item.id)
    ]
    return _topological_actionable_order(plan, leaves)


def _topological_actionable_order(
    plan: PlanState,
    leaves: list[PlanItem],
) -> list[PlanItem]:
    """Stable topological sort using creation order as tie-breaker."""
    leaf_ids = {item.id for item in leaves}
    if not leaf_ids:
        return []

    order_index = {item.id: item.order for item in leaves}
    in_degree: dict[str, int] = {item_id: 0 for item_id in leaf_ids}
    dependents: dict[str, list[str]] = {item_id: [] for item_id in leaf_ids}

    for item in leaves:
        for dep in item.dependencies:
            if dep in leaf_ids:
                in_degree[item.id] += 1
                dependents[dep].append(item.id)

    for dep_id, waiting in dependents.items():
        waiting.sort(key=lambda item_id: (order_index[item_id], item_id))

    ready = sorted(
        (item_id for item_id, degree in in_degree.items() if degree == 0),
        key=lambda item_id: (order_index[item_id], item_id),
    )
    ordered: list[PlanItem] = []
    by_id = {item.id: item for item in leaves}

    while ready:
        current_id = ready.pop(0)
        ordered.append(by_id[current_id])
        for dependent_id in dependents[current_id]:
            in_degree[dependent_id] -= 1
            if in_degree[dependent_id] == 0:
                ready.append(dependent_id)
                ready.sort(key=lambda item_id: (order_index[item_id], item_id))

    if len(ordered) != len(leaves):
        return sorted(leaves, key=lambda item: (item.order, item.id))
    return ordered


def blocked_leaf_items(plan: PlanState) -> list[PlanItem]:
    leaves = [
        item
        for item in plan.plan
        if item.decomposition_status == DecompositionStatus.BLOCKED
        and _is_leaf(plan, item.id)
    ]
    return sorted(leaves, key=lambda item: item.order)


def _dependency_labels(plan: PlanState, item: PlanItem) -> list[str]:
    labels: list[str] = []
    for dep in item.dependencies:
        dep_item = plan.item_by_id(dep)
        labels.append(dep_item.title if dep_item else dep)
    return labels


def build_render_brief(plan: PlanState) -> str:
    """Build a markdown brief that defines the authoritative render scope."""
    leaves = actionable_leaf_items(plan)
    blocked = blocked_leaf_items(plan)
    lines: list[str] = [
        "# Render brief",
        "",
        "The decomposition breakdown below defines **authoritative ownership and "
        "deliverables**. The output goal defines format and schema; this brief "
        "defines which items must appear and what must be preserved.",
        "",
        "Named paths, examples, and investigation anchors in each item are "
        "starting surfaces, not exhaustive inventories, unless the source "
        "explicitly says otherwise.",
        "",
        f"## Actionable deliverable units ({len(leaves)})",
        "",
    ]

    if not leaves:
        lines.append("_No actionable leaf items._")
    else:
        for index, item in enumerate(leaves, start=1):
            lines.extend(format_leaf_brief_section(plan, item, index))

    if blocked:
        lines.extend(["", f"## Blocked items ({len(blocked)})", ""])
        for item in blocked:
            lines.append(f"- **{item.title}**")
            if item.blocked_reason:
                lines.append(f"  - Reason: {item.blocked_reason}")
            for note in item.notes:
                lines.append(f"  - Note: {note}")
            for risk in item.risks:
                lines.append(f"  - Risk: {risk}")
            for question in item.open_questions:
                lines.append(f"  - Open question: {question}")

    lines.extend(["", "## Hierarchy reference", ""])
    lines.extend(_render_hierarchy(plan, parent_id=None, prefix=""))
    return "\n".join(lines).rstrip() + "\n"


def _render_hierarchy(
    plan: PlanState,
    *,
    parent_id: str | None,
    prefix: str,
) -> list[str]:
    lines: list[str] = []
    children = plan.children_of(parent_id)
    for index, item in enumerate(children, start=1):
        number = f"{prefix}{index}" if prefix else str(index)
        status = item.decomposition_status.value
        lines.append(f"{number}. **{item.title}** ({status})")
        child_prefix = f"{number}."
        lines.extend(_render_hierarchy(plan, parent_id=item.id, prefix=child_prefix))
    return lines
