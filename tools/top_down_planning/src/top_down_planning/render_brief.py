"""Derive render instructions and coverage checks from canonical plan state."""

from __future__ import annotations

import re
from pathlib import Path

from top_down_planning.models import DecompositionStatus, PlanItem, PlanState


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


_PUNCTUATION_TO_SPACE = re.compile(r"[,;:.!?–—\-/\\()\"'`]+")


def _normalize_for_match(text: str) -> str:
    """Normalize titles for coverage checks; ignores case and punctuation drift."""
    deduped = _PUNCTUATION_TO_SPACE.sub(" ", text.strip().lower())
    return re.sub(r"\s+", " ", deduped).strip()


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


def validate_render_coverage(
    plan: PlanState,
    artifact_paths: list[Path],
) -> list[str]:
    """Return human-readable errors when deliverables omit breakdown items."""
    errors: list[str] = []
    if not artifact_paths:
        return ["No deliverable files were written."]

    combined_parts: list[str] = []
    for path in artifact_paths:
        if not path.is_file():
            errors.append(f"Deliverable file is missing: {path}")
            continue
        try:
            combined_parts.append(path.read_text(encoding="utf-8"))
        except OSError as exc:
            errors.append(f"Cannot read deliverable {path}: {exc}")

    if errors:
        return errors

    combined_normalized = _normalize_for_match("\n".join(combined_parts))
    leaves = actionable_leaf_items(plan)
    for item in leaves:
        title_normalized = _normalize_for_match(item.title)
        if title_normalized and title_normalized not in combined_normalized:
            errors.append(
                "Deliverables do not cover breakdown item "
                f"{item.id} ({item.title!r}). "
                "Each actionable leaf in the render brief must appear in the output."
            )

    return errors
