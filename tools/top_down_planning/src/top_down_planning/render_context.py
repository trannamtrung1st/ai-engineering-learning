"""Cumulative context for sequential render batch sessions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from top_down_planning.digest import digest_text
from top_down_planning.errors import PlanningToolError
from top_down_planning.generation_context import build_plan_overview
from top_down_planning.input_loader import LoadedOutputGoal
from top_down_planning.models import PlanItem, PlanState, RenderBatchItem, WholePlanContextMode
from top_down_planning.item_format import format_item_context
from top_down_planning.prompts import format_input_file_reference
from top_down_planning.render_brief import build_render_brief


@dataclass(frozen=True)
class PreparedRenderContext:
    context_digest: str
    context_markdown: str
    batch_dir: Path


def prepare_scaffold_context(
    *,
    plan: PlanState,
    output_dir: Path,
    workspace: Path,
    output_goal: LoadedOutputGoal,
    plan_digest: str,
    whole_plan_context: WholePlanContextMode,
    embed_threshold: int,
) -> PreparedRenderContext:
    batch_dir = output_dir / ".planning-output" / "render" / "scaffold"
    batch_dir.mkdir(parents=True, exist_ok=True)
    markdown = _build_context_markdown(
        heading="Scaffold context",
        plan=plan,
        assigned_items=[],
        output_dir=output_dir,
        workspace=workspace,
        output_goal=output_goal,
        plan_digest=plan_digest,
        whole_plan_context=whole_plan_context,
        embed_threshold=embed_threshold,
        artifact_paths=[],
        include_full_brief=True,
    )
    return PreparedRenderContext(
        context_digest=digest_text(markdown),
        context_markdown=markdown,
        batch_dir=batch_dir,
    )


def prepare_batch_context(
    *,
    plan: PlanState,
    batch: RenderBatchItem,
    output_dir: Path,
    workspace: Path,
    output_goal: LoadedOutputGoal,
    plan_digest: str,
    whole_plan_context: WholePlanContextMode,
    embed_threshold: int,
    artifact_paths: list[str],
    revision: bool = False,
) -> PreparedRenderContext:
    batch_dir = output_dir / ".planning-output" / "render" / "batches" / f"{batch.batch_index:03d}"
    batch_dir.mkdir(parents=True, exist_ok=True)
    assigned = [plan.item_by_id(item_id) for item_id in batch.item_ids]
    missing_ids = [
        item_id for item_id, item in zip(batch.item_ids, assigned, strict=True) if item is None
    ]
    if missing_ids:
        raise PlanningToolError(
            f"Batch {batch.batch_index} references unknown plan items: "
            + ", ".join(missing_ids)
        )
    assigned_items = [item for item in assigned if item is not None]
    heading = "Render batch revision context" if revision else "Render batch author context"
    markdown = _build_context_markdown(
        heading=heading,
        plan=plan,
        assigned_items=assigned_items,
        output_dir=output_dir,
        workspace=workspace,
        output_goal=output_goal,
        plan_digest=plan_digest,
        whole_plan_context=whole_plan_context,
        embed_threshold=embed_threshold,
        artifact_paths=artifact_paths,
        batch=batch,
    )
    return PreparedRenderContext(
        context_digest=digest_text(markdown),
        context_markdown=markdown,
        batch_dir=batch_dir,
    )


def prepare_final_revision_context(
    *,
    plan: PlanState,
    output_dir: Path,
    workspace: Path,
    output_goal: LoadedOutputGoal,
    plan_digest: str,
    whole_plan_context: WholePlanContextMode,
    embed_threshold: int,
    artifact_paths: list[str],
    affected_batch_indices: list[int],
    findings_summary: str,
) -> PreparedRenderContext:
    batch_dir = output_dir / ".planning-output" / "render" / "final-revision"
    batch_dir.mkdir(parents=True, exist_ok=True)
    markdown = _build_context_markdown(
        heading="Final render revision context",
        plan=plan,
        assigned_items=[],
        output_dir=output_dir,
        workspace=workspace,
        output_goal=output_goal,
        plan_digest=plan_digest,
        whole_plan_context=whole_plan_context,
        embed_threshold=embed_threshold,
        artifact_paths=artifact_paths,
        include_full_brief=True,
        extra_sections=[
            "## Revision scope",
            f"- Affected batches: {', '.join(str(index) for index in affected_batch_indices) or 'unspecified (see findings)'}",
            "",
            "## Review findings",
            findings_summary or "_No findings summary provided._",
            "",
        ],
    )
    return PreparedRenderContext(
        context_digest=digest_text(markdown),
        context_markdown=markdown,
        batch_dir=batch_dir,
    )


def _build_context_markdown(
    *,
    heading: str,
    plan: PlanState,
    assigned_items: list[PlanItem],
    output_dir: Path,
    workspace: Path,
    output_goal: LoadedOutputGoal,
    plan_digest: str,
    whole_plan_context: WholePlanContextMode,
    embed_threshold: int,
    artifact_paths: list[str],
    batch: RenderBatchItem | None = None,
    include_full_brief: bool = False,
    extra_sections: list[str] | None = None,
) -> str:
    lines = [f"# {heading}", "", f"Plan digest: `{plan_digest}`", ""]
    if batch is not None:
        lines.extend(
            [
                f"Batch index: {batch.batch_index}",
                f"Batch title: {batch.title}",
                "",
            ]
        )
    if assigned_items:
        lines.extend(["## Assigned plan items", ""])
        for item in assigned_items:
            lines.append(format_item_context(plan, item))
            lines.append("")
    if include_full_brief or not assigned_items:
        lines.append(build_render_brief(plan))
    if whole_plan_context == WholePlanContextMode.EMBEDDED:
        lines.extend(
            [
                "",
                "## Whole-plan overview",
                build_plan_overview(plan, plan_digest, output_dir=output_dir),
                "",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "## Whole-plan overview reference",
                format_input_file_reference(
                    output_dir / ".planning-output" / "context" / f"plan-overview-{plan_digest}.md",
                    workspace,
                ),
                "",
            ]
        )
    if artifact_paths:
        lines.extend(["## Current workspace deliverables", ""])
        for relative in sorted(artifact_paths):
            lines.append(
                f"- {format_input_file_reference(workspace / relative, workspace)}"
            )
        lines.append("")
    if extra_sections:
        lines.extend(extra_sections)
    return "\n".join(lines).rstrip() + "\n"
