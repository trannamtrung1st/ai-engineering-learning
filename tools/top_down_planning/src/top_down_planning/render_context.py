"""Per-node render context preparation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from top_down_planning.generation_context import ensure_plan_overview_artifact
from top_down_planning.input_loader import LoadedOutputGoal
from top_down_planning.models import (
    PlanItem,
    PlanState,
    RenderContextSnapshot,
    RenderNodePhase,
    WholePlanContextMode,
)
from top_down_planning.persistence import render_context_dir, render_transaction_staging_dir
from top_down_planning.prompts import (
    _ancestors,
    format_input_file_reference,
    format_output_goal_section,
)


@dataclass(frozen=True)
class PreparedRenderNodeContext:
    node_context_markdown: str
    context_snapshot: RenderContextSnapshot
    context_path: Path
    staging_dir: Path
    overview_path: Path | None = None


def prepare_render_node_context(
    *,
    plan: PlanState,
    node_id: str,
    output_dir: Path,
    workspace: Path,
    output_goal: LoadedOutputGoal,
    whole_plan_context: WholePlanContextMode,
    embed_threshold: int,
    plan_digest: str,
    ancestor_decision_ids: list[str] | None = None,
    owned_artifact_paths: list[str] | None = None,
) -> PreparedRenderNodeContext:
    from top_down_planning.digest import digest_text

    plan_item = plan.item_by_id(node_id)
    if plan_item is None:
        raise ValueError(f"unknown node id: {node_id}")

    context_root = render_context_dir(output_dir)
    context_root.mkdir(parents=True, exist_ok=True)
    overview_path = ensure_plan_overview_artifact(output_dir, plan, plan_digest)

    transaction_id = f"txn-{node_id}-render"
    staging_dir = render_transaction_staging_dir(output_dir, transaction_id)
    staging_dir.mkdir(parents=True, exist_ok=True)

    ancestor_ids = ancestor_decision_ids or []
    owned_paths = owned_artifact_paths or []
    snapshot_payload = {
        "plan_digest": plan_digest,
        "node_id": node_id,
        "phase": RenderNodePhase.RENDER.value,
        "ancestor_decision_ids": sorted(ancestor_ids),
        "owned_artifact_paths": sorted(owned_paths),
    }
    context_digest = digest_text(
        json.dumps(snapshot_payload, sort_keys=True, separators=(",", ":"))
    )
    snapshot = RenderContextSnapshot(
        context_digest=context_digest,
        read_set_digest=context_digest,
        plan_digest=plan_digest,
        node_id=node_id,
        ancestor_decision_ids=sorted(ancestor_ids),
        owned_artifact_paths=owned_paths,
    )

    context_path = context_root / f"{node_id}-context.md"
    markdown = _build_node_context_markdown(
        plan=plan,
        plan_item=plan_item,
        snapshot=snapshot,
        overview_path=overview_path,
        output_goal=output_goal,
        workspace=workspace,
        embed_threshold=embed_threshold,
        whole_plan_context=whole_plan_context,
        staging_dir=staging_dir,
        owned_artifact_paths=owned_paths,
    )
    context_path.write_text(markdown, encoding="utf-8")

    return PreparedRenderNodeContext(
        node_context_markdown=markdown,
        context_snapshot=snapshot,
        context_path=context_path,
        staging_dir=staging_dir,
        overview_path=overview_path,
    )


def _build_node_context_markdown(
    *,
    plan: PlanState,
    plan_item: PlanItem,
    snapshot: RenderContextSnapshot,
    overview_path: Path | None,
    output_goal: LoadedOutputGoal,
    workspace: Path,
    embed_threshold: int,
    whole_plan_context: WholePlanContextMode,
    staging_dir: Path,
    owned_artifact_paths: list[str],
) -> str:
    lines = [
        f"# Render node context: {plan_item.id}",
        "",
        f"- Context digest: `{snapshot.context_digest}`",
        f"- Private staging: `{staging_dir}`",
        "",
        "## Current node",
        "",
        f"- Title: {plan_item.title}",
        f"- Objective: {plan_item.objective}",
        f"- Depth: {plan_item.depth}",
        f"- Status: {plan_item.decomposition_status.value}",
        "",
    ]
    ancestors = _ancestors(plan, plan_item)
    if ancestors:
        lines.extend(["## Ancestors", ""])
        for ancestor in ancestors:
            lines.append(f"- [{ancestor.id}] {ancestor.title}")
        lines.append("")

    if owned_artifact_paths:
        lines.extend(["## Owned artifacts", ""])
        for path in owned_artifact_paths:
            lines.append(f"- `{path}`")
        lines.append("")

    if whole_plan_context in {WholePlanContextMode.REFERENCED, WholePlanContextMode.HYBRID}:
        if overview_path is not None:
            lines.extend(["## Whole plan overview (read-only)", ""])
            lines.append(format_input_file_reference(overview_path, workspace))

    lines.extend(
        [
            "## Output goal",
            "",
            format_output_goal_section(
                output_goal=output_goal,
                workspace=workspace,
                embed_threshold=embed_threshold,
            ),
        ]
    )
    return "\n".join(lines).rstrip() + "\n"
