"""Shared render pipeline for normal runs and render-only mode."""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from top_down_planning.console_renderer import ConsoleRenderer
from top_down_planning.cursor_client import CursorClient
from top_down_planning.digest import compute_plan_digest, compute_render_config_digest, digest_file
from top_down_planning.errors import CursorEnvironmentError, CursorSessionError, PlanningToolError, UserInterrupted
from top_down_planning.input_loader import LoadedInput, LoadedOutputGoal
from top_down_planning.models import (
    DeliverableStatus,
    PlanState,
    RenderBatchStateEntry,
    RenderBatchStatus,
    RenderConfig,
    RenderManifest,
    RenderOutputReviewDecision,
    RenderOutputReviewStatus,
    RenderStage,
    RenderState,
    RunState,
)
from top_down_planning.persistence import (
    load_owned_artifacts,
    load_render_state,
    record_history,
    render_batch_dir,
    render_batch_transaction_path,
    render_manifest_path,
    save_render_state,
    save_run_state,
)
from top_down_planning.prompts import build_render_batch_prompt
from top_down_planning.render_assembly import (
    AssembledOutput,
    assemble_render_output,
    load_valid_batch_transactions,
    write_assembled_output,
)
from top_down_planning.render_batcher import items_for_batch
from top_down_planning.render_context import prepare_render_batch_context
from top_down_planning.render_manifest import (
    FINAL_BATCH_ID,
    apply_final_transaction_to_manifest,
    build_render_manifest,
    compute_manifest_digest,
    load_render_manifest,
    manifest_is_valid,
    scheduled_batch_ids,
    save_render_manifest as write_manifest_file,
    strip_final_items_from_manifest,
)
from top_down_planning.render_deliverables import (
    collect_deliverable_output,
    finalize_deliverables,
    materialize_final_deliverables,
)
from top_down_planning.render_review import (
    RenderReviewDeps,
    review_status_from_decision,
    run_render_output_review,
)
from top_down_planning.render_tool import build_render_session_env, resolve_render_tool_command
from top_down_planning.render_transaction import validate_batch_transaction
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
    deps.stream.emit("render.started")
    deps.renderer.rule("RENDER deliverables in staged batches and workspace destinations")

    plan_digest = compute_plan_digest(plan)
    render_config = deps.render
    render_config_digest = compute_render_config_digest(render_config)

    render_state = load_render_state(deps.output_dir) or RenderState()
    if _should_invalidate_render_state(
        render_state,
        plan_digest=plan_digest,
        output_goal_digest=deps.output_goal.digest,
        render_config_digest=render_config_digest,
        force_rerender=force_rerender,
    ):
        _clear_render_staging(deps.output_dir)
        render_state = RenderState()

    manifest, manifest_digest, reused = _ensure_manifest(
        deps,
        plan=plan,
        plan_digest=plan_digest,
        render_config=render_config,
        render_state=render_state,
    )
    deps.stream.emit(
        "render.manifest.reused" if reused else "render.manifest.created",
        digest=manifest_digest,
    )

    render_state.plan_digest = plan_digest
    render_state.output_goal_digest = deps.output_goal.digest
    render_state.render_config_digest = render_config_digest
    render_state.render_manifest_digest = manifest_digest
    render_state.stage = RenderStage.BATCHES
    _sync_batch_state(render_state, manifest, force=force_rerender)
    manifest = _invalidate_missing_deliverables(
        deps,
        manifest=manifest,
        render_state=render_state,
        force_rerender=force_rerender,
    )
    manifest_digest = compute_manifest_digest(manifest)
    render_state.render_manifest_digest = manifest_digest
    save_render_state(deps.output_dir, render_state)

    await _run_render_batches(
        deps,
        plan=plan,
        manifest=manifest,
        render_state=render_state,
        run_state=run_state,
        force_rerender=force_rerender,
    )

    manifest_path = render_manifest_path(deps.output_dir)
    manifest = load_render_manifest(manifest_path)
    manifest_digest = compute_manifest_digest(manifest)
    render_state.render_manifest_digest = manifest_digest
    save_render_state(deps.output_dir, render_state)

    render_state.stage = RenderStage.ASSEMBLY
    save_render_state(deps.output_dir, render_state)
    deps.stream.emit("render.assembly.started")

    transactions = load_valid_batch_transactions(deps.output_dir, manifest)
    try:
        assembled = assemble_render_output(manifest, transactions)
    except ValueError as exc:
        deps.stream.emit("render.validation_failed", errors=[str(exc)])
        raise PlanningToolError(f"Render assembly failed: {exc}") from exc

    write_assembled_output(deps.output_dir, assembled)
    render_state.assembled_output_digest = assembled.digest
    save_render_state(deps.output_dir, render_state)
    deps.stream.emit("render.assembly.completed", digest=assembled.digest)

    try:
        deliverable = collect_deliverable_output(deps.workspace_root, manifest)
    except ValueError as exc:
        deps.stream.emit("render.validation_failed", errors=[str(exc)])
        raise PlanningToolError(f"Deliverable collection failed: {exc}") from exc
    render_state.deliverable_output_digest = deliverable.digest
    save_render_state(deps.output_dir, render_state)

    if render_config.final_review:
        render_state.stage = RenderStage.REVIEW
        save_render_state(deps.output_dir, render_state)
        await _run_output_review_cycle(
            deps,
            plan=plan,
            plan_digest=plan_digest,
            manifest=manifest,
            manifest_digest=manifest_digest,
            render_state=render_state,
            run_state=run_state,
            force_rerender=force_rerender,
        )
        deliverable = collect_deliverable_output(deps.workspace_root, manifest)
        render_state.deliverable_output_digest = deliverable.digest
        save_render_state(deps.output_dir, render_state)
    else:
        render_state.output_review_status = RenderOutputReviewStatus.SKIPPED
        save_render_state(deps.output_dir, render_state)

    deps.stream.emit("render.finalization.started")
    render_state.stage = RenderStage.FINALIZATION
    save_render_state(deps.output_dir, render_state)

    previous_ledger = load_owned_artifacts(deps.output_dir)
    finalization = finalize_deliverables(
        output_dir=deps.output_dir,
        workspace=deps.workspace_root,
        manifest=manifest,
        previous_ledger=previous_ledger,
    )

    render_state.deliverable_status = DeliverableStatus.COMPLETE
    render_state.stage = RenderStage.COMPLETE
    save_render_state(deps.output_dir, render_state)

    paths = _persist_render_result(deps, run_state, finalization.artifacts)
    record_history(
        deps.output_dir,
        run_state,
        event="render_applied",
        artifacts=paths,
        manifest_digest=manifest_digest,
    )
    save_run_state(deps.output_dir, run_state)

    deps.stream.emit("render.finalization.completed", artifacts=paths)
    deps.stream.emit("render.completed", artifacts=paths)
    return RenderFlowResult(artifacts=paths)


def _invalidate_missing_deliverables(
    deps: RenderFlowDeps,
    *,
    manifest: RenderManifest,
    render_state: RenderState,
    force_rerender: bool,
) -> RenderManifest:
    if force_rerender:
        return manifest
    if not any(item.artifact_role == "final" for item in manifest.items):
        return manifest
    try:
        collect_deliverable_output(deps.workspace_root, manifest)
        return manifest
    except ValueError:
        batch_entry = render_state.batches.get(FINAL_BATCH_ID)
        if batch_entry is None:
            return manifest
        batch_entry.status = RenderBatchStatus.PENDING
        batch_entry.transaction_digest = None
        render_batch_transaction_path(deps.output_dir, FINAL_BATCH_ID).unlink(missing_ok=True)
        stripped = strip_final_items_from_manifest(manifest)
        write_manifest_file(render_manifest_path(deps.output_dir), stripped)
        return stripped


def _should_invalidate_render_state(
    render_state: RenderState,
    *,
    plan_digest: str,
    output_goal_digest: str,
    render_config_digest: str,
    force_rerender: bool,
) -> bool:
    if force_rerender:
        return True
    if not render_state.plan_digest:
        return False
    return (
        render_state.plan_digest != plan_digest
        or render_state.output_goal_digest != output_goal_digest
        or render_state.render_config_digest != render_config_digest
    )


def _clear_render_staging(output_dir: Path) -> None:
    from top_down_planning.persistence import render_dir

    root = render_dir(output_dir)
    if root.exists():
        shutil.rmtree(root)


def _ensure_manifest(
    deps: RenderFlowDeps,
    *,
    plan: PlanState,
    plan_digest: str,
    render_config: RenderConfig,
    render_state: RenderState,
) -> tuple[RenderManifest, str, bool]:
    path = render_manifest_path(deps.output_dir)
    if (
        path.is_file()
        and render_state.render_manifest_digest
        and render_state.plan_digest == plan_digest
        and render_state.output_goal_digest == deps.output_goal.digest
        and render_state.render_config_digest == compute_render_config_digest(render_config)
    ):
        try:
            manifest = load_render_manifest(path)
        except ValidationError:
            manifest = None
        else:
            if manifest_is_valid(manifest):
                return manifest, render_state.render_manifest_digest, True

    manifest = build_render_manifest(
        plan,
        plan_digest=plan_digest,
        output_goal_digest=deps.output_goal.digest,
        render_config=render_config,
    )
    manifest_digest = compute_manifest_digest(manifest)
    write_manifest_file(path, manifest)
    return manifest, manifest_digest, False


def _sync_batch_state(
    render_state: RenderState,
    manifest: RenderManifest,
    *,
    force: bool,
) -> None:
    existing = dict(render_state.batches)
    render_state.batches = {}
    for batch_id in scheduled_batch_ids(manifest):
        assigned = [item.plan_item_id for item in items_for_batch(manifest.items, batch_id)]
        prior = existing.get(batch_id)
        if (
            not force
            and prior is not None
            and prior.status == RenderBatchStatus.VALID
            and prior.transaction_digest
        ):
            render_state.batches[batch_id] = prior
        else:
            render_state.batches[batch_id] = RenderBatchStateEntry(
                assigned_item_ids=assigned,
            )


async def _run_render_batches(
    deps: RenderFlowDeps,
    *,
    plan: PlanState,
    manifest: RenderManifest,
    render_state: RenderState,
    run_state: RunState,
    force_rerender: bool,
) -> None:
    all_batch_ids = scheduled_batch_ids(manifest)
    pending = [
        batch_id
        for batch_id in all_batch_ids
        if force_rerender
        or render_state.batches[batch_id].status != RenderBatchStatus.VALID
    ]
    if not pending:
        return

    intermediate_batch_ids = [
        batch_id for batch_id in pending if batch_id != FINAL_BATCH_ID
    ]
    final_batch_id = FINAL_BATCH_ID if FINAL_BATCH_ID in pending else None

    semaphore = asyncio.Semaphore(max(1, deps.render.concurrent_batches))

    async def run_one(batch_id: str) -> None:
        async with semaphore:
            await _run_single_batch(
                deps,
                plan=plan,
                manifest=manifest,
                batch_id=batch_id,
                render_state=render_state,
                run_state=run_state,
            )

    if intermediate_batch_ids:
        await asyncio.gather(*(run_one(batch_id) for batch_id in intermediate_batch_ids))
    if final_batch_id:
        await run_one(final_batch_id)


async def _run_single_batch(
    deps: RenderFlowDeps,
    *,
    plan: PlanState,
    manifest: RenderManifest,
    batch_id: str,
    render_state: RenderState,
    run_state: RunState,
) -> None:
    assigned_items = items_for_batch(manifest.items, batch_id)
    plan_digest = manifest.plan_digest
    manifest_digest = render_state.render_manifest_digest
    batch_entry = render_state.batches[batch_id]
    batch_entry.status = RenderBatchStatus.RUNNING
    save_render_state(deps.output_dir, render_state)

    prepared = prepare_render_batch_context(
        plan=plan,
        manifest=manifest,
        assigned_items=assigned_items,
        output_dir=deps.output_dir,
        workspace=deps.workspace_root,
        output_goal=deps.output_goal,
        whole_plan_context=deps.render.whole_plan_context,
        embed_threshold=deps.embed_threshold,
        batch_id=batch_id,
        manifest_digest=manifest_digest,
    )
    deps.stream.emit(
        "render.batch.context_prepared",
        batch_id=batch_id,
        plan_item_ids=[item.plan_item_id for item in assigned_items],
    )

    txn_path = render_batch_transaction_path(deps.output_dir, batch_id)
    batch_dir = render_batch_dir(deps.output_dir, batch_id)
    batch_dir.mkdir(parents=True, exist_ok=True)
    if txn_path.is_file():
        txn_path.unlink()

    validation_feedback: list[str] | None = None
    for attempt in range(1, deps.render.max_retries + 1):
        batch_entry.attempts = attempt
        deps.stream.emit(
            "render.batch.started",
            batch_id=batch_id,
            attempt=attempt,
            plan_item_ids=[item.plan_item_id for item in assigned_items],
        )

        prompt = build_render_batch_prompt(
            batch_id=batch_id,
            plan_digest=plan_digest,
            output_goal_digest=manifest.output_goal_digest,
            render_config_digest=manifest.render_config_digest,
            batch_context_markdown=prepared.batch_context_markdown,
            output_goal=deps.output_goal,
            workspace=deps.workspace_root,
            embed_threshold=deps.embed_threshold,
            validation_feedback=validation_feedback,
            agent_context=deps.resolve_render_context(),
            render_tool_command=resolve_render_tool_command(),
            is_final_batch=batch_id == FINAL_BATCH_ID,
        )
        prompt_path = batch_dir / f"request-{attempt:03d}-prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")

        session_env = build_render_session_env(
            transaction_path=txn_path,
            batch_id=batch_id,
            plan_digest=plan_digest,
            output_goal_digest=manifest.output_goal_digest,
            render_config_digest=manifest.render_config_digest,
        )

        try:
            await deps.client.run_session(
                workspace=deps.workspace_root,
                prompt=prompt,
                prompt_path=prompt_path,
                timeout_seconds=deps.session_timeout_seconds,
                events_path=batch_dir / f"agent-{attempt:03d}.ndjson" if deps.audit else None,
                log_path=batch_dir / f"agent-{attempt:03d}.log" if deps.audit else None,
                renderer=deps.renderer,
                session_mode="agent",
                model=deps.resolve_render_model(),
                extra_env=session_env,
            )
        except UserInterrupted:
            run_state.agent_pids = []
            save_run_state(deps.output_dir, run_state)
            raise
        except CursorEnvironmentError:
            raise
        except CursorSessionError as exc:
            batch_entry.status = RenderBatchStatus.FAILED
            save_render_state(deps.output_dir, render_state)
            if attempt >= deps.render.max_retries:
                deps.stream.emit("render.batch.failed", batch_id=batch_id, reason=str(exc))
                raise
            deps.stream.emit(
                "render.batch.retrying",
                batch_id=batch_id,
                attempt=attempt + 1,
                reason=str(exc),
            )
            continue

        if not txn_path.is_file():
            validation_feedback = ["Batch transaction was not finalized"]
            deps.stream.emit(
                "render.validation_failed",
                batch_id=batch_id,
                attempt=attempt,
                errors=validation_feedback,
            )
            if attempt >= deps.render.max_retries:
                batch_entry.status = RenderBatchStatus.FAILED
                save_render_state(deps.output_dir, render_state)
                deps.stream.emit("render.batch.failed", batch_id=batch_id, reason="missing transaction")
                raise CursorSessionError(f"Render batch {batch_id} did not finalize a transaction")
            deps.stream.emit(
                "render.batch.retrying",
                batch_id=batch_id,
                attempt=attempt + 1,
                reason="missing transaction",
            )
            continue

        from top_down_planning.render_tool import load_render_transaction

        transaction = load_render_transaction(txn_path)
        validation_feedback = validate_batch_transaction(
            transaction,
            manifest=manifest,
            assigned_items=assigned_items,
            expected_batch_id=batch_id,
            expected_plan_digest=plan_digest,
            expected_output_goal_digest=manifest.output_goal_digest,
            expected_render_config_digest=manifest.render_config_digest,
            workspace=deps.workspace_root if batch_id == FINAL_BATCH_ID else None,
        )
        if validation_feedback:
            deps.stream.emit(
                "render.validation_failed",
                batch_id=batch_id,
                attempt=attempt,
                errors=validation_feedback,
            )
            if attempt >= deps.render.max_retries:
                batch_entry.status = RenderBatchStatus.FAILED
                save_render_state(deps.output_dir, render_state)
                deps.stream.emit(
                    "render.batch.failed",
                    batch_id=batch_id,
                    reason="; ".join(validation_feedback),
                )
                raise CursorSessionError(
                    f"Render batch {batch_id} failed validation: {'; '.join(validation_feedback)}"
                )
            deps.stream.emit(
                "render.batch.retrying",
                batch_id=batch_id,
                attempt=attempt + 1,
                reason="; ".join(validation_feedback),
            )
            txn_path.unlink(missing_ok=True)
            continue

        if batch_id == FINAL_BATCH_ID:
            try:
                materialize_final_deliverables(deps.workspace_root, transaction)
            except ValueError as exc:
                validation_feedback = [str(exc)]
                deps.stream.emit(
                    "render.validation_failed",
                    batch_id=batch_id,
                    attempt=attempt,
                    errors=validation_feedback,
                )
                if attempt >= deps.render.max_retries:
                    batch_entry.status = RenderBatchStatus.FAILED
                    save_render_state(deps.output_dir, render_state)
                    raise CursorSessionError(
                        f"Render batch {batch_id} failed materialization: {exc}"
                    ) from exc
                deps.stream.emit(
                    "render.batch.retrying",
                    batch_id=batch_id,
                    attempt=attempt + 1,
                    reason=str(exc),
                )
                txn_path.unlink(missing_ok=True)
                continue

            manifest = apply_final_transaction_to_manifest(manifest, transaction)
            manifest_digest = compute_manifest_digest(manifest)
            write_manifest_file(render_manifest_path(deps.output_dir), manifest)
            render_state.render_manifest_digest = manifest_digest
            batch_entry.assigned_item_ids = [
                item.plan_item_id for item in manifest.items if item.artifact_role == "final"
            ]

        batch_entry.status = RenderBatchStatus.VALID
        batch_entry.transaction_digest = digest_file(txn_path)
        save_render_state(deps.output_dir, render_state)
        deps.stream.emit(
            "render.batch.completed",
            batch_id=batch_id,
            attempt=attempt,
            plan_item_ids=[item.plan_item_id for item in assigned_items],
        )
        return

    batch_entry.status = RenderBatchStatus.FAILED
    save_render_state(deps.output_dir, render_state)
    raise CursorSessionError(
        f"Render batch {batch_id} failed after {deps.render.max_retries} attempts"
    )


async def _run_output_review_cycle(
    deps: RenderFlowDeps,
    *,
    plan: PlanState,
    plan_digest: str,
    manifest: RenderManifest,
    manifest_digest: str,
    render_state: RenderState,
    run_state: RunState,
    force_rerender: bool,
) -> None:
    max_cycles = deps.render.max_rerender_cycles
    for cycle in range(max_cycles + 1):
        transactions = load_valid_batch_transactions(deps.output_dir, manifest)
        assembled = assemble_render_output(manifest, transactions)
        write_assembled_output(deps.output_dir, assembled)

        try:
            deliverable = collect_deliverable_output(deps.workspace_root, manifest)
        except ValueError as exc:
            raise PlanningToolError(f"Deliverable collection failed: {exc}") from exc
        render_state.deliverable_output_digest = deliverable.digest
        save_render_state(deps.output_dir, render_state)

        deps.stream.emit("render.review.started", cycle=cycle)
        review_deps = RenderReviewDeps(
            workspace_root=deps.workspace_root,
            output_dir=deps.output_dir,
            output_goal=deps.output_goal,
            embed_threshold=deps.embed_threshold,
            client=deps.client,
            renderer=deps.renderer,
            audit=deps.audit,
            resolve_review_context=deps.resolve_review_context,
            resolve_review_model=deps.resolve_review_model,
        )
        result = await run_render_output_review(
            review_deps,
            plan_digest=plan_digest,
            manifest=manifest,
            manifest_digest=manifest_digest,
            deliverable=deliverable,
            max_retries=deps.render.max_retries,
        )
        if result is None:
            render_state.output_review_status = RenderOutputReviewStatus.BLOCKED
            save_render_state(deps.output_dir, render_state)
            deps.stream.emit("render.review.completed", decision="blocked")
            raise PlanningToolError(
                "Rendered output review blocked: reviewer did not finalize a result."
            )

        render_state.output_review_status = review_status_from_decision(result.decision)
        save_render_state(deps.output_dir, render_state)
        deps.stream.emit(
            "render.review.completed",
            decision=result.decision.value,
            summary=result.summary,
        )

        if result.decision == RenderOutputReviewDecision.APPROVE:
            return

        if result.decision == RenderOutputReviewDecision.BLOCKED:
            raise PlanningToolError(
                f"Rendered output review blocked: {result.summary or 'no summary provided.'}"
            )

        if cycle >= max_cycles:
            raise PlanningToolError(
                "Rendered output review exceeded max rerender cycles "
                f"({max_cycles})."
            )

        deps.stream.emit("render.review.needs_rerender", affected_batches=result.affected_batch_ids)
        affected = _expand_rerender_batch_ids(set(result.affected_batch_ids), manifest)
        if not affected:
            for finding in result.findings:
                for item_id in finding.plan_item_ids:
                    for item in manifest.items:
                        if item.plan_item_id == item_id:
                            affected.add(item.assigned_batch_id)

        for batch_id in affected:
            if batch_id in render_state.batches:
                render_state.batches[batch_id].status = RenderBatchStatus.PENDING
                render_state.batches[batch_id].transaction_digest = None
                txn_path = render_batch_transaction_path(deps.output_dir, batch_id)
                txn_path.unlink(missing_ok=True)

        if FINAL_BATCH_ID in affected:
            manifest = strip_final_items_from_manifest(manifest)
            write_manifest_file(render_manifest_path(deps.output_dir), manifest)
            manifest_digest = compute_manifest_digest(manifest)
            render_state.render_manifest_digest = manifest_digest

        render_state.rerender_cycle = cycle + 1
        save_render_state(deps.output_dir, render_state)
        await _run_render_batches(
            deps,
            plan=plan,
            manifest=manifest,
            render_state=render_state,
            run_state=run_state,
            force_rerender=False,
        )
        manifest = load_render_manifest(render_manifest_path(deps.output_dir))
        manifest_digest = compute_manifest_digest(manifest)
        render_state.render_manifest_digest = manifest_digest
        save_render_state(deps.output_dir, render_state)

    raise PlanningToolError("Rendered output review did not reach an approved decision.")


def _expand_rerender_batch_ids(
    affected: set[str],
    manifest: RenderManifest,
) -> set[str]:
    """Re-synthesize finals whenever an intermediate batch is invalidated."""
    expanded = set(affected)
    intermediate_batch_ids = {
        item.assigned_batch_id
        for item in manifest.items
        if item.artifact_role == "intermediate"
    }
    if expanded.intersection(intermediate_batch_ids):
        expanded.add(FINAL_BATCH_ID)
    return expanded


def _persist_render_result(
    deps: RenderFlowDeps,
    run_state: RunState,
    artifacts: list[str],
) -> list[str]:
    relative: list[str] = []
    workspace = deps.workspace_root.resolve()
    for artifact in artifacts:
        path = Path(artifact)
        if path.is_absolute():
            relative.append(path.resolve().relative_to(workspace).as_posix())
        else:
            relative.append(artifact.replace("\\", "/"))
    run_state.generated_artifacts = relative
    return [str(workspace / name) for name in relative]


def existing_deliverable_artifacts(
    workspace: Path,
    run_state: RunState,
    render_state: RenderState | None,
    *,
    manifest: RenderManifest | None = None,
) -> list[str] | None:
    if render_state is not None and render_state.stage == RenderStage.COMPLETE:
        if not run_state.generated_artifacts:
            return None
        absolute: list[str] = []
        for relative in run_state.generated_artifacts:
            path = workspace / relative
            if not path.is_file():
                return None
            absolute.append(str(path))
        if manifest is not None and render_state.deliverable_output_digest:
            try:
                current = collect_deliverable_output(workspace, manifest)
            except ValueError:
                return None
            if current.digest != render_state.deliverable_output_digest:
                return None
        return absolute
    return None
