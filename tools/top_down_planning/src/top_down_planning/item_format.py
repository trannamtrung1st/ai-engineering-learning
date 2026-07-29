"""Shared plan-item formatting for prompts, context artifacts, and render briefs."""

from __future__ import annotations

from top_down_planning.models import DecompositionStatus, PlanItem, PlanState


def _ancestors(plan: PlanState, item: PlanItem) -> list[PlanItem]:
    chain: list[PlanItem] = []
    current = item.parent_id
    while current is not None:
        parent = plan.item_by_id(current)
        if parent is None:
            break
        chain.append(parent)
        current = parent.parent_id
    chain.reverse()
    return chain


def _siblings(plan: PlanState, item: PlanItem) -> list[PlanItem]:
    return [
        sibling
        for sibling in plan.children_of(item.parent_id)
        if sibling.id != item.id
    ]


def format_item_detail_lines(
    plan: PlanState,
    item: PlanItem,
    *,
    indent: str = "",
    bullet: str = "-",
    include_status: bool = True,
    include_depth: bool = False,
) -> list[str]:
    """Return markdown lines for one item's full planning detail."""
    parts: list[str] = []
    header = f"{indent}{bullet} [{item.id}] {item.title}"
    if include_status:
        header += f" ({item.decomposition_status.value})"
    parts.append(header)
    sub = indent + "  "
    parts.append(f"{sub}Objective: {item.objective}")
    if include_depth:
        parts.append(f"{sub}Depth: {item.depth}")
    if item.dependencies:
        parts.append(f"{sub}Dependencies: {', '.join(item.dependencies)}")
    if item.expected_outputs:
        parts.append(f"{sub}Expected outputs:")
        parts.extend(f"{sub}  - {value}" for value in item.expected_outputs)
    if item.acceptance_criteria:
        parts.append(f"{sub}Acceptance criteria:")
        parts.extend(f"{sub}  - {value}" for value in item.acceptance_criteria)
    if item.notes:
        parts.append(f"{sub}Notes:")
        parts.extend(f"{sub}  - {value}" for value in item.notes)
    if item.risks:
        parts.append(f"{sub}Risks:")
        parts.extend(f"{sub}  - {value}" for value in item.risks)
    if item.open_questions:
        parts.append(f"{sub}Open questions:")
        parts.extend(f"{sub}  - {value}" for value in item.open_questions)
    if item.blocked_reason:
        parts.append(f"{sub}Blocked: {item.blocked_reason}")
    if item.blocked_constraint_code is not None:
        parts.append(f"{sub}Blocked constraint: {item.blocked_constraint_code.value}")
    if item.blocked_required_min_children is not None:
        parts.append(
            f"{sub}Required min children: {item.blocked_required_min_children}"
        )
    if item.out_of_scope_reason:
        parts.append(f"{sub}Out of scope: {item.out_of_scope_reason}")
    return parts


def format_item_context(plan: PlanState, item: PlanItem) -> str:
    """Assigned-item context with ancestors and siblings."""
    parts = [
        f"### Selected item `{item.id}`",
        f"- Title: {item.title}",
        f"- Objective: {item.objective}",
        f"- Depth: {item.depth}",
        f"- Status: {item.decomposition_status.value}",
    ]
    if item.dependencies:
        parts.append(f"- Dependencies: {', '.join(item.dependencies)}")
    if item.expected_outputs:
        parts.append("- Expected outputs:")
        parts.extend(f"  - {value}" for value in item.expected_outputs)
    if item.acceptance_criteria:
        parts.append("- Acceptance criteria:")
        parts.extend(f"  - {value}" for value in item.acceptance_criteria)
    if item.notes:
        parts.append("- Notes:")
        parts.extend(f"  - {value}" for value in item.notes)
    if item.risks:
        parts.append("- Risks:")
        parts.extend(f"  - {value}" for value in item.risks)
    if item.open_questions:
        parts.append("- Open questions:")
        parts.extend(f"  - {value}" for value in item.open_questions)
    if item.blocked_reason:
        parts.append(f"- Blocked: {item.blocked_reason}")
    if item.blocked_constraint_code is not None:
        parts.append(f"- Blocked constraint: {item.blocked_constraint_code.value}")
    if item.blocked_required_min_children is not None:
        parts.append(
            f"- Required min children: {item.blocked_required_min_children}"
        )
    if item.out_of_scope_reason:
        parts.append(f"- Out of scope: {item.out_of_scope_reason}")

    ancestors = _ancestors(plan, item)
    if ancestors:
        parts.append("- Ancestors:")
        for ancestor in ancestors:
            parts.append(f"  - [{ancestor.id}] {ancestor.title}")

    siblings = _siblings(plan, item)
    if siblings:
        parts.append("- Direct siblings:")
        for sibling in siblings:
            parts.append(
                f"  - [{sibling.id}] {sibling.title} "
                f"({sibling.decomposition_status.value})"
            )
    return "\n".join(parts)


def format_item_summary(plan: PlanState, item: PlanItem) -> str:
    """Compact read-only item block with full detail fields."""
    lines = format_item_detail_lines(
        plan,
        item,
        bullet="-",
        include_status=True,
    )
    return "\n".join(lines)


def format_patchable_item_context(plan: PlanState, item: PlanItem) -> str:
    """Patchable related item with explicit field listing."""
    parts = [
        f"### [{item.id}] {item.title} ({item.decomposition_status.value})",
    ]
    parts.extend(
        format_item_detail_lines(
            plan,
            item,
            indent="",
            bullet="-",
            include_status=False,
        )[1:]
    )
    return "\n".join(parts)


def format_leaf_brief_section(plan: PlanState, item: PlanItem, index: int) -> list[str]:
    """Actionable leaf section for render briefs."""
    lines = [
        f"### {index}. {item.title}",
        f"- **Objective:** {item.objective}",
    ]
    if item.dependencies:
        dep_labels = []
        for dep in item.dependencies:
            dep_item = plan.item_by_id(dep)
            dep_labels.append(dep_item.title if dep_item else dep)
        lines.append(f"- **Dependencies:** {', '.join(dep_labels)}")
    if item.expected_outputs:
        lines.append("- **Expected outputs:**")
        lines.extend(f"  - {value}" for value in item.expected_outputs)
    if item.acceptance_criteria:
        lines.append("- **Acceptance criteria:**")
        lines.extend(f"  - {value}" for value in item.acceptance_criteria)
    if item.notes:
        lines.append("- **Notes:**")
        lines.extend(f"  - {value}" for value in item.notes)
    if item.risks:
        lines.append("- **Risks:**")
        lines.extend(f"  - {value}" for value in item.risks)
    if item.open_questions:
        lines.append("- **Open questions:**")
        lines.extend(f"  - {value}" for value in item.open_questions)
    lines.append("")
    return lines
