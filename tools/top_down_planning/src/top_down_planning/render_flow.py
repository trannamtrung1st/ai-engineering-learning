"""Sequential cumulative render pipeline."""

from __future__ import annotations

import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from top_down_planning.console_renderer import ConsoleRenderer
from top_down_planning.cursor_client import CursorClient
from top_down_planning.completeness import structural_errors
from top_down_planning.digest import compute_plan_digest, compute_render_config_digest
from top_down_planning.errors import CursorSessionError, PlanningToolError, UserInterrupted
from top_down_planning.input_loader import LoadedInput, LoadedOutputGoal
from top_down_planning.models import (
    DecompositionStatus,
    DeliverableStatus,
    PlanState,
    ProcessedBatchRecord,
    RenderBatchItem,
    RenderBatchReviewDecision,
    RenderBatchStatus,
    RenderConfig,
    RenderOutputReviewDecision,
    RenderOutputReviewStatus,
    RenderStage,
    RenderState,
    RunState,
)
from top_down_planning.persistence import (
    load_render_state,
    save_render_state,
    save_run_state,
)
from top_down_planning.prompts import (
    build_render_batch_author_prompt,
    build_render_batch_revision_prompt,
    build_render_final_revision_prompt,
    build_render_scaffold_prompt,
)
from top_down_planning.render_batch_review import RenderBatchReviewDeps, run_render_batch_review
from top_down_planning.render_batches import (
    processed_batch_indices,
    processed_batches_digest,
    validate_render_batch_selection,
)
from top_down_planning.render_context import (
    prepare_batch_context,
    prepare_final_revision_context,
    prepare_scaffold_context,
)
from top_down_planning.render_deliverables import (
    ArtifactIgnoreMatcher,
    build_artifact_ignore_matcher,
    canonical_state_prefix,
    collect_deliverable_output,
    diff_workspace_snapshots,
    filter_deliverable_candidates,
    is_utf8_text_file,
    snapshot_workspace_files,
)
from top_down_planning.render_brief import actionable_leaf_items
from top_down_planning.render_tool import build_session_env as build_render_tool_env, load_batch_manifest
from top_down_planning.render_review import (
    RenderReviewDeps,
    review_status_from_decision,
    run_render_output_review,
)
from top_down_planning.stream_events import StreamEmitter


@dataclass
class RenderFlowDeps:
    workspace_root: Path
    output_dir: Path
    loaded: LoadedInput | None
    output_goal: LoadedOutputGoal
    embed_threshold: int
    render: RenderConfig
    client: CursorClient
    renderer: ConsoleRenderer
    stream: StreamEmitter
    audit: bool
    resolve_render_context: callable
    resolve_render_model: callable
    resolve_review_context: callable
    resolve_review_model: callable
    session_timeout_seconds: int


@dataclass(frozen=True)
class RenderFlowResult:
    artifacts: list[str]


async def render_from_confirmed_plan(
    deps: RenderFlowDeps,
    *,
    plan: PlanState,
    run_state: RunState,
    force_rerender: bool = False,
    render_only: bool = False,
) -> RenderFlowResult:
    del render_only

    render_config = deps.render
    plan_digest = compute_plan_digest(plan)
    render_config_digest = compute_render_config_digest(render_config)

    _validate_render_preconditions(plan)

    render_state = load_render_state(deps.output_dir) or RenderState()
    matcher = _artifact_ignore_matcher(deps)
    if render_state.artifact_paths:
        render_state.artifact_paths = _existing_artifact_paths(
            deps.workspace_root,
            render_state.artifact_paths,
            matcher,
        )
        if not render_state.artifact_paths and render_state.stage == RenderStage.COMPLETE:
            force_rerender = True
    reset_state = _should_reset_render_state(
        render_state,
        plan_digest=plan_digest,
        output_goal_digest=deps.output_goal.digest,
        render_config_digest=render_config_digest,
        force_rerender=force_rerender,
    )

    if reset_state:
        _reset_render_state(deps.output_dir)
        render_state = RenderState()
        run_id = f"render-run-{uuid.uuid4().hex[:8]}"
    else:
        run_id = render_state.run_id or f"render-run-{uuid.uuid4().hex[:8]}"

    if not actionable_leaf_items(plan):
        raise PlanningToolError(
            "Render cannot proceed: no actionable leaf items to author."
        )

    batches_digest = processed_batches_digest(render_state.processed_batches)
    render_state.run_id = run_id
    render_state.plan_digest = plan_digest
    render_state.output_goal_digest = deps.output_goal.digest
    render_state.render_config_digest = render_config_digest
    save_render_state(deps.output_dir, render_state)

    if not force_rerender and render_state.stage == RenderStage.COMPLETE:
        existing = existing_deliverable_artifacts(
            deps.workspace_root,
            run_state,
            render_state,
            output_dir=deps.output_dir,
            artifact_ignore_patterns=deps.render.artifact_ignore_patterns,
        )
        if existing is not None:
            return RenderFlowResult(artifacts=existing)

    artifact_paths = _existing_artifact_paths(
        deps.workspace_root,
        render_state.artifact_paths,
        matcher,
    )

    if render_config.scaffold and not render_state.scaffold_complete:
        render_state.stage = RenderStage.SCAFFOLD
        save_render_state(deps.output_dir, render_state)
        deps.stream.emit("render.scaffold.started")
        artifact_paths = await _run_scaffold_session(
            deps,
            plan=plan,
            plan_digest=plan_digest,
            artifact_paths=artifact_paths,
            run_state=run_state,
        )
        render_state.scaffold_complete = True
        render_state.artifact_paths = artifact_paths
        render_state.stage = RenderStage.BATCHES
        save_render_state(deps.output_dir, render_state)
        deps.stream.emit("render.scaffold.completed", artifacts=artifact_paths)
    elif not render_state.scaffold_complete:
        render_state.scaffold_complete = True
        render_state.stage = RenderStage.BATCHES
        save_render_state(deps.output_dir, render_state)

    render_state.stage = RenderStage.BATCHES
    save_render_state(deps.output_dir, render_state)

    while True:
        eligible = _uncovered_actionable_leaves(plan, render_state)
        if not eligible:
            break

        batch_index = render_state.current_batch_index
        batch = RenderBatchItem(
            batch_index=batch_index,
            item_ids=[],
            title=f"batch-{batch_index:03d}",
        )
        covered_ids = {
            item_id
            for record in render_state.processed_batches
            for item_id in record.selected_items
        }
        eligible_ids = {item.id for item in eligible}
        deps.stream.emit(
            "render.batch.started",
            batch_index=batch.batch_index,
            eligible_items=[item.id for item in eligible],
        )
        artifact_paths = await _run_batch_pipeline(
            deps,
            plan=plan,
            plan_digest=plan_digest,
            processed_batches_digest=batches_digest,
            batch=batch,
            eligible_items=eligible,
            eligible_ids=eligible_ids,
            covered_ids=covered_ids,
            processed_batches=render_state.processed_batches,
            artifact_paths=artifact_paths,
            run_state=run_state,
            render_state=render_state,
        )
        render_state.processed_batches.append(
            ProcessedBatchRecord(
                iteration=batch_index + 1,
                selected_items=list(batch.item_ids),
                purpose=batch.purpose,
                plan_digest_before=plan_digest,
                plan_digest_after=plan_digest,
                result="completed",
            )
        )
        render_state.current_batch_index = batch_index + 1
        render_state.artifact_paths = artifact_paths
        batches_digest = processed_batches_digest(render_state.processed_batches)
        save_render_state(deps.output_dir, render_state)
        deps.stream.emit(
            "render.batch.completed",
            batch_index=batch.batch_index,
            selected_items=batch.item_ids,
            artifacts=artifact_paths,
        )

    if not artifact_paths:
        raise PlanningToolError("Render completed without workspace deliverables")

    artifact_paths = _existing_artifact_paths(deps.workspace_root, artifact_paths, matcher)
    deliverable = collect_deliverable_output(deps.workspace_root, artifact_paths, matcher)
    render_state.deliverable_output_digest = deliverable.digest
    render_state.stage = RenderStage.FINAL_REVIEW
    save_render_state(deps.output_dir, render_state)

    if not render_config.final_review:
        render_state.output_review_status = RenderOutputReviewStatus.SKIPPED
    else:
        while True:
            deps.stream.emit(
                "render.final_review.started",
                cycle=render_state.final_revision_cycle,
            )
            artifact_paths = _existing_artifact_paths(
                deps.workspace_root,
                artifact_paths,
                matcher,
            )
            deliverable = collect_deliverable_output(
                deps.workspace_root,
                artifact_paths,
                matcher,
            )
            review_result = await run_render_output_review(
                RenderReviewDeps(
                    workspace_root=deps.workspace_root,
                    output_dir=deps.output_dir,
                    output_goal=deps.output_goal,
                    embed_threshold=deps.embed_threshold,
                    client=deps.client,
                    renderer=deps.renderer,
                    audit=deps.audit,
                    resolve_review_context=deps.resolve_review_context,
                    resolve_review_model=deps.resolve_review_model,
                    session_timeout_seconds=deps.session_timeout_seconds,
                ),
                plan=plan,
                plan_digest=plan_digest,
                output_goal_digest=deps.output_goal.digest,
                processed_batches_digest=batches_digest,
                processed_batch_indices=processed_batch_indices(
                    render_state.processed_batches
                ),
                deliverable=deliverable,
                max_retries=render_config.max_retries,
            )
            if review_result is None:
                render_state.output_review_status = RenderOutputReviewStatus.BLOCKED
                save_render_state(deps.output_dir, render_state)
                raise PlanningToolError(
                    "Rendered output review blocked: reviewer did not finalize a result."
                )

            render_state.output_review_status = review_status_from_decision(
                review_result.decision
            )
            deps.stream.emit(
                "render.final_review.completed",
                decision=review_result.decision.value,
                summary=review_result.summary,
                cycle=render_state.final_revision_cycle,
            )
            if review_result.decision == RenderOutputReviewDecision.BLOCKED:
                save_render_state(deps.output_dir, render_state)
                raise PlanningToolError(
                    f"Rendered output review blocked: {review_result.summary or 'no summary'}"
                )
            if review_result.decision == RenderOutputReviewDecision.APPROVE:
                break

            render_state.final_revision_cycle += 1
            if render_state.final_revision_cycle > render_config.max_final_revision_cycles:
                save_render_state(deps.output_dir, render_state)
                raise PlanningToolError(
                    "Rendered output review exceeded max_final_revision_cycles "
                    f"({render_config.max_final_revision_cycles})"
                )

            deps.stream.emit(
                "render.final_revision.started",
                cycle=render_state.final_revision_cycle,
                batch_indices=review_result.affected_batch_indices,
            )
            artifact_paths = await _run_final_revision_session(
                deps,
                plan=plan,
                plan_digest=plan_digest,
                artifact_paths=artifact_paths,
                affected_batch_indices=review_result.affected_batch_indices,
                findings_summary=_format_findings_summary(review_result.findings),
                run_state=run_state,
            )
            render_state.artifact_paths = artifact_paths
            save_render_state(deps.output_dir, render_state)
            deps.stream.emit(
                "render.final_revision.completed",
                cycle=render_state.final_revision_cycle,
                artifacts=artifact_paths,
            )

    render_state.stage = RenderStage.COMPLETE
    render_state.deliverable_status = DeliverableStatus.COMPLETE
    save_render_state(deps.output_dir, render_state)
    paths = _persist_render_result(deps, run_state, artifact_paths)
    deps.stream.emit("render.completed", artifacts=paths)
    return RenderFlowResult(artifacts=paths)


async def _run_batch_pipeline(
    deps: RenderFlowDeps,
    *,
    plan: PlanState,
    plan_digest: str,
    processed_batches_digest: str,
    batch: RenderBatchItem,
    eligible_items: list,
    eligible_ids: set[str],
    covered_ids: set[str],
    processed_batches: list[ProcessedBatchRecord],
    artifact_paths: list[str],
    run_state: RunState,
    render_state: RenderState,
) -> list[str]:
    revision_cycle = 0
    matcher = _artifact_ignore_matcher(deps)
    while True:
        batch.status = RenderBatchStatus.AUTHORING
        artifact_paths = await _run_batch_author_session(
            deps,
            plan=plan,
            plan_digest=plan_digest,
            batch=batch,
            eligible_items=eligible_items,
            eligible_ids=eligible_ids,
            covered_ids=covered_ids,
            processed_batches=processed_batches,
            artifact_paths=artifact_paths,
            revision=False,
            run_state=run_state,
        )

        batch.status = RenderBatchStatus.REVIEWING
        artifact_paths = _existing_artifact_paths(
            deps.workspace_root,
            artifact_paths,
            matcher,
        )
        deliverable = collect_deliverable_output(
            deps.workspace_root,
            artifact_paths,
            matcher,
        )
        deps.stream.emit(
            "render.batch.review.started",
            batch_index=batch.batch_index,
            cycle=revision_cycle,
        )
        review_result = await run_render_batch_review(
            RenderBatchReviewDeps(
                workspace_root=deps.workspace_root,
                output_dir=deps.output_dir,
                output_goal=deps.output_goal,
                embed_threshold=deps.embed_threshold,
                client=deps.client,
                renderer=deps.renderer,
                audit=deps.audit,
                resolve_review_context=deps.resolve_review_context,
                resolve_review_model=deps.resolve_review_model,
                session_timeout_seconds=deps.session_timeout_seconds,
            ),
            plan=plan,
            batch=batch,
            plan_digest=plan_digest,
            processed_batches_digest=processed_batches_digest,
            deliverable=deliverable,
            max_retries=deps.render.max_retries,
        )
        if review_result is None:
            batch.status = RenderBatchStatus.BLOCKED
            raise PlanningToolError(
                f"Batch {batch.batch_index} review blocked: reviewer did not finalize a result."
            )

        deps.stream.emit(
            "render.batch.review.completed",
            batch_index=batch.batch_index,
            decision=review_result.decision.value,
            cycle=revision_cycle,
        )
        if review_result.decision == RenderBatchReviewDecision.APPROVE:
            batch.revision_cycle = revision_cycle
            return artifact_paths
        if review_result.decision == RenderBatchReviewDecision.BLOCKED:
            batch.status = RenderBatchStatus.BLOCKED
            raise PlanningToolError(
                f"Batch {batch.batch_index} review blocked: {review_result.summary}"
            )

        revision_cycle += 1
        if revision_cycle > deps.render.max_batch_revision_cycles:
            batch.status = RenderBatchStatus.BLOCKED
            raise PlanningToolError(
                f"Batch {batch.batch_index} exceeded max_batch_revision_cycles "
                f"({deps.render.max_batch_revision_cycles})"
            )

        batch.status = RenderBatchStatus.REVISING
        batch.revision_cycle = revision_cycle
        deps.stream.emit(
            "render.batch.revision.started",
            batch_index=batch.batch_index,
            cycle=revision_cycle,
        )
        artifact_paths = await _run_batch_author_session(
            deps,
            plan=plan,
            plan_digest=plan_digest,
            batch=batch,
            eligible_items=eligible_items,
            eligible_ids=eligible_ids,
            covered_ids=covered_ids,
            processed_batches=processed_batches,
            artifact_paths=artifact_paths,
            revision=True,
            run_state=run_state,
            findings_summary=_format_batch_findings_summary(review_result.findings),
        )
        deps.stream.emit(
            "render.batch.revision.completed",
            batch_index=batch.batch_index,
            cycle=revision_cycle,
        )


async def _run_scaffold_session(
    deps: RenderFlowDeps,
    *,
    plan: PlanState,
    plan_digest: str,
    artifact_paths: list[str],
    run_state: RunState,
) -> list[str]:
    prepared = prepare_scaffold_context(
        plan=plan,
        output_dir=deps.output_dir,
        workspace=deps.workspace_root,
        output_goal=deps.output_goal,
        plan_digest=plan_digest,
        embed_threshold=deps.embed_threshold,
    )
    def build_prompt(validation_feedback: list[str] | None) -> str:
        return build_render_scaffold_prompt(
            plan_digest=plan_digest,
            output_goal_digest=deps.output_goal.digest,
            render_config_digest=compute_render_config_digest(deps.render),
            context_markdown=prepared.context_markdown,
            output_goal=deps.output_goal,
            workspace=deps.workspace_root,
            embed_threshold=deps.embed_threshold,
            agent_context=deps.resolve_render_context(),
            validation_feedback=validation_feedback,
        )

    return await _run_author_session(
        deps,
        build_prompt=build_prompt,
        session_dir=prepared.batch_dir,
        artifact_paths=artifact_paths,
        run_state=run_state,
        session_label="scaffold",
    )


async def _run_batch_author_session(
    deps: RenderFlowDeps,
    *,
    plan: PlanState,
    plan_digest: str,
    batch: RenderBatchItem,
    eligible_items: list | None = None,
    eligible_ids: set[str] | None = None,
    covered_ids: set[str] | None = None,
    processed_batches: list[ProcessedBatchRecord] | None = None,
    artifact_paths: list[str],
    revision: bool,
    run_state: RunState,
    findings_summary: str = "",
) -> list[str]:
    batch_dir = deps.output_dir / ".planning-output" / "render" / "batches" / f"{batch.batch_index:03d}"
    batch_dir.mkdir(parents=True, exist_ok=True)
    batch_manifest = batch_dir / "batch-manifest.json"
    validation_feedback: list[str] | None = None

    for attempt in range(1, deps.render.max_retries + 1):
        if not revision and batch_manifest.is_file():
            batch_manifest.unlink()

        prepared = prepare_batch_context(
            plan=plan,
            batch=batch,
            output_dir=deps.output_dir,
            workspace=deps.workspace_root,
            output_goal=deps.output_goal,
            plan_digest=plan_digest,
            embed_threshold=deps.embed_threshold,
            artifact_paths=artifact_paths,
            revision=revision,
        )
        inventory = ""
        if eligible_items is not None:
            from top_down_planning.prompts import (
                format_eligible_items_section,
                format_processed_batches_section,
            )

            inventory = (
                "## Eligible render items\n"
                f"{format_eligible_items_section(eligible_items)}\n\n"
                "## Processed render batches\n"
                f"{format_processed_batches_section(processed_batches or [])}\n\n"
                "Record your batch with `planning-render-tool select-batch --node-id <id>` "
                "before authoring deliverables.\n\n"
            )
        context_markdown = inventory + prepared.context_markdown
        if revision:
            def build_prompt(feedback: list[str] | None) -> str:
                return build_render_batch_revision_prompt(
                    batch_index=batch.batch_index,
                    plan_digest=plan_digest,
                    output_goal_digest=deps.output_goal.digest,
                    render_config_digest=compute_render_config_digest(deps.render),
                    context_markdown=context_markdown,
                    output_goal=deps.output_goal,
                    workspace=deps.workspace_root,
                    embed_threshold=deps.embed_threshold,
                    findings_summary=findings_summary,
                    agent_context=deps.resolve_render_context(),
                    validation_feedback=feedback,
                )
        else:
            def build_prompt(feedback: list[str] | None) -> str:
                return build_render_batch_author_prompt(
                    batch_index=batch.batch_index,
                    plan_digest=plan_digest,
                    output_goal_digest=deps.output_goal.digest,
                    render_config_digest=compute_render_config_digest(deps.render),
                    context_markdown=context_markdown,
                    output_goal=deps.output_goal,
                    workspace=deps.workspace_root,
                    embed_threshold=deps.embed_threshold,
                    agent_context=deps.resolve_render_context(),
                    validation_feedback=feedback,
                )

        render_eligible_ids = (
            [item.id for item in eligible_items]
            if eligible_items is not None
            else list(batch.item_ids)
        )
        extra_env = build_render_tool_env(
            batch_file=batch_manifest,
            eligible_ids=render_eligible_ids,
        )
        try:
            result_paths = await _run_author_session(
                deps,
                build_prompt=build_prompt,
                session_dir=prepared.batch_dir,
                artifact_paths=artifact_paths,
                run_state=run_state,
                session_label=f"batch-{batch.batch_index:03d}",
                extra_env=extra_env,
                validation_feedback=validation_feedback,
            )
        except CursorSessionError:
            if attempt >= deps.render.max_retries:
                raise
            continue

        if revision:
            return result_paths

        if not batch_manifest.is_file():
            validation_feedback = [
                "Missing render batch selection; run planning-render-tool select-batch "
                "before authoring deliverables."
            ]
            if attempt >= deps.render.max_retries:
                raise PlanningToolError("; ".join(validation_feedback))
            continue

        manifest = load_batch_manifest(batch_manifest)
        selected_raw = manifest.get("selected_items")
        selected_ids = (
            [str(item_id) for item_id in selected_raw]
            if isinstance(selected_raw, list)
            else []
        )
        selection_errors = validate_render_batch_selection(
            plan,
            selected_ids=selected_ids,
            eligible_ids=eligible_ids or set(),
            covered_ids=covered_ids or set(),
        )
        if selection_errors:
            validation_feedback = selection_errors
            if attempt >= deps.render.max_retries:
                raise PlanningToolError("; ".join(selection_errors))
            continue

        batch.item_ids = selected_ids
        purpose = manifest.get("purpose")
        if isinstance(purpose, str):
            batch.purpose = purpose.strip()
        return result_paths

    raise PlanningToolError(
        f"Render batch {batch.batch_index} authoring failed after "
        f"{deps.render.max_retries} attempts"
    )


async def _run_final_revision_session(
    deps: RenderFlowDeps,
    *,
    plan: PlanState,
    plan_digest: str,
    artifact_paths: list[str],
    affected_batch_indices: list[int],
    findings_summary: str,
    run_state: RunState,
) -> list[str]:
    prepared = prepare_final_revision_context(
        plan=plan,
        output_dir=deps.output_dir,
        workspace=deps.workspace_root,
        output_goal=deps.output_goal,
        plan_digest=plan_digest,
        embed_threshold=deps.embed_threshold,
        artifact_paths=artifact_paths,
        affected_batch_indices=affected_batch_indices,
        findings_summary=findings_summary,
    )
    def build_prompt(validation_feedback: list[str] | None) -> str:
        return build_render_final_revision_prompt(
            plan_digest=plan_digest,
            output_goal_digest=deps.output_goal.digest,
            render_config_digest=compute_render_config_digest(deps.render),
            context_markdown=prepared.context_markdown,
            output_goal=deps.output_goal,
            workspace=deps.workspace_root,
            embed_threshold=deps.embed_threshold,
            findings_summary=findings_summary,
            agent_context=deps.resolve_render_context(),
            validation_feedback=validation_feedback,
        )

    return await _run_author_session(
        deps,
        build_prompt=build_prompt,
        session_dir=prepared.batch_dir,
        artifact_paths=artifact_paths,
        run_state=run_state,
        session_label="final-revision",
    )


async def _run_author_session(
    deps: RenderFlowDeps,
    *,
    build_prompt: Callable[[list[str] | None], str],
    session_dir: Path,
    artifact_paths: list[str],
    run_state: RunState,
    session_label: str,
    extra_env: dict[str, str] | None = None,
    validation_feedback: list[str] | None = None,
) -> list[str]:
    matcher = _artifact_ignore_matcher(deps)
    before = snapshot_workspace_files(deps.workspace_root, matcher)
    feedback = validation_feedback

    for attempt in range(1, deps.render.max_retries + 1):
        prompt = build_prompt(feedback)
        prompt_path = session_dir / f"{session_label}-request-{attempt:03d}-prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        try:
            def on_started(pid: int) -> None:
                if pid not in run_state.agent_pids:
                    run_state.agent_pids.append(pid)
                save_run_state(deps.output_dir, run_state)

            await deps.client.run_session(
                workspace=deps.workspace_root,
                prompt=prompt,
                prompt_path=prompt_path,
                timeout_seconds=deps.session_timeout_seconds,
                events_path=session_dir / f"{session_label}-agent-{attempt:03d}.ndjson"
                if deps.audit
                else None,
                log_path=session_dir / f"{session_label}-agent-{attempt:03d}.log"
                if deps.audit
                else None,
                renderer=deps.renderer,
                session_mode="agent",
                model=deps.resolve_render_model(),
                on_agent_started=on_started,
                extra_env=extra_env,
            )
        except UserInterrupted:
            run_state.agent_pids = []
            raise
        except CursorSessionError as exc:
            if attempt >= deps.render.max_retries:
                raise
            feedback = [str(exc)]
            continue

        after = snapshot_workspace_files(deps.workspace_root, matcher)
        changed = diff_workspace_snapshots(before, after)
        if not changed and not artifact_paths:
            feedback = ["session did not create or update workspace deliverables"]
            if attempt >= deps.render.max_retries:
                raise CursorSessionError(
                    f"Render session {session_label} produced no workspace deliverables"
                )
            continue

        merged = _existing_artifact_paths(
            deps.workspace_root,
            sorted(set(artifact_paths) | set(changed)),
            matcher,
        )
        if not merged:
            feedback = [
                "session did not create or update tracked workspace deliverables"
            ]
            if attempt >= deps.render.max_retries:
                raise CursorSessionError(
                    f"Render session {session_label} produced no workspace deliverables"
                )
            continue
        return merged

    raise CursorSessionError(
        f"Render session {session_label} failed after {deps.render.max_retries} attempts"
    )


def _validate_render_preconditions(plan: PlanState) -> None:
    needs_expansion = [
        item.id
        for item in plan.plan
        if item.decomposition_status == DecompositionStatus.NEEDS_EXPANSION
    ]
    if needs_expansion:
        raise PlanningToolError(
            "Render cannot proceed: plan items remain in needs_expansion: "
            + ", ".join(needs_expansion)
        )
    struct_errors = structural_errors(plan)
    if struct_errors:
        raise PlanningToolError(
            "Render cannot proceed: invalid structural plan state: "
            + "; ".join(struct_errors)
        )


def _should_reset_render_state(
    render_state: RenderState | None,
    *,
    plan_digest: str,
    output_goal_digest: str,
    render_config_digest: str,
    force_rerender: bool,
) -> bool:
    if force_rerender:
        return True
    if render_state is None:
        return True
    if (
        render_state.plan_digest != plan_digest
        or render_state.output_goal_digest != output_goal_digest
        or render_state.render_config_digest != render_config_digest
    ):
        return True
    return False


def _uncovered_actionable_leaves(plan: PlanState, render_state: RenderState):
    covered = {
        item_id
        for record in render_state.processed_batches
        for item_id in record.selected_items
    }
    return [item for item in actionable_leaf_items(plan) if item.id not in covered]


def _artifact_ignore_matcher(deps: RenderFlowDeps) -> ArtifactIgnoreMatcher:
    if canonical_state_prefix(deps.workspace_root, deps.output_dir) is None:
        raise PlanningToolError(
            "Render cannot proceed: the run output directory must lie inside the "
            "workspace so canonical planning state can be excluded from artifact "
            "discovery."
        )
    return build_artifact_ignore_matcher(
        deps.workspace_root,
        deps.output_dir,
        deps.render.artifact_ignore_patterns,
    )


def _existing_artifact_paths(
    workspace: Path,
    artifact_paths: list[str],
    matcher: ArtifactIgnoreMatcher,
) -> list[str]:
    existing: list[str] = []
    for path in artifact_paths:
        destination = workspace / path
        if not destination.is_file() or not is_utf8_text_file(destination):
            continue
        existing.append(path)
    return filter_deliverable_candidates(existing, matcher)


def _reset_render_state(output_dir: Path) -> None:
    from top_down_planning.persistence import render_dir

    directory = render_dir(output_dir)
    if directory.is_dir():
        shutil.rmtree(directory)


def _persist_render_result(
    deps: RenderFlowDeps,
    run_state: RunState,
    artifact_paths: list[str],
) -> list[str]:
    workspace = deps.workspace_root.resolve()
    relative: list[str] = []
    matcher = _artifact_ignore_matcher(deps)
    for artifact in _existing_artifact_paths(workspace, artifact_paths, matcher):
        path = Path(artifact)
        if path.is_absolute():
            relative.append(path.resolve().relative_to(workspace).as_posix())
        else:
            relative.append(artifact.replace("\\", "/"))
    run_state.generated_artifacts = relative
    save_run_state(deps.output_dir, run_state)
    return [str(workspace / name) for name in relative]


def existing_deliverable_artifacts(
    workspace: Path,
    run_state: RunState,
    render_state: RenderState | None,
    *,
    output_dir: Path,
    artifact_ignore_patterns: list[str],
) -> list[str] | None:
    if render_state is None or render_state.stage != RenderStage.COMPLETE:
        return None
    if not run_state.generated_artifacts:
        return None
    if canonical_state_prefix(workspace, output_dir) is None:
        return None
    matcher = build_artifact_ignore_matcher(
        workspace,
        output_dir,
        artifact_ignore_patterns,
    )
    normalized = _existing_artifact_paths(workspace, run_state.generated_artifacts, matcher)
    if not normalized:
        return None
    absolute = [str(workspace / relative) for relative in normalized]
    if render_state.deliverable_output_digest:
        try:
            current = collect_deliverable_output(workspace, normalized, matcher)
        except (ValueError, UnicodeDecodeError):
            return None
        if current.digest != render_state.deliverable_output_digest:
            return None
    return absolute


def _format_findings_summary(findings) -> str:
    if not findings:
        return ""
    lines = []
    for finding in findings:
        lines.append(f"- [{finding.severity.value}] {finding.description}")
        if finding.recommended_change:
            lines.append(f"  - Recommended: {finding.recommended_change}")
    return "\n".join(lines)


def _format_batch_findings_summary(findings) -> str:
    return _format_findings_summary(findings)
