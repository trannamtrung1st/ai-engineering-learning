"""Deterministic fallback rendering from canonical planning state."""

from __future__ import annotations

from top_down_planning.input_loader import resolve_output_goal_text
from top_down_planning.models import DecompositionStatus, PlanState
from top_down_planning.render_brief import actionable_leaf_items, blocked_leaf_items


def _format_output_goal_label(plan: PlanState) -> str:
    if plan.source.output_goal_file:
        return plan.source.output_goal_file
    text = resolve_output_goal_text(plan).strip()
    if not text:
        return plan.source.output_goal
    return text.splitlines()[0][:200]


def render_plan_markdown(plan: PlanState) -> str:
    lines: list[str] = [
        "# Planning result",
        "",
        f"**Output goal:** {_format_output_goal_label(plan)}",
        "",
        f"**Status:** {plan.result.status.value}",
    ]
    if plan.result.summary:
        lines.extend(["", plan.result.summary])
    lines.extend(["", "## Hierarchical view", ""])
    lines.extend(_render_hierarchy(plan, parent_id=None, prefix=""))
    lines.extend(["", "## Actionable items", ""])
    lines.extend(_render_actionable_list(plan))
    blocked = blocked_leaf_items(plan)
    if blocked:
        lines.extend(["", "## Blocked items", ""])
        for item in blocked:
            lines.append(f"- **{item.title}** (`{item.id}`)")
            if item.blocked_reason:
                lines.append(f"  - Reason: {item.blocked_reason}")
            for question in item.open_questions:
                lines.append(f"  - Open question: {question}")
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
        lines.append(f"{number}. **{item.title}** (`{item.id}`, {status})")
        lines.append(f"   - Objective: {item.objective}")
        if item.expected_outputs:
            lines.append("   - Expected outputs:")
            lines.extend(f"     - {value}" for value in item.expected_outputs)
        if item.acceptance_criteria:
            lines.append("   - Acceptance criteria:")
            lines.extend(f"     - {value}" for value in item.acceptance_criteria)
        if item.dependencies:
            lines.append(f"   - Dependencies: {', '.join(item.dependencies)}")
        if item.notes:
            lines.append("   - Notes:")
            lines.extend(f"     - {value}" for value in item.notes)
        if item.risks:
            lines.append("   - Risks:")
            lines.extend(f"     - {value}" for value in item.risks)
        if item.out_of_scope_reason:
            lines.append(f"   - Out of scope: {item.out_of_scope_reason}")
        child_prefix = f"{number}."
        lines.extend(_render_hierarchy(plan, parent_id=item.id, prefix=child_prefix))
    return lines


def _render_actionable_list(plan: PlanState) -> list[str]:
    actionable = actionable_leaf_items(plan)
    if not actionable:
        return ["- No actionable leaf items."]
    lines: list[str] = []
    for index, item in enumerate(actionable, start=1):
        lines.append(f"{index}. **{item.title}** (`{item.id}`)")
        lines.append(f"   - Objective: {item.objective}")
        if item.dependencies:
            dep_titles = []
            for dep in item.dependencies:
                dep_item = plan.item_by_id(dep)
                label = dep_item.title if dep_item else dep
                dep_titles.append(label)
            lines.append(f"   - Dependencies: {', '.join(dep_titles)}")
        if item.expected_outputs:
            lines.append("   - Expected outputs:")
            lines.extend(f"     - {value}" for value in item.expected_outputs)
        if item.acceptance_criteria:
            lines.append("   - Acceptance criteria:")
            lines.extend(f"     - {value}" for value in item.acceptance_criteria)
        if item.notes:
            lines.append("   - Notes:")
            lines.extend(f"     - {value}" for value in item.notes)
        if item.risks:
            lines.append("   - Risks:")
            lines.extend(f"     - {value}" for value in item.risks)
    return lines
