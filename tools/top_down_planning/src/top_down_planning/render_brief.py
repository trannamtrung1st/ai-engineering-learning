"""Derive render instructions and coverage checks from canonical plan state."""

from __future__ import annotations

from top_down_planning.models import (
    DecompositionStatus,
    PlanItem,
    PlanState,
    RenderDecisionKind,
)


def _is_leaf(plan: PlanState, item_id: str) -> bool:
    return not any(child.parent_id == item_id for child in plan.plan)


def is_render_eligible(item: PlanItem) -> bool:
    """Return True when a plan node may receive a render decision."""
    return item.decomposition_status in {
        DecompositionStatus.ACTIONABLE,
        DecompositionStatus.BLOCKED,
        DecompositionStatus.OUT_OF_SCOPE,
    }


def eligible_render_nodes(plan: PlanState) -> list[PlanItem]:
    """Return all structurally valid render-eligible nodes in deterministic order."""
    nodes = [item for item in plan.plan if is_render_eligible(item)]
    return sorted(nodes, key=lambda item: (item.depth, item.order, item.id))


def deterministic_skip_decision(item: PlanItem) -> RenderDecisionKind | None:
    """Return a deterministic skip decision for blocked/out-of-scope nodes."""
    if item.decomposition_status == DecompositionStatus.BLOCKED:
        return RenderDecisionKind.SKIP
    if item.decomposition_status == DecompositionStatus.OUT_OF_SCOPE:
        return RenderDecisionKind.SKIP
    return None


def deterministic_skip_reason(item: PlanItem) -> str:
    if item.decomposition_status == DecompositionStatus.BLOCKED:
        return item.blocked_reason or "Node is blocked."
    if item.decomposition_status == DecompositionStatus.OUT_OF_SCOPE:
        return item.out_of_scope_reason or "Node is out of scope."
    return ""


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


def build_render_brief(plan: PlanState, *, include_all_nodes: bool = False) -> str:
    """Build a markdown brief that defines the authoritative render scope."""
    leaves = actionable_leaf_items(plan)
    all_nodes = eligible_render_nodes(plan) if include_all_nodes else leaves
    blocked = blocked_leaf_items(plan)
    lines: list[str] = [
        "# Render brief",
        "",
        "The decomposition breakdown below is the **authoritative scope** for "
        "deliverables. The output goal defines format and schema; this brief "
        "defines which items must appear and what must be preserved.",
        "",
    ]

    if include_all_nodes:
        lines.extend(
            [
                f"## Eligible render nodes ({len(all_nodes)})",
                "",
            ]
        )
        if not all_nodes:
            lines.append("_No eligible render nodes._")
        else:
            for index, item in enumerate(all_nodes, start=1):
                skip = deterministic_skip_decision(item)
                suffix = f" [{skip.value}]" if skip else ""
                lines.append(f"{index}. **{item.title}** ({item.decomposition_status.value}){suffix}")
        lines.append("")

    lines.extend(
        [
            f"## Actionable deliverable units ({len(leaves)})",
            "",
        ]
    )

    if not leaves:
        lines.append("_No actionable leaf items._")
    else:
        for index, item in enumerate(leaves, start=1):
            lines.extend(_format_leaf_section(plan, item, index))

    if blocked:
        lines.extend(["", f"## Blocked items ({len(blocked)})", ""])
        for item in blocked:
            lines.append(f"- **{item.title}**")
            if item.blocked_reason:
                lines.append(f"  - Reason: {item.blocked_reason}")
            for question in item.open_questions:
                lines.append(f"  - Open question: {question}")

    lines.extend(["", "## Hierarchy reference", ""])
    lines.extend(_render_hierarchy(plan, parent_id=None, prefix=""))
    return "\n".join(lines).rstrip() + "\n"


def _format_leaf_section(plan: PlanState, item: PlanItem, index: int) -> list[str]:
    lines = [
        f"### {index}. {item.title}",
        f"- **Objective:** {item.objective}",
    ]
    dependencies = _dependency_labels(plan, item)
    if dependencies:
        lines.append(f"- **Dependencies:** {', '.join(dependencies)}")
    if item.expected_outputs:
        lines.append("- **Expected outputs:**")
        lines.extend(f"  - {value}" for value in item.expected_outputs)
    if item.acceptance_criteria:
        lines.append("- **Acceptance criteria:**")
        lines.extend(f"  - {value}" for value in item.acceptance_criteria)
    if item.open_questions:
        lines.append("- **Open questions:**")
        lines.extend(f"  - {value}" for value in item.open_questions)
    lines.append("")
    return lines


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
