"""Post-decomposition review, revision, and confirmation flow."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

from top_down_planning.completeness import (
    child_limit_blocked_summary,
    compute_final_status,
    has_child_limit_blocked_leaves,
    is_plan_complete,
    structural_errors,
)
from top_down_planning.console_renderer import ConsoleRenderer
from top_down_planning.cursor_client import CursorClient
from top_down_planning.digest import compute_plan_digest
from top_down_planning.errors import CursorSessionError, PlanningToolError, UserInterrupted
from top_down_planning.input_loader import LoadedInput, LoadedOutputGoal, LoadedStopHint
from top_down_planning.models import (
    ConfirmationDecision,
    FinalConfirmationResult,
    FinalStatus,
    PlanState,
    ReviewConfig,
    ReviewDecision,
    ReviewStage,
    ReviewState,
    ReviewStatus,
    RunState,
    WholePlanReviewResult,
)
from top_down_planning.persistence import (
    final_confirmation_result_path,
    load_review_state,
    record_history,
    save_plan,
    save_review_state,
    save_run_state,
    update_final_status,
    update_review_status,
    whole_plan_review_result_path,
    write_json,
)
from top_down_planning.recovery import backup_canonical_plan, restore_canonical_plan
from top_down_planning.review_prompts import (
    build_final_confirmation_prompt,
    build_whole_plan_review_prompt,
)
from top_down_planning.review_tool import (
    ReviewToolError,
    build_review_session_env,
    load_review_result,
    reset_review_result,
    resolve_review_tool_command,
)
from top_down_planning.review_validator import (
    validate_final_confirmation,
    validate_whole_plan_review,
)
from top_down_planning.revision import (
    reopen_branch,
    revision_targets_from_findings,
    validate_reopen_branch,
)
from top_down_planning.stream_events import StreamEmitter


@dataclass
class ReviewFlowDeps:
    workspace_root: Path
    output_dir: Path
    loaded: LoadedInput
    output_goal: LoadedOutputGoal
    stop_hint: LoadedStopHint | None
    embed_threshold: int
    review: ReviewConfig
    client: CursorClient
    renderer: ConsoleRenderer
    stream: StreamEmitter
    audit: bool
    resolve_review_context: callable
    resolve_review_model: callable
    run_planning_loop: callable


async def run_post_decomposition_flow(
    deps: ReviewFlowDeps,
    *,
    plan: PlanState,
    run_state: RunState,
) -> tuple[PlanState, RunState, bool]:
    """Return (plan, run_state, should_render)."""
    output_dir = deps.output_dir
    limits = run_state.limits

    if has_child_limit_blocked_leaves(plan):
        summary = child_limit_blocked_summary(
            plan,
            max_children_per_expansion=limits.max_children_per_expansion,
        ) or "Planning blocked by child-count constraint conflict."
        update_final_status(plan, FinalStatus.INCOMPLETE_BLOCKED, summary)
        update_review_status(plan, ReviewStatus.BLOCKED)
        save_plan(output_dir, plan)
        save_run_state(output_dir, run_state)
        return plan, run_state, False

    status = compute_final_status(plan)
    if status != FinalStatus.COMPLETE:
        summary = plan.result.summary or "Planning finished with remaining incomplete items."
        update_final_status(plan, status, summary)
        update_review_status(plan, ReviewStatus.PENDING)
        save_plan(output_dir, plan)
        save_run_state(output_dir, run_state)
        return plan, run_state, False

    if not deps.review.enabled:
        update_final_status(plan, FinalStatus.COMPLETE, plan.result.summary)
        update_review_status(plan, ReviewStatus.SKIPPED)
        save_plan(output_dir, plan)
        save_run_state(output_dir, run_state)
        return plan, run_state, True

    review_state = load_review_state(output_dir) or ReviewState()
    plan_digest = compute_plan_digest(plan)
    if review_state.plan_digest and review_state.plan_digest != plan_digest:
        _invalidate_review_artifacts(output_dir)
        review_state = ReviewState()

    review_state.plan_digest = plan_digest
    save_review_state(output_dir, review_state)

    revision_budget = deps.review.max_revision_cycles
    revision_cycles_used = 0

    while True:
        review_state.stage = ReviewStage.WHOLE_PLAN_REVIEW
        save_review_state(output_dir, review_state)

        whole_result = await _ensure_whole_plan_review(deps, plan, run_state, plan_digest)
        if whole_result is None:
            update_review_status(plan, ReviewStatus.BLOCKED)
            update_final_status(
                plan,
                FinalStatus.INCOMPLETE_BLOCKED,
                "Whole-plan review failed.",
            )
            save_plan(output_dir, plan)
            save_run_state(output_dir, run_state)
            return plan, run_state, False

        review_state.whole_plan_decision = whole_result.decision
        save_review_state(output_dir, review_state)

        if whole_result.decision == ReviewDecision.BLOCKED:
            deps.stream.emit("review.blocked", summary=whole_result.summary)
            update_review_status(plan, ReviewStatus.BLOCKED)
            update_final_status(plan, FinalStatus.INCOMPLETE_BLOCKED, whole_result.summary)
            review_state.stage = ReviewStage.BLOCKED
            save_review_state(output_dir, review_state)
            save_plan(output_dir, plan)
            save_run_state(output_dir, run_state)
            return plan, run_state, False

        if whole_result.decision == ReviewDecision.NEEDS_REVISION:
            deps.stream.emit("review.needs_revision", summary=whole_result.summary)
            if revision_cycles_used >= revision_budget:
                update_review_status(plan, ReviewStatus.NEEDS_REVISION)
                update_final_status(
                    plan,
                    FinalStatus.INCOMPLETE_BLOCKED,
                    "Review requested revision but revision budget is exhausted.",
                )
                review_state.stage = ReviewStage.BLOCKED
                save_review_state(output_dir, review_state)
                save_plan(output_dir, plan)
                save_run_state(output_dir, run_state)
                return plan, run_state, False

            revision_cycles_used += 1
            review_state.revision_cycle = revision_cycles_used
            review_state.stage = ReviewStage.REVISION
            save_review_state(output_dir, review_state)
            deps.stream.emit(
                "revision.started",
                revision_cycle=revision_cycles_used,
            )
            plan = _apply_targeted_revision(
                deps,
                plan=plan,
                run_state=run_state,
                findings=whole_result.findings,
                revision_cycle=revision_cycles_used,
            )
            _invalidate_review_artifacts(output_dir)
            review_state.whole_plan_decision = None
            review_state.final_confirmation_decision = None
            save_review_state(output_dir, review_state)

            plan, run_state = await deps.run_planning_loop(plan, run_state)
            if not is_plan_complete(plan) or structural_errors(plan):
                update_review_status(plan, ReviewStatus.NEEDS_REVISION)
                update_final_status(
                    plan,
                    FinalStatus.INCOMPLETE_BLOCKED,
                    "Revision replanning did not reach a structurally complete plan.",
                )
                save_plan(output_dir, plan)
                save_run_state(output_dir, run_state)
                return plan, run_state, False
            if has_child_limit_blocked_leaves(plan):
                summary = child_limit_blocked_summary(
                    plan,
                    max_children_per_expansion=limits.max_children_per_expansion,
                ) or "Planning blocked by child-count constraint conflict."
                update_review_status(plan, ReviewStatus.BLOCKED)
                update_final_status(plan, FinalStatus.INCOMPLETE_BLOCKED, summary)
                review_state.stage = ReviewStage.BLOCKED
                save_review_state(output_dir, review_state)
                save_plan(output_dir, plan)
                save_run_state(output_dir, run_state)
                return plan, run_state, False
            plan_digest = compute_plan_digest(plan)
            review_state.plan_digest = plan_digest
            save_review_state(output_dir, review_state)
            continue

        update_review_status(plan, ReviewStatus.APPROVED)
        deps.stream.emit("review.completed", decision=whole_result.decision.value)
        break

    review_state.stage = ReviewStage.FINAL_CONFIRMATION
    save_review_state(output_dir, review_state)

    confirmation = await _ensure_final_confirmation(deps, plan, run_state, plan_digest)
    if confirmation is None:
        update_review_status(plan, ReviewStatus.BLOCKED)
        update_final_status(
            plan,
            FinalStatus.INCOMPLETE_BLOCKED,
            "Final confirmation failed.",
        )
        save_plan(output_dir, plan)
        save_run_state(output_dir, run_state)
        return plan, run_state, False

    review_state.final_confirmation_decision = confirmation.decision
    save_review_state(output_dir, review_state)

    if confirmation.decision == ConfirmationDecision.CONFIRMED:
        deps.stream.emit("confirmation.confirmed", summary=confirmation.summary)
        update_review_status(plan, ReviewStatus.CONFIRMED)
        update_final_status(
            plan,
            FinalStatus.COMPLETE,
            confirmation.summary or "Planning and review completed successfully.",
        )
        review_state.stage = ReviewStage.RENDERING
        save_review_state(output_dir, review_state)
        save_plan(output_dir, plan)
        save_run_state(output_dir, run_state)
        return plan, run_state, True

    if confirmation.decision == ConfirmationDecision.NEEDS_REVISION:
        deps.stream.emit("confirmation.needs_revision", summary=confirmation.summary)
        update_review_status(plan, ReviewStatus.NEEDS_REVISION)
        update_final_status(
            plan,
            FinalStatus.INCOMPLETE_BLOCKED,
            confirmation.summary or "Final confirmation requested revision.",
        )
        review_state.stage = ReviewStage.BLOCKED
        save_review_state(output_dir, review_state)
        save_plan(output_dir, plan)
        save_run_state(output_dir, run_state)
        return plan, run_state, False

    deps.stream.emit("confirmation.blocked", summary=confirmation.summary)
    update_review_status(plan, ReviewStatus.BLOCKED)
    update_final_status(plan, FinalStatus.INCOMPLETE_BLOCKED, confirmation.summary)
    review_state.stage = ReviewStage.BLOCKED
    save_review_state(output_dir, review_state)
    save_plan(output_dir, plan)
    save_run_state(output_dir, run_state)
    return plan, run_state, False


def _invalidate_review_artifacts(output_dir: Path) -> None:
    for path in (
        whole_plan_review_result_path(output_dir),
        final_confirmation_result_path(output_dir),
    ):
        reset_review_result(path)


def _apply_targeted_revision(
    deps: ReviewFlowDeps,
    *,
    plan: PlanState,
    run_state: RunState,
    findings,
    revision_cycle: int,
) -> PlanState:
    targets = revision_targets_from_findings(plan, findings)
    if not targets:
        raise PlanningToolError("Revision requested but no affected node ids were provided")

    updated = copy.deepcopy(plan)
    for node_id in targets:
        errors = validate_reopen_branch(updated, node_id)
        if errors:
            raise PlanningToolError("; ".join(errors))
        updated = reopen_branch(updated, node_id)

    save_plan(deps.output_dir, updated)
    record_history(
        deps.output_dir,
        run_state,
        event="revision_applied",
        revision_cycle=revision_cycle,
        reopened_nodes=targets,
    )
    deps.stream.emit("revision.applied", reopened_nodes=targets, revision_cycle=revision_cycle)
    write_json(
        Path(deps.output_dir / ".planning-output" / "reviews" / f"revision-{revision_cycle:03d}.json"),
        {"reopened_nodes": targets},
    )
    update_final_status(updated, FinalStatus.PLANNING, "Targeted revision reopened branches.")
    update_review_status(updated, ReviewStatus.PENDING)
    return updated


async def _ensure_whole_plan_review(
    deps: ReviewFlowDeps,
    plan: PlanState,
    run_state: RunState,
    plan_digest: str,
) -> WholePlanReviewResult | None:
    result_path = whole_plan_review_result_path(deps.output_dir)
    cached = _load_cached_whole_plan_review(result_path, plan_digest, plan=plan)
    if cached is not None:
        return cached

    deps.stream.emit("review.started", plan_digest=plan_digest)
    return await _run_review_session(
        deps,
        plan=plan,
        run_state=run_state,
        plan_digest=plan_digest,
        stage="whole_plan_review",
        prompt=build_whole_plan_review_prompt(
            loaded_input=deps.loaded,
            workspace=deps.workspace_root,
            output_goal=deps.output_goal,
            stop_hint=deps.stop_hint,
            plan=plan,
            plan_digest=plan_digest,
            embed_threshold=deps.embed_threshold,
            review_tool_command=resolve_review_tool_command(),
            agent_context=deps.resolve_review_context(),
        ),
        result_path=result_path,
        validate=lambda result: validate_whole_plan_review(
            result,
            plan=plan,
            expected_digest=plan_digest,
        ),
    )


async def _ensure_final_confirmation(
    deps: ReviewFlowDeps,
    plan: PlanState,
    run_state: RunState,
    plan_digest: str,
) -> FinalConfirmationResult | None:
    result_path = final_confirmation_result_path(deps.output_dir)
    det_passed = not structural_errors(plan)
    cached = _load_cached_final_confirmation(
        result_path,
        plan_digest,
        plan=plan,
        deterministic_validation_passed=det_passed,
    )
    if cached is not None:
        return cached

    deps.stream.emit("confirmation.started", plan_digest=plan_digest)
    return await _run_review_session(
        deps,
        plan=plan,
        run_state=run_state,
        plan_digest=plan_digest,
        stage="final_confirmation",
        prompt=build_final_confirmation_prompt(
            loaded_input=deps.loaded,
            workspace=deps.workspace_root,
            output_goal=deps.output_goal,
            stop_hint=deps.stop_hint,
            plan=plan,
            plan_digest=plan_digest,
            embed_threshold=deps.embed_threshold,
            review_tool_command=resolve_review_tool_command(),
            agent_context=deps.resolve_review_context(),
        ),
        result_path=result_path,
        validate=lambda result: validate_final_confirmation(
            result,
            plan=plan,
            expected_digest=plan_digest,
            deterministic_validation_passed=det_passed,
        ),
    )


def _load_cached_whole_plan_review(
    path: Path,
    plan_digest: str,
    *,
    plan: PlanState,
) -> WholePlanReviewResult | None:
    if not path.is_file():
        return None
    try:
        result = load_review_result(path, stage="whole_plan_review")
    except ReviewToolError:
        return None
    if not isinstance(result, WholePlanReviewResult):
        return None
    if result.plan_digest != plan_digest:
        return None
    errors = validate_whole_plan_review(
        result,
        plan=plan,
        expected_digest=plan_digest,
    )
    if errors:
        return None
    return result


def _load_cached_final_confirmation(
    path: Path,
    plan_digest: str,
    *,
    plan: PlanState,
    deterministic_validation_passed: bool,
) -> FinalConfirmationResult | None:
    if not path.is_file():
        return None
    try:
        result = load_review_result(path, stage="final_confirmation")
    except ReviewToolError:
        return None
    if not isinstance(result, FinalConfirmationResult):
        return None
    if result.plan_digest != plan_digest:
        return None
    errors = validate_final_confirmation(
        result,
        plan=plan,
        expected_digest=plan_digest,
        deterministic_validation_passed=deterministic_validation_passed,
    )
    if errors:
        return None
    return result


async def _run_review_session(
    deps: ReviewFlowDeps,
    *,
    plan: PlanState,
    run_state: RunState,
    plan_digest: str,
    stage: str,
    prompt: str,
    result_path: Path,
    validate,
):
    reviews_dir = result_path.parent
    reviews_dir.mkdir(parents=True, exist_ok=True)
    stage_prefix = {
        "whole_plan_review": "whole-plan",
        "final_confirmation": "final-confirmation",
    }[stage]
    prefix = reviews_dir / stage_prefix
    prompt_path = Path(f"{prefix}-request-prompt.md")
    events_path = Path(f"{prefix}-agent.ndjson")
    log_path = Path(f"{prefix}-agent.log")
    prompt_path.write_text(prompt, encoding="utf-8")
    reset_review_result(result_path)

    review_tool_command = resolve_review_tool_command()
    session_env = build_review_session_env(
        result_path=result_path,
        stage=stage,  # type: ignore[arg-type]
        review_tool_command=review_tool_command,
    )
    limits = run_state.limits
    plan_backup = backup_canonical_plan(deps.output_dir)
    min_plan_items = len(plan.plan)

    validation_feedback: list[str] | None = None
    for attempt in range(1, deps.review.max_retries + 1):
        try:
            await deps.client.run_session(
                workspace=deps.workspace_root,
                prompt=prompt,
                prompt_path=prompt_path,
                timeout_seconds=limits.session_timeout_seconds,
                events_path=events_path if deps.audit else None,
                log_path=log_path if deps.audit else None,
                renderer=ConsoleRenderer.with_file_logging(deps.renderer, log_path)
                if deps.audit
                else deps.renderer,
                session_mode="agent",
                extra_env=session_env,
                model=deps.resolve_review_model(),
            )
        except UserInterrupted:
            raise
        except CursorSessionError as exc:
            if attempt >= deps.review.max_retries:
                deps.renderer.warning(f"{stage} session failed: {exc}")
                return None
            continue
        finally:
            if restore_canonical_plan(
                deps.output_dir, plan_backup, min_items=min_plan_items
            ):
                deps.renderer.warning(
                    f"Restored plan.yaml after {stage} session modified canonical state"
                )

        try:
            result = load_review_result(result_path, stage=stage)  # type: ignore[arg-type]
        except ReviewToolError as exc:
            validation_feedback = [str(exc)]
            if attempt >= deps.review.max_retries:
                return None
            continue

        errors = validate(result)
        if errors:
            validation_feedback = errors
            reset_review_result(result_path)
            if attempt >= deps.review.max_retries:
                return None
            continue

        if deps.audit:
            write_json(result_path, result.model_dump(mode="json"))
        return result

    return None
