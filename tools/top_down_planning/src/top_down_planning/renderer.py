"""Render plan.md from canonical planning state."""

from __future__ import annotations

from pathlib import Path

from top_down_planning.models import DecompositionStatus, PlanItem, PlanState


def render_plan_markdown(plan: PlanState) -> str:
    lines: list[str] = [
        "# Planning result",
        "",
        f"**Output goal:** {plan.source.output_goal}",
        "",
        f"**Status:** {plan.result.status.value}",
    ]
    if plan.result.summary:
        lines.extend(["", plan.result.summary])
    lines.extend(["", "## Hierarchical view", ""])
    lines.extend(_render_hierarchy(plan, parent_id=None, prefix=""))
    lines.extend(["", "## Actionable items", ""])
    lines.extend(_render_actionable_list(plan))
    blocked = [
        item
        for item in plan.plan
        if item.decomposition_status == DecompositionStatus.BLOCKED
    ]
    if blocked:
        lines.extend(["", "## Blocked items", ""])
        for item in blocked:
            lines.append(f"- **{item.title}** (`{item.id}`)")
            if item.blocked_reason:
                lines.append(f"  - Reason: {item.blocked_reason}")
            for question in item.open_questions:
                lines.append(f"  - Open question: {question}")
    return "\n".join(lines).rstrip() + "\n"


def write_plan_markdown(output_dir: Path, plan: PlanState) -> Path:
    path = output_dir / "plan.md"
    path.write_text(render_plan_markdown(plan), encoding="utf-8")
    return path


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
        if item.out_of_scope_reason:
            lines.append(f"   - Out of scope: {item.out_of_scope_reason}")
        child_prefix = f"{number}."
        lines.extend(_render_hierarchy(plan, parent_id=item.id, prefix=child_prefix))
    return lines


def _is_leaf(plan: PlanState, item: PlanItem) -> bool:
    return not any(child.parent_id == item.id for child in plan.plan)


def _render_actionable_list(plan: PlanState) -> list[str]:
    actionable = [
        item
        for item in plan.plan
        if item.decomposition_status == DecompositionStatus.ACTIONABLE
        and _is_leaf(plan, item)
    ]
    actionable.sort(key=lambda item: item.order)
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
    return lines
