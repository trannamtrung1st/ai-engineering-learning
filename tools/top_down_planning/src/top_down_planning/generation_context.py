"""Build bounded whole-plan and per-batch generation context artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from top_down_planning.models import (
    CheckpointFinding,
    DecompositionStatus,
    PlanItem,
    PlanState,
    PlanningState,
)
from top_down_planning.persistence import load_planning_state, plan_overview_artifact_path
from top_down_planning.item_format import (
    format_item_context,
    format_item_summary,
    format_patchable_item_context,
)
from top_down_planning.render_brief import _render_hierarchy


def _ancestors(plan: PlanState, item_id: str) -> list[PlanItem]:
    chain: list[PlanItem] = []
    item = plan.item_by_id(item_id)
    if item is None:
        return chain
    current = item.parent_id
    while current is not None:
        parent = plan.item_by_id(current)
        if parent is None:
            break
        chain.append(parent)
        current = parent.parent_id
    chain.reverse()
    return chain


def _descendants(plan: PlanState, item_id: str) -> list[PlanItem]:
    result: list[PlanItem] = []
    stack = [item_id]
    while stack:
        parent = stack.pop()
        for child in plan.children_of(parent):
            result.append(child)
            stack.append(child.id)
    return result


def _siblings(plan: PlanState, item: PlanItem) -> list[PlanItem]:
    return [
        sibling
        for sibling in plan.children_of(item.parent_id)
        if sibling.id != item.id
    ]


def _reverse_dependents(plan: PlanState, item_id: str) -> list[PlanItem]:
    return [
        item
        for item in plan.plan
        if item_id in item.dependencies and item.id != item_id
    ]


def _top_level_branch_root(plan: PlanState, item: PlanItem) -> PlanItem:
    current = item
    while current.parent_id is not None:
        parent = plan.item_by_id(current.parent_id)
        if parent is None:
            break
        current = parent
    return current


def _load_planning_state(output_dir: Path | None) -> PlanningState | None:
    if output_dir is None:
        return None
    return load_planning_state(output_dir)


def _checkpoint_finding_node_ids(finding: CheckpointFinding) -> list[str]:
    return list(finding.affected_branches)


def select_patchable_node_ids(
    plan: PlanState,
    selected_ids: set[str],
) -> set[str]:
    """Directly related existing nodes that may receive cross-item updates."""
    patchable: set[str] = set()
    for item_id in sorted(selected_ids):
        item = plan.item_by_id(item_id)
        if item is None:
            continue

        for ancestor in _ancestors(plan, item_id):
            patchable.add(ancestor.id)

        for sibling in _siblings(plan, item):
            patchable.add(sibling.id)

        for dep in item.dependencies:
            patchable.add(dep)

        for dependent in _reverse_dependents(plan, item_id):
            patchable.add(dependent.id)

    patchable -= selected_ids
    return patchable


def select_relevant_node_ids(
    plan: PlanState,
    selected_ids: set[str],
    *,
    output_dir: Path | None = None,
) -> set[str]:
    """Deterministic relevant-context node selection for one batch."""
    relevant: set[str] = set()
    planning_state = _load_planning_state(output_dir)
    review_node_ids: set[str] = set()
    if planning_state is not None:
        for finding in planning_state.review_findings:
            review_node_ids.update(_checkpoint_finding_node_ids(finding))

    top_level_summaries: set[str] = set()
    for item in plan.plan:
        if item.parent_id is None:
            top_level_summaries.add(item.id)

    for item_id in sorted(selected_ids):
        item = plan.item_by_id(item_id)
        if item is None:
            continue

        for ancestor in _ancestors(plan, item_id):
            relevant.add(ancestor.id)

        for descendant in _descendants(plan, item_id):
            relevant.add(descendant.id)

        for sibling in _siblings(plan, item):
            relevant.add(sibling.id)

        for dep in item.dependencies:
            relevant.add(dep)

        for dependent in _reverse_dependents(plan, item_id):
            relevant.add(dependent.id)

        branch_root = _top_level_branch_root(plan, item)
        for peer in plan.plan:
            if _top_level_branch_root(plan, peer).id == branch_root.id:
                relevant.add(peer.id)

        relevant.update(review_node_ids & {node.id for node in plan.plan})
        relevant.update(top_level_summaries)

    relevant -= selected_ids
    return relevant


def _format_item_summary(plan: PlanState, item: PlanItem) -> str:
    return format_item_summary(plan, item)


def _format_patchable_item_context(plan: PlanState, item: PlanItem) -> str:
    return format_patchable_item_context(plan, item)


def build_plan_overview(
    plan: PlanState,
    plan_digest: str,
    *,
    output_dir: Path | None = None,
) -> str:
    """Complete read-only whole-plan reference for one planning iteration snapshot."""
    lines: list[str] = [
        "# Plan overview",
        "",
        f"Plan digest: `{plan_digest}`",
        "",
        "## Hierarchy",
        "",
    ]
    lines.extend(_render_hierarchy(plan, parent_id=None, prefix=""))
    lines.extend(["", "## Nodes", ""])

    for item in sorted(plan.plan, key=lambda entry: (entry.order, entry.id)):
        lines.append(_format_item_summary(plan, item))
        lines.append("")

    review = _load_planning_state(output_dir)
    if review is not None and review.review_findings:
        lines.extend(["## Review findings", ""])
        for finding in review.review_findings:
            nodes = ", ".join(_checkpoint_finding_node_ids(finding)) or "plan-wide"
            lines.append(
                f"- [{finding.severity.value}/{finding.category.value}] "
                f"({nodes}) {finding.observation}"
            )
            if finding.recommended_disposition:
                lines.append(f"  - Recommended: {finding.recommended_disposition}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def ensure_plan_overview_artifact(
    output_dir: Path,
    plan: PlanState,
    plan_digest: str,
) -> Path:
    """Write or reuse the shared plan-overview artifact for a digest."""
    path = plan_overview_artifact_path(output_dir, plan_digest)
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        build_plan_overview(plan, plan_digest, output_dir=output_dir),
        encoding="utf-8",
    )
    return path


@dataclass(frozen=True)
class PreparedBatchContext:
    batch_context_markdown: str
    plan_overview_relative: str
    inline_relevant_context: str


@dataclass(frozen=True)
class PreparedDispositionContext:
    context_markdown: str
    plan_overview_relative: str


def prepare_disposition_context(
    *,
    plan: PlanState,
    findings: list[CheckpointFinding],
    plan_digest: str,
    output_dir: Path,
) -> PreparedDispositionContext:
    """Build read-only context for a finding-disposition session."""
    overview_path = ensure_plan_overview_artifact(output_dir, plan, plan_digest)
    overview_relative = _relative_output_path(overview_path, output_dir)

    affected_ids: set[str] = set()
    for finding in findings:
        affected_ids.update(_checkpoint_finding_node_ids(finding))

    patchable_ids: set[str] = set()
    for item_id in affected_ids:
        patchable_ids |= select_patchable_node_ids(plan, {item_id})
    patchable_only = patchable_ids - affected_ids

    sections: list[str] = []
    if affected_ids:
        sections.append("## Affected items")
        sections.append("")
        for item_id in sorted(affected_ids):
            item = plan.item_by_id(item_id)
            if item is not None:
                sections.append(format_item_context(plan, item))
                sections.append("")

    if patchable_only:
        sections.append("## Related patchable items")
        sections.append("")
        for item_id in sorted(patchable_only):
            item = plan.item_by_id(item_id)
            if item is not None:
                sections.append(_format_patchable_item_context(plan, item))
                sections.append("")

    sections.extend(
        [
            "## Complete plan overview (read-only)",
            "",
            "Read the complete plan overview before recording updates:",
            f"`.planning-output/{overview_relative}`",
            "",
            "Open that file and use it as the authoritative whole-plan reference for "
            "this disposition session.",
        ]
    )

    return PreparedDispositionContext(
        context_markdown="\n".join(sections).rstrip() + "\n",
        plan_overview_relative=overview_relative,
    )


def _relative_output_path(path: Path, output_dir: Path) -> str:
    state_root = output_dir / ".planning-output"
    try:
        return str(path.resolve().relative_to(state_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.name)


def build_batch_context_markdown(
    *,
    plan: PlanState,
    selected_items: list[PlanItem],
    plan_digest: str,
    output_dir: Path | None = None,
    include_cross_item_updates: bool = True,
) -> tuple[str, str, str]:
    """Return (assigned scope, patchable scope, relevant read-only context)."""
    selected_ids = {item.id for item in selected_items}
    if selected_items:
        assigned_lines = [
            "## Assigned generation scope (writable)",
            "",
            "Produce exactly one operation for each assigned item below.",
            "",
        ]
        for item in selected_items:
            assigned_lines.append(format_item_context(plan, item))
            assigned_lines.append("")
    else:
        assigned_lines = [
            "## Assigned generation scope (writable)",
            "",
            "No batch selected yet. Run `select-batch` to record your chosen scope, then "
            "use `show-context` for detailed item context before recording operations.",
            "",
        ]

    patchable_ids: set[str] = set()
    patchable_lines: list[str] = []
    if include_cross_item_updates:
        patchable_ids = select_patchable_node_ids(plan, selected_ids)
        patchable_lines = [
            "## Patchable related items (cross-item updates)",
            "",
            "You may record zero or more `update_item` patches for the related items below "
            "when your assigned decomposition changes their dependencies, notes, risks, "
            "open questions, or detail. Omitted fields preserve the current value; an empty "
            "list clears a list field.",
            "",
        ]
        if not patchable_ids:
            patchable_lines.append(
                "_No related existing items are patchable in this batch._"
            )
        else:
            for item_id in sorted(patchable_ids, key=lambda node_id: (
                plan.item_by_id(node_id).order if plan.item_by_id(node_id) else 0,
                node_id,
            )):
                item = plan.item_by_id(item_id)
                if item is not None:
                    patchable_lines.append(_format_patchable_item_context(plan, item))
                    patchable_lines.append("")

    relevant_ids = select_relevant_node_ids(
        plan,
        selected_ids,
        output_dir=output_dir,
    )
    if include_cross_item_updates:
        relevant_ids -= patchable_ids
    relevant_lines = [
        "## Relevant plan context (read-only)",
        "",
    ]
    if not relevant_ids:
        relevant_lines.append("_No additional read-only context beyond assigned scope._")
    else:
        for item_id in sorted(relevant_ids, key=lambda node_id: (
            plan.item_by_id(node_id).order if plan.item_by_id(node_id) else 0,
            node_id,
        )):
            item = plan.item_by_id(item_id)
            if item is not None:
                relevant_lines.append(_format_item_summary(plan, item))
                relevant_lines.append("")

    relevant_lines.append(f"Plan digest: `{plan_digest}`")
    assigned_section = "\n".join(assigned_lines).rstrip() + "\n"
    patchable_section = (
        "\n".join(patchable_lines).rstrip() + "\n" if patchable_lines else ""
    )
    relevant_section = "\n".join(relevant_lines).rstrip() + "\n"
    return assigned_section, patchable_section, relevant_section


def prepare_batch_context(
    *,
    plan: PlanState,
    selected_items: list[PlanItem],
    plan_digest: str,
    output_dir: Path,
    include_cross_item_updates: bool = True,
) -> PreparedBatchContext:
    """Prepare per-batch context with a mandatory whole-plan overview reference."""
    overview_path = ensure_plan_overview_artifact(output_dir, plan, plan_digest)
    overview_relative = _relative_output_path(overview_path, output_dir)

    assigned_section, patchable_section, relevant_section = build_batch_context_markdown(
        plan=plan,
        selected_items=selected_items,
        plan_digest=plan_digest,
        output_dir=output_dir,
        include_cross_item_updates=include_cross_item_updates,
    )

    global_consistency = """
## Global consistency checks

Before recording an operation, compare the proposed decomposition with the
plan overview artifact.

Preserve:
- source terminology and explicit structure;
- decisions already established in other branches;
- consistent planning granularity;
- real prerequisite relationships;
- global non-goals;
- compatible acceptance and verification expectations.

Do not:
- duplicate work already owned by another branch;
- contradict established decisions;
- create dependencies merely to express preferred execution order;
- do not merge or omit explicit source groups to satisfy structural limits; group
  related work within the child cap and capture ancillary detail in item notes or
  actionable metadata instead;
- re-plan unrelated branches without using the assigned operation or a patchable
  `update_item` when related detail must change.

When a conflict cannot be resolved within your write scope, mark the assigned item
blocked or record a structured note/open question indicating the affected external
node. Use `record-update` to patch related items listed in the patchable scope when
your assigned decomposition changes their dependencies or invalidates existing detail.
""".strip()

    parts = (
        [assigned_section, patchable_section, relevant_section, global_consistency]
        if patchable_section
        else [assigned_section, relevant_section, global_consistency]
    )
    parts.extend(
        [
            "## Complete plan overview (read-only)",
            "",
            "Read the complete plan overview before recording operations:",
            f"`.planning-output/{overview_relative}`",
            "",
            "Open that file and use it as the authoritative whole-plan reference for "
            "this batch.",
        ]
    )

    batch_markdown = "\n\n".join(parts).rstrip() + "\n"
    return PreparedBatchContext(
        batch_context_markdown=batch_markdown,
        plan_overview_relative=overview_relative,
        inline_relevant_context=relevant_section,
    )
