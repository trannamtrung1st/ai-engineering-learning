"""Render batch context preparation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from top_down_planning.digest import compute_plan_digest
from top_down_planning.generation_context import build_plan_overview, ensure_plan_overview_artifact
from top_down_planning.input_loader import LoadedOutputGoal
from top_down_planning.models import (
    PlanItem,
    PlanState,
    RenderManifest,
    RenderManifestItem,
    WholePlanContextMode,
)
from top_down_planning.persistence import render_context_dir
from top_down_planning.prompts import (
    _format_item_context,
    format_embedded_markdown,
    format_input_file_reference,
    format_output_goal_section,
    should_embed_content,
)
from top_down_planning.render_manifest import save_render_manifest


@dataclass(frozen=True)
class PreparedRenderBatchContext:
    batch_context_markdown: str
    context_mode: WholePlanContextMode
    manifest_path: Path
    overview_path: Path | None
    output_goal_path: Path | None


def prepare_render_batch_context(
    *,
    plan: PlanState,
    manifest: RenderManifest,
    assigned_items: list[RenderManifestItem],
    output_dir: Path,
    workspace: Path,
    output_goal: LoadedOutputGoal,
    whole_plan_context: WholePlanContextMode,
    embed_threshold: int,
    batch_id: str,
    manifest_digest: str,
) -> PreparedRenderBatchContext:
    context_root = render_context_dir(output_dir)
    context_root.mkdir(parents=True, exist_ok=True)

    plan_digest = compute_plan_digest(plan)
    overview_path = ensure_plan_overview_artifact(
        output_dir,
        plan,
        plan_digest,
    )

    manifest_path = context_root / f"render-manifest-{manifest_digest}.yaml"
    save_render_manifest(manifest_path, manifest)

    output_goal_path: Path | None = None
    if output_goal.path is not None:
        output_goal_path = output_goal.path
    elif not should_embed_content(output_goal.text, embed_threshold=embed_threshold):
        output_goal_path = context_root / f"output-goal-{manifest.output_goal_digest}.md"
        output_goal_path.write_text(output_goal.text.strip() + "\n", encoding="utf-8")

    batch_context_path = context_root / f"{batch_id}-context.md"
    batch_markdown = _build_batch_context_markdown(
        plan=plan,
        assigned_items=assigned_items,
        manifest=manifest,
        manifest_path=manifest_path,
        overview_path=overview_path,
        output_goal=output_goal,
        output_goal_path=output_goal_path,
        workspace=workspace,
        embed_threshold=embed_threshold,
        whole_plan_context=whole_plan_context,
        batch_id=batch_id,
    )
    batch_context_path.write_text(batch_markdown, encoding="utf-8")

    return PreparedRenderBatchContext(
        batch_context_markdown=batch_markdown,
        context_mode=whole_plan_context,
        manifest_path=manifest_path,
        overview_path=overview_path,
        output_goal_path=output_goal_path,
    )


def _build_batch_context_markdown(
    *,
    plan: PlanState,
    assigned_items: list[RenderManifestItem],
    manifest: RenderManifest,
    manifest_path: Path,
    overview_path: Path | None,
    output_goal: LoadedOutputGoal,
    output_goal_path: Path | None,
    workspace: Path,
    embed_threshold: int,
    whole_plan_context: WholePlanContextMode,
    batch_id: str,
) -> str:
    lines = [
        f"# Render batch context: {batch_id}",
        "",
        "## Assigned items",
        "",
    ]
    for manifest_item in assigned_items:
        plan_item = plan.item_by_id(manifest_item.plan_item_id)
        if plan_item is not None:
            lines.append(_format_item_context(plan, plan_item))
            lines.append("")
        else:
            lines.extend(
                [
                    f"### {manifest_item.title}",
                    f"- **Artifact role:** `{manifest_item.artifact_role}`",
                    f"- **Artifact key:** `{manifest_item.artifact_key}`",
                    "",
                ]
            )

    lines.extend(
        [
            "## Artifact assignments",
            "",
        ]
    )
    for manifest_item in assigned_items:
        if manifest_item.relative_path:
            lines.append(
                f"- `{manifest_item.plan_item_id}` → "
                f"`{manifest_item.artifact_key}` → "
                f"staging `{manifest_item.relative_path}` → "
                f"set_order `{manifest_item.set_order:02d}` → "
                f"publish `{manifest_item.publish_relative_path}`"
            )
        else:
            lines.append(
                f"- `{manifest_item.plan_item_id}` → "
                f"`{manifest_item.artifact_key}` → section {manifest_item.section_order}"
            )

    if whole_plan_context in {WholePlanContextMode.REFERENCED, WholePlanContextMode.HYBRID}:
        lines.extend(["", "## Whole plan overview (read-only)", ""])
        if overview_path is not None:
            lines.append(format_input_file_reference(overview_path, workspace))
        lines.extend(["", "## Render manifest (read-only)", ""])
        lines.append(format_input_file_reference(manifest_path, workspace))

    if whole_plan_context in {WholePlanContextMode.EMBEDDED, WholePlanContextMode.HYBRID}:
        if overview_path is not None and overview_path.is_file():
            lines.extend(
                [
                    "",
                    "## Embedded plan overview",
                    "",
                    format_embedded_markdown(overview_path.read_text(encoding="utf-8")),
                ]
            )

    lines.extend(
        [
            "",
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
