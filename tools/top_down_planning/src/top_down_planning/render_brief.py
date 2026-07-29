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
    """Return actionable leaf items in deterministic order."""
    leaves = [
        item
        for item in plan.plan
        if item.decomposition_status == DecompositionStatus.ACTIONABLE
        and _is_leaf(plan, item.id)
    ]
    return sorted(leaves, key=lambda item: item.order)


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
        "The decomposition breakdown below is the **authoritative scope** for "
        "deliverables. The output goal defines format and schema; this brief "
        "defines which items must appear and what must be preserved.",
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
            if item.blocked_constraint_code is not None:
                lines.append(
                    f"  - Constraint: {item.blocked_constraint_code.value}"
                )
            if item.blocked_required_min_children is not None:
                lines.append(
                    f"  - Required min children: {item.blocked_required_min_children}"
                )
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
