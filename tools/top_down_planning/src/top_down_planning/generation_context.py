"""Build bounded whole-plan and per-batch generation context artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from top_down_planning.models import (
    DEFAULT_CONTEXT_CHARACTERS,
    DecompositionStatus,
    PlanItem,
    PlanState,
    WholePlanReviewResult,
    WholePlanContextMode,
)
from top_down_planning.persistence import plan_overview_artifact_path, whole_plan_review_result_path
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


def _load_review_findings(output_dir: Path | None) -> WholePlanReviewResult | None:
    if output_dir is None:
        return None
    path = whole_plan_review_result_path(output_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return WholePlanReviewResult.model_validate(data)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


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
    review = _load_review_findings(output_dir)
    review_node_ids: set[str] = set()
    if review is not None:
        for finding in review.findings:
            review_node_ids.update(finding.node_ids)

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
    """Complete read-only whole-plan reference for a wave snapshot."""
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

    review = _load_review_findings(output_dir)
    if review is not None and review.findings:
        lines.extend(["## Review findings", ""])
        for finding in review.findings:
            nodes = ", ".join(finding.node_ids) if finding.node_ids else "plan-wide"
            lines.append(
                f"- [{finding.severity.value}/{finding.category.value}] "
                f"({nodes}) {finding.description}"
            )
            if finding.recommended_change:
                lines.append(f"  - Recommended: {finding.recommended_change}")
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
    context_mode: WholePlanContextMode
    plan_overview_relative: str | None
    inline_relevant_context: str
    embedded_overview: str | None


def _relative_output_path(path: Path, output_dir: Path) -> str:
    state_root = output_dir / ".planning-output"
    try:
        return str(path.resolve().relative_to(state_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.name)


def estimate_context_size(
    *,
    selected_items: list[PlanItem],
    relevant_ids: set[str],
    plan: PlanState,
    overview: str,
) -> int:
    total = len(overview)
    for item in selected_items:
        total += len(format_item_context(plan, item))
    for item_id in sorted(relevant_ids):
        item = plan.item_by_id(item_id)
        if item is not None:
            total += len(_format_item_summary(plan, item))
    return total


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
    whole_plan_context: WholePlanContextMode,
    max_context_characters: int = DEFAULT_CONTEXT_CHARACTERS,
    include_cross_item_updates: bool = True,
) -> PreparedBatchContext:
    """Prepare per-batch context and decide embedding vs reference mode."""
    overview_path = ensure_plan_overview_artifact(output_dir, plan, plan_digest)
    overview = build_plan_overview(plan, plan_digest, output_dir=output_dir)
    overview_relative = _relative_output_path(overview_path, output_dir)

    assigned_section, patchable_section, relevant_section = build_batch_context_markdown(
        plan=plan,
        selected_items=selected_items,
        plan_digest=plan_digest,
        output_dir=output_dir,
        include_cross_item_updates=include_cross_item_updates,
    )

    selected_ids = {item.id for item in selected_items}
    relevant_ids = select_relevant_node_ids(plan, selected_ids, output_dir=output_dir)
    patchable_ids = (
        select_patchable_node_ids(plan, selected_ids)
        if include_cross_item_updates
        else set()
    )
    estimated = estimate_context_size(
        selected_items=selected_items,
        relevant_ids=relevant_ids | patchable_ids,
        plan=plan,
        overview=overview,
    )

    embedded_overview: str | None = None
    if whole_plan_context == WholePlanContextMode.EMBEDDED:
        if len(overview) <= max_context_characters:
            context_mode = WholePlanContextMode.EMBEDDED
            embedded_overview = overview
        else:
            context_mode = WholePlanContextMode.REFERENCED
    elif whole_plan_context == WholePlanContextMode.REFERENCED:
        context_mode = WholePlanContextMode.REFERENCED
    elif estimated + len(overview) <= max_context_characters:
        context_mode = WholePlanContextMode.HYBRID
        embedded_overview = overview
    else:
        context_mode = WholePlanContextMode.HYBRID

    global_consistency = """
## Global consistency checks

Before recording an operation, compare the proposed decomposition with the
current whole-plan context.

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
- do not merge or omit explicit source groups to satisfy artificial limits;
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
    if embedded_overview is not None:
        parts.extend(
            [
                "## Complete plan overview (read-only)",
                "",
                embedded_overview,
            ]
        )
    elif context_mode in {WholePlanContextMode.REFERENCED, WholePlanContextMode.HYBRID}:
        parts.extend(
            [
                "## Complete plan overview (read-only)",
                "",
                f"Read the complete plan overview before recording operations: "
                f"`.planning-output/{overview_relative}`",
            ]
        )

    batch_markdown = "\n\n".join(parts).rstrip() + "\n"
    return PreparedBatchContext(
        batch_context_markdown=batch_markdown,
        context_mode=context_mode,
        plan_overview_relative=overview_relative,
        inline_relevant_context=relevant_section,
        embedded_overview=embedded_overview,
    )
