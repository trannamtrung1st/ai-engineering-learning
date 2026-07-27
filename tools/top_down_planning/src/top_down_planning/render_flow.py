"""Per-node progressive render pipeline."""

from __future__ import annotations

import asyncio
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from top_down_planning.console_renderer import ConsoleRenderer
from top_down_planning.cursor_client import CursorClient
from top_down_planning.digest import compute_plan_digest, compute_render_config_digest
from top_down_planning.completeness import structural_errors
from top_down_planning.errors import CursorSessionError, PlanningToolError, UserInterrupted
from top_down_planning.input_loader import LoadedInput, LoadedOutputGoal
from top_down_planning.models import (
    DecompositionStatus,
    DeliverableStatus,
    FinalSynthesisMode,
    NodeRenderPhaseState,
    NodeRenderRevision,
    NodeRenderRevisionStatus,
    PlanState,
    RenderConfig,
    RenderDecisionKind,
    RenderManifest,
    RenderManifestItem,
    RenderManifestItemStatus,
    RenderNodePhase,
    RenderNodeTransaction,
    RenderOutputReviewDecision,
    RenderOutputReviewStatus,
    RenderStage,
    RenderState,
    RunState,
)
from top_down_planning.persistence import (
    load_ownership_ledger,
    load_render_manifest_from_output,
    load_render_state,
    render_decisions_dir,
    render_phases_dir,
    save_render_manifest_to_output,
    save_render_state,
)
from top_down_planning.prompts import build_render_node_prompt
from top_down_planning.render_brief import deterministic_skip_decision, deterministic_skip_reason
from top_down_planning.render_context import prepare_render_node_context
from top_down_planning.render_coordinator import RenderCoordinator
from top_down_planning.render_decisions import all_deferred_resolved, decision_id_for
from top_down_planning.render_deliverables import collect_deliverable_output_from_ledger
from top_down_planning.render_manifest import build_render_manifest, compute_manifest_digest
from top_down_planning.render_ownership import final_paths, owned_paths_for_node
from top_down_planning.render_scheduler import build_rollup_schedule, groups_in_wave, unique_waves
from top_down_planning.render_tool import (
    build_render_session_env,
    load_render_node_transaction,
    resolve_render_tool_command,
)
from top_down_planning.render_rerender import (
    manifest_items_for_rerender,
    prepare_targeted_rerender,
    resolve_rerender_node_ids,
)
from top_down_planning.render_review import (
    RenderReviewDeps,
    progressive_decision_coverage_errors,
    review_status_from_decision,
    run_render_output_review,
)
from top_down_planning.render_transaction import validate_node_render_transaction
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


@dataclass
class _NodeCandidate:
    item: object
    manifest_slot: int
    transaction: RenderNodeTransaction
    plan_digest: str


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
    dry_run = render_config.dry_run

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

    render_state = load_render_state(deps.output_dir) or RenderState()
    reset_publication = _should_reset_publication_state(
        render_state,
        plan_digest=plan_digest,
        output_goal_digest=deps.output_goal.digest,
        render_config_digest=render_config_digest,
        force_rerender=force_rerender,
    )

    existing_manifest = load_render_manifest_from_output(deps.output_dir)
    if (
        not reset_publication
        and existing_manifest is not None
        and render_state.stage == RenderStage.WAVES
    ):
        manifest = existing_manifest
        run_id = manifest.run_id
    else:
        if reset_publication:
            _reset_render_publication_state(deps.output_dir)
        run_id = f"render-run-{uuid.uuid4().hex[:8]}"
        manifest, schedule_errors = build_render_manifest(
            plan,
            run_id=run_id,
            plan_digest=plan_digest,
            output_goal_digest=deps.output_goal.digest,
            render_config=render_config,
        )
        if schedule_errors:
            raise PlanningToolError(
                "Render scheduling failed: " + "; ".join(schedule_errors)
            )

    render_state.run_id = run_id
    render_state.plan_digest = plan_digest
    render_state.output_goal_digest = deps.output_goal.digest
    render_state.render_config_digest = render_config_digest
    render_state.stage = RenderStage.MANIFEST
    manifest_digest = compute_manifest_digest(manifest)
    render_state.render_manifest_digest = manifest_digest
    save_render_state(deps.output_dir, render_state)
    save_render_manifest_to_output(deps.output_dir, manifest)

    coordinator = RenderCoordinator(
        output_dir=deps.output_dir,
        workspace=deps.workspace_root,
        run_id=run_id,
        dry_run=dry_run,
        allow_final_publication=render_config.allow_final_publication,
        allow_staged_artifacts=render_config.allow_staged_artifacts,
    )

    render_state.stage = RenderStage.WAVES
    save_render_state(deps.output_dir, render_state)

    failed_nodes: set[str] = set()
    with coordinator.acquire():
        await _run_render_waves(
            deps,
            plan=plan,
            manifest=manifest,
            coordinator=coordinator,
            run_state=run_state,
            render_state=render_state,
            dry_run=dry_run,
            failed_nodes=failed_nodes,
        )

        if render_config.rollup.enabled:
            rollup_items, rollup_errors = build_rollup_schedule(
                plan, render_config=render_config
            )
            if rollup_errors:
                raise PlanningToolError(
                    "Rollup scheduling failed: " + "; ".join(rollup_errors)
                )
            if rollup_items:
                deps.stream.emit("render.rollup.started", items=len(rollup_items))
                rollup_manifest = manifest.model_copy(deep=True)
                rollup_manifest.items = rollup_items
                await _run_render_waves(
                    deps,
                    plan=plan,
                    manifest=rollup_manifest,
                    coordinator=coordinator,
                    run_state=run_state,
                    render_state=render_state,
                    dry_run=dry_run,
                    failed_nodes=failed_nodes,
                )

        if render_config.final_synthesis == FinalSynthesisMode.OPTIONAL:
            deps.stream.emit("render.synthesis.skipped")
        elif render_config.final_synthesis == FinalSynthesisMode.REQUIRED:
            if not final_paths(coordinator._ledger):
                raise PlanningToolError(
                    "final_synthesis required but no final deliverables were published"
                )
            deps.stream.emit("render.synthesis.verified")

    coverage_errors = progressive_decision_coverage_errors(
        deps.output_dir,
        expected_node_ids={item.plan_item_id for item in manifest.items},
    )
    if coverage_errors and not dry_run:
        raise PlanningToolError(
            "Render decision coverage incomplete: " + "; ".join(coverage_errors)
        )

    unresolved = _unresolved_deferred(coordinator)
    if unresolved and not dry_run:
        raise PlanningToolError(
            "Unresolved deferred decisions: " + ", ".join(unresolved)
        )

    if failed_nodes and not dry_run:
        raise PlanningToolError(
            "Render failed for nodes: " + ", ".join(sorted(failed_nodes))
        )

    if dry_run:
        render_state.stage = RenderStage.COMPLETE
        render_state.deliverable_status = DeliverableStatus.COMPLETE
        render_state.output_review_status = RenderOutputReviewStatus.SKIPPED
        save_render_state(deps.output_dir, render_state)
        deps.stream.emit("render.completed", artifacts=[], dry_run=True)
        return RenderFlowResult(artifacts=[])

    render_state.stage = RenderStage.REVIEW
    save_render_state(deps.output_dir, render_state)

    while True:
        artifacts = final_paths(coordinator._ledger)
        deliverable = None
        if artifacts:
            deliverable = collect_deliverable_output_from_ledger(
                deps.workspace_root,
                coordinator._ledger,
            )
            render_state.deliverable_output_digest = deliverable.digest

        if not render_config.final_review or deliverable is None:
            render_state.output_review_status = RenderOutputReviewStatus.SKIPPED
            break

        deps.stream.emit("render.review.started", cycle=render_state.rerender_cycle)
        coordinator.freeze_for_review()
        try:
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
                ),
                plan_digest=plan_digest,
                manifest=manifest,
                manifest_digest=manifest_digest,
                deliverable=deliverable,
                max_retries=deps.render.max_retries,
            )
        finally:
            coordinator.unfreeze_after_review()

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
            "render.review.completed",
            decision=review_result.decision.value,
            summary=review_result.summary,
            cycle=render_state.rerender_cycle,
        )
        if review_result.decision == RenderOutputReviewDecision.BLOCKED:
            save_render_state(deps.output_dir, render_state)
            raise PlanningToolError(
                f"Rendered output review blocked: {review_result.summary or 'no summary'}"
            )
        if review_result.decision == RenderOutputReviewDecision.APPROVE:
            break

        render_state.rerender_cycle += 1
        if render_state.rerender_cycle > render_config.max_rerender_cycles:
            save_render_state(deps.output_dir, render_state)
            raise PlanningToolError(
                "Rendered output review exceeded max_rerender_cycles "
                f"({render_config.max_rerender_cycles})"
            )

        node_ids = resolve_rerender_node_ids(review_result, plan)
        if not node_ids:
            save_render_state(deps.output_dir, render_state)
            raise PlanningToolError(
                "Rendered output review requested rerender but identified no affected nodes"
            )

        deps.stream.emit(
            "render.rerender.started",
            cycle=render_state.rerender_cycle,
            node_ids=node_ids,
        )
        failed_nodes.clear()
        render_state.stage = RenderStage.WAVES
        save_render_state(deps.output_dir, render_state)
        with coordinator.acquire():
            target_ids = prepare_targeted_rerender(
                output_dir=deps.output_dir,
                workspace=deps.workspace_root,
                plan=plan,
                manifest=manifest,
                render_state=render_state,
                coordinator=coordinator,
                node_ids=node_ids,
            )
            await _run_render_waves(
                deps,
                plan=plan,
                manifest=manifest,
                coordinator=coordinator,
                run_state=run_state,
                render_state=render_state,
                dry_run=dry_run,
                failed_nodes=failed_nodes,
                only_node_ids=target_ids,
            )
        if failed_nodes and not dry_run:
            raise PlanningToolError(
                "Targeted rerender failed for nodes: "
                + ", ".join(sorted(failed_nodes))
            )
        manifest_digest = compute_manifest_digest(manifest)
        render_state.render_manifest_digest = manifest_digest
        save_render_manifest_to_output(deps.output_dir, manifest)
        deps.stream.emit(
            "render.rerender.completed",
            cycle=render_state.rerender_cycle,
            node_ids=sorted(target_ids),
        )

    render_state.stage = RenderStage.COMPLETE
    render_state.deliverable_status = DeliverableStatus.COMPLETE
    save_render_state(deps.output_dir, render_state)
    artifacts = final_paths(coordinator._ledger)
    paths = _persist_render_result(deps, run_state, artifacts)
    deps.stream.emit("render.completed", artifacts=paths)
    return RenderFlowResult(artifacts=paths)


async def _run_render_waves(
    deps: RenderFlowDeps,
    *,
    plan: PlanState,
    manifest: RenderManifest,
    coordinator: RenderCoordinator,
    run_state: RunState,
    render_state: RenderState,
    dry_run: bool,
    failed_nodes: set[str],
    only_node_ids: set[str] | None = None,
) -> None:
    del dry_run
    manifest_slot = coordinator._commit_sequence
    active_items = manifest_items_for_rerender(manifest.items, only_node_ids)

    for wave in unique_waves(active_items):
        for group in groups_in_wave(active_items, wave):
            group_items = [
                item
                for item in active_items
                if item.wave == wave and item.generation_group == group
            ]
            manifest_slot = await _run_generation_group(
                deps,
                plan=plan,
                manifest=manifest,
                group_items=group_items,
                coordinator=coordinator,
                manifest_slot_start=manifest_slot,
                run_state=run_state,
                render_state=render_state,
                failed_nodes=failed_nodes,
            )
            save_render_manifest_to_output(deps.output_dir, manifest)


async def _run_generation_group(
    deps: RenderFlowDeps,
    *,
    plan: PlanState,
    manifest: RenderManifest,
    group_items: list[RenderManifestItem],
    coordinator: RenderCoordinator,
    manifest_slot_start: int,
    run_state: RunState,
    render_state: RenderState,
    failed_nodes: set[str],
) -> int:
    semaphore = asyncio.Semaphore(max(1, deps.render.concurrent_batches))
    candidates: dict[int, _NodeCandidate | None] = {}

    async def generate(item: RenderManifestItem, slot: int) -> None:
        async with semaphore:
            if _is_dependency_blocked(plan, item, failed_nodes):
                candidates[slot] = None
                return
            try:
                candidates[slot] = await _generate_node_candidate(
                    deps,
                    plan=plan,
                    manifest=manifest,
                    item=item,
                    coordinator=coordinator,
                    manifest_slot=slot,
                    run_state=run_state,
                )
            except CursorSessionError:
                failed_nodes.add(item.plan_item_id)
                candidates[slot] = None

    await asyncio.gather(
        *(
            generate(item, manifest_slot_start + offset)
            for offset, item in enumerate(group_items)
        )
    )

    slot = manifest_slot_start
    for offset, item in enumerate(group_items):
        current_slot = manifest_slot_start + offset
        candidate = candidates.get(current_slot)
        if candidate is None:
            if _is_dependency_blocked(plan, item, failed_nodes):
                item.status = RenderManifestItemStatus.DEPENDENCY_FAILED
                _record_node_failure(
                    render_state,
                    item,
                    status=NodeRenderRevisionStatus.DEPENDENCY_FAILED,
                )
            else:
                item.status = RenderManifestItemStatus.FAILED
                failed_nodes.add(item.plan_item_id)
                _record_node_failure(
                    render_state,
                    item,
                    status=NodeRenderRevisionStatus.FAILED,
                )
            barrier = coordinator.commit_failure_barrier(
                manifest_slot=current_slot,
                node_id=item.plan_item_id,
                reason="terminal node failure",
            )
            if not barrier.committed:
                raise PlanningToolError(
                    f"Failed to advance failure barrier for {item.plan_item_id}: "
                    f"{barrier.errors}"
                )
            slot = current_slot + 1
            continue

        result = await coordinator.commit_candidate_async(
            candidate.transaction,
            manifest_slot=current_slot,
            plan_digest=candidate.plan_digest,
        )
        if not result.committed:
            item.status = RenderManifestItemStatus.FAILED
            failed_nodes.add(item.plan_item_id)
            _record_node_failure(
                render_state,
                item,
                status=NodeRenderRevisionStatus.FAILED,
            )
            barrier = coordinator.commit_failure_barrier(
                manifest_slot=current_slot,
                node_id=item.plan_item_id,
                reason="; ".join(result.errors),
            )
            if not barrier.committed:
                raise PlanningToolError(
                    f"Failed to advance failure barrier for {item.plan_item_id}: "
                    f"{barrier.errors}"
                )
            slot = current_slot + 1
            continue

        transaction = candidate.transaction
        if transaction.decision == RenderDecisionKind.PRODUCE:
            item.status = RenderManifestItemStatus.COMMITTED
        elif transaction.decision == RenderDecisionKind.DEFER:
            item.status = RenderManifestItemStatus.DEFERRED
        else:
            item.status = RenderManifestItemStatus.SKIPPED
        _record_node_commit(
            render_state,
            item,
            transaction=transaction,
            decision_id=result.decision_id,
        )
        slot = current_slot + 1

    save_render_state(deps.output_dir, render_state)
    return slot


async def _generate_node_candidate(
    deps: RenderFlowDeps,
    *,
    plan: PlanState,
    manifest: RenderManifest,
    item: RenderManifestItem,
    coordinator: RenderCoordinator,
    manifest_slot: int,
    run_state: RunState,
) -> _NodeCandidate:
    plan_digest = manifest.plan_digest
    phase = item.phase
    plan_item = plan.item_by_id(item.plan_item_id)
    skip_kind = deterministic_skip_decision(plan_item) if plan_item else None
    if skip_kind is not None:
        transaction = RenderNodeTransaction(
            transaction_id=f"txn-{item.plan_item_id}-{phase.value}",
            node_id=item.plan_item_id,
            phase=phase,
            revision=item.revision,
            context_digest="deterministic",
            read_set_digest="deterministic",
            plan_digest=plan_digest,
            output_goal_digest=manifest.output_goal_digest,
            render_config_digest=manifest.render_config_digest,
            decision=RenderDecisionKind.SKIP,
            reason=deterministic_skip_reason(plan_item),
        )
        return _NodeCandidate(
            item=item,
            manifest_slot=manifest_slot,
            transaction=transaction,
            plan_digest=plan_digest,
        )

    ancestor_decision_ids = _ancestor_decision_ids(
        coordinator.output_dir,
        plan,
        item.plan_item_id,
    )
    owned = owned_paths_for_node(coordinator._ledger, item.plan_item_id)
    prepared = prepare_render_node_context(
        plan=plan,
        node_id=item.plan_item_id,
        output_dir=deps.output_dir,
        workspace=deps.workspace_root,
        output_goal=deps.output_goal,
        whole_plan_context=deps.render.whole_plan_context,
        embed_threshold=deps.embed_threshold,
        plan_digest=plan_digest,
        ancestor_decision_ids=ancestor_decision_ids,
        owned_artifact_paths=owned,
    )

    txn_path = prepared.staging_dir.parent / "transaction.yaml"
    session_env = build_render_session_env(
        transaction_path=txn_path,
        node_id=item.plan_item_id,
        context_digest=prepared.context_snapshot.context_digest,
        plan_digest=plan_digest,
        output_goal_digest=manifest.output_goal_digest,
        render_config_digest=manifest.render_config_digest,
        staging_dir=prepared.staging_dir,
    )

    prompt = build_render_node_prompt(
        node_id=item.plan_item_id,
        plan_digest=plan_digest,
        output_goal_digest=manifest.output_goal_digest,
        render_config_digest=manifest.render_config_digest,
        node_context_markdown=prepared.node_context_markdown,
        output_goal=deps.output_goal,
        workspace=deps.workspace_root,
        embed_threshold=deps.embed_threshold,
        agent_context=deps.resolve_render_context(),
        render_tool_command=resolve_render_tool_command(),
    )

    node_dir = prepared.staging_dir.parent
    node_dir.mkdir(parents=True, exist_ok=True)
    validation_feedback: list[str] | None = None

    for attempt in range(1, deps.render.max_retries + 1):
        prompt_path = node_dir / f"request-{attempt:03d}-prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        if txn_path.is_file():
            txn_path.unlink()

        try:
            await deps.client.run_session(
                workspace=deps.workspace_root,
                prompt=prompt,
                prompt_path=prompt_path,
                timeout_seconds=deps.session_timeout_seconds,
                events_path=node_dir / f"agent-{attempt:03d}.ndjson" if deps.audit else None,
                log_path=node_dir / f"agent-{attempt:03d}.log" if deps.audit else None,
                renderer=deps.renderer,
                session_mode="agent",
                model=deps.resolve_render_model(),
                extra_env=session_env,
            )
        except UserInterrupted:
            run_state.agent_pids = []
            raise
        except CursorSessionError as exc:
            if attempt >= deps.render.max_retries:
                raise
            validation_feedback = [str(exc)]
            continue

        if not txn_path.is_file():
            validation_feedback = ["node transaction was not submitted"]
            if attempt >= deps.render.max_retries:
                raise CursorSessionError(
                    f"Render node {item.plan_item_id} did not submit a transaction"
                )
            continue

        transaction = load_render_node_transaction(txn_path)
        transaction.revision = item.revision
        errors = validate_node_render_transaction(
            transaction,
            expected_node_id=item.plan_item_id,
            expected_plan_digest=plan_digest,
            expected_output_goal_digest=manifest.output_goal_digest,
            expected_render_config_digest=manifest.render_config_digest,
            expected_context_digest=prepared.context_snapshot.context_digest,
        )
        if errors:
            validation_feedback = errors
            if attempt >= deps.render.max_retries:
                raise CursorSessionError(
                    f"Render node {item.plan_item_id} failed validation: {'; '.join(errors)}"
                )
            continue

        return _NodeCandidate(
            item=item,
            manifest_slot=manifest_slot,
            transaction=transaction,
            plan_digest=plan_digest,
        )

    raise CursorSessionError(
        f"Render node {item.plan_item_id} failed after {deps.render.max_retries} attempts"
    )


def _should_reset_publication_state(
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
    if render_state.stage == RenderStage.WAVES:
        return False
    return True


def _is_dependency_blocked(
    plan: PlanState,
    item: RenderManifestItem,
    failed_nodes: set[str],
) -> bool:
    current_id: str | None = item.plan_item_id
    while current_id:
        plan_item = plan.item_by_id(current_id)
        if plan_item is None:
            break
        parent_id = plan_item.parent_id
        if parent_id and parent_id in failed_nodes:
            return True
        current_id = parent_id
    return any(dep in failed_nodes for dep in item.dependencies)


def _record_node_commit(
    render_state: RenderState,
    item: RenderManifestItem,
    *,
    transaction: RenderNodeTransaction,
    decision_id: str | None,
) -> None:
    phase_key = item.phase.value
    node_phases = render_state.nodes.setdefault(item.plan_item_id, {})
    phase_state = node_phases.get(phase_key)
    if not isinstance(phase_state, NodeRenderPhaseState):
        phase_state = NodeRenderPhaseState()
        node_phases[phase_key] = phase_state
    revision = phase_state.revisions.setdefault(
        item.revision,
        NodeRenderRevision(),
    )
    revision.status = NodeRenderRevisionStatus.COMMITTED
    revision.decision = transaction.decision
    revision.decision_id = decision_id
    revision.artifacts = [artifact.path for artifact in transaction.artifacts]


def _record_node_failure(
    render_state: RenderState,
    item: RenderManifestItem,
    *,
    status: NodeRenderRevisionStatus,
) -> None:
    phase_key = item.phase.value
    node_phases = render_state.nodes.setdefault(item.plan_item_id, {})
    phase_state = node_phases.get(phase_key)
    if not isinstance(phase_state, NodeRenderPhaseState):
        phase_state = NodeRenderPhaseState()
        node_phases[phase_key] = phase_state
    revision = phase_state.revisions.setdefault(item.revision, NodeRenderRevision())
    revision.status = status


def _reset_render_publication_state(output_dir: Path) -> None:
    from top_down_planning.persistence import (
        commit_journal_path,
        coordinator_state_path,
        ownership_ledger_path,
        render_decisions_dir,
        render_dir,
        render_staged_artifacts_dir,
        render_transactions_dir,
    )

    commit_journal_path(output_dir).unlink(missing_ok=True)
    coordinator_state_path(output_dir).unlink(missing_ok=True)
    ownership_ledger_path(output_dir).unlink(missing_ok=True)
    staged = render_staged_artifacts_dir(output_dir)
    if staged.is_dir():
        shutil.rmtree(staged)
    decisions = render_decisions_dir(output_dir)
    if decisions.is_dir():
        shutil.rmtree(decisions)
    transactions = render_transactions_dir(output_dir)
    if transactions.is_dir():
        shutil.rmtree(transactions)
    for legacy_subdir in ("batches", "assembled"):
        path = render_dir(output_dir) / legacy_subdir
        if path.is_dir():
            shutil.rmtree(path)


def _ancestor_decision_ids(output_dir: Path, plan: PlanState, node_id: str) -> list[str]:
    from top_down_planning.persistence import load_render_decision

    item = plan.item_by_id(node_id)
    if item is None:
        return []
    ancestor_ids: list[str] = []
    current = item
    while current.parent_id:
        ancestor_ids.append(current.parent_id)
        parent = plan.item_by_id(current.parent_id)
        if parent is None:
            break
        current = parent
    decisions_dir = render_decisions_dir(output_dir)
    if not decisions_dir.is_dir():
        return []
    resolved: list[str] = []
    for ancestor_id in ancestor_ids:
        for phase in (RenderNodePhase.RENDER,):
            path = decisions_dir / ancestor_id / phase.value / "0001.yaml"
            if path.is_file():
                decision = load_render_decision(path)
                resolved.append(decision.decision_id)
            else:
                resolved.append(decision_id_for(ancestor_id, phase, 1))
    return resolved


def _unresolved_deferred(coordinator: RenderCoordinator) -> list[str]:
    from top_down_planning.persistence import load_phase_completion, load_render_decision

    decisions_dir = render_decisions_dir(coordinator.output_dir)
    if not decisions_dir.is_dir():
        return []

    decisions = []
    for path in decisions_dir.rglob("*.yaml"):
        decisions.append(load_render_decision(path))

    phase_completions = []
    phases_dir = render_phases_dir(coordinator.output_dir)
    if phases_dir.is_dir():
        for completion_path in phases_dir.rglob("completion-*.yaml"):
            phase_completions.append(load_phase_completion(completion_path))

    return all_deferred_resolved(decisions, phase_completions=phase_completions)


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
    output_dir: Path | None = None,
) -> list[str] | None:
    if render_state is None or render_state.stage != RenderStage.COMPLETE:
        return None
    if not run_state.generated_artifacts:
        return None
    absolute: list[str] = []
    for relative in run_state.generated_artifacts:
        path = workspace / relative
        if not path.is_file():
            return None
        absolute.append(str(path))
    if output_dir is not None and render_state.deliverable_output_digest:
        ledger = load_ownership_ledger(output_dir)
        if ledger is None:
            return None
        try:
            current = collect_deliverable_output_from_ledger(workspace, ledger)
        except ValueError:
            return None
        if current.digest != render_state.deliverable_output_digest:
            return None
    return absolute
