"""Checkpointed specialist review and disposition orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from top_down_planning.console_renderer import ConsoleRenderer
from top_down_planning.cursor_client import CursorClient
from top_down_planning.digest import compute_plan_digest
from top_down_planning.errors import CursorSessionError, PlanningToolError, UserInterrupted
from top_down_planning.input_loader import LoadedInput, LoadedOutputGoal, LoadedStopHint
from top_down_planning.models import (
    CheckpointFinding,
    FindingDispositionRecord,
    PlanState,
    PlanningState,
    ReviewCheckpoint,
    ReviewConfig,
    ReviewerRole,
    RunState,
    SessionStrategy,
    SpecialistReviewResult,
)
from top_down_planning.orchestration_validation import orchestration_errors
from top_down_planning.persistence import reviews_dir, write_json
from top_down_planning.planning_state import (
    merge_planning_state_update,
    unresolved_finding_ids,
)
from top_down_planning.recovery import backup_canonical_plan, restore_canonical_plan
from top_down_planning.review_prompts import build_specialist_review_prompt
from top_down_planning.review_tool import (
    ReviewToolError,
    build_review_session_env,
    load_review_result,
    reset_review_result,
    resolve_review_tool_command,
)
from top_down_planning.review_validator import validate_specialist_review
from top_down_planning.session_strategy import checkpoint_enabled
from top_down_planning.stream_events import StreamEmitter


@dataclass
class CheckpointFlowDeps:
    workspace_root: Path
    output_dir: Path
    loaded: LoadedInput
    output_goal: LoadedOutputGoal
    stop_hint: LoadedStopHint | None
    embed_threshold: int
    client: CursorClient
    renderer: ConsoleRenderer
    stream: StreamEmitter
    audit: bool
    review: ReviewConfig
    strategy: SessionStrategy
    resolve_review_context: callable
    resolve_review_model: callable
    run_primary_disposition: callable


def roles_for_checkpoint(checkpoint: ReviewCheckpoint) -> list[ReviewerRole]:
    if checkpoint == ReviewCheckpoint.INITIAL_STRUCTURE:
        return [ReviewerRole.COVERAGE_BOUNDARY]
    if checkpoint == ReviewCheckpoint.ALL_BRANCHES_ACTIONABLE:
        return [
            ReviewerRole.DEPENDENCY_SEQUENCING,
            ReviewerRole.EXECUTABILITY_EVIDENCE,
        ]
    if checkpoint == ReviewCheckpoint.FINAL_CANDIDATE:
        return [ReviewerRole.ADVERSARIAL]
    return []


def specialist_review_result_path(
    output_dir: Path,
    *,
    role: ReviewerRole,
    plan_digest: str,
) -> Path:
    return reviews_dir(output_dir) / f"{role.value}-{plan_digest}.json"


async def run_checkpoint_reviews(
    deps: CheckpointFlowDeps,
    *,
    plan: PlanState,
    planning_state: PlanningState,
    run_state: RunState,
    checkpoint: ReviewCheckpoint,
) -> tuple[PlanState, PlanningState, list[CheckpointFinding]]:
    if not checkpoint_enabled(deps.strategy, checkpoint):
        return plan, planning_state, []
    findings: list[CheckpointFinding] = []
    plan_digest = compute_plan_digest(plan)
    for role in roles_for_checkpoint(checkpoint):
        result = await _ensure_specialist_review(
            deps,
            plan=plan,
            run_state=run_state,
            plan_digest=plan_digest,
            role=role,
            checkpoint=checkpoint,
        )
        if result is None:
            raise PlanningToolError(f"{role.value} review failed")
        findings.extend(result.findings)
        run_state.orchestration_metrics.reviewer_session_count += 1
        run_state.orchestration_metrics.findings_by_reviewer[role.value] = (
            run_state.orchestration_metrics.findings_by_reviewer.get(role.value, 0)
            + len(result.findings)
        )
    if not findings:
        return plan, planning_state, []
    updated_state = planning_state.model_copy(deep=True)
    from top_down_planning.models import PlanningStateUpdate

    updated_state = merge_planning_state_update(
        updated_state,
        PlanningStateUpdate(review_findings=findings),
    )
    plan, updated_state = await deps.run_primary_disposition(
        plan=plan,
        planning_state=updated_state,
        findings=findings,
        checkpoint=checkpoint,
        run_state=run_state,
    )
    return plan, updated_state, findings


async def _ensure_specialist_review(
    deps: CheckpointFlowDeps,
    *,
    plan: PlanState,
    run_state: RunState,
    plan_digest: str,
    role: ReviewerRole,
    checkpoint: ReviewCheckpoint,
) -> SpecialistReviewResult | None:
    result_path = specialist_review_result_path(
        deps.output_dir,
        role=role,
        plan_digest=plan_digest,
    )
    cached = _load_cached_specialist_review(result_path, plan_digest, plan=plan, role=role)
    if cached is not None:
        return cached

    deps.stream.emit(
        "review.checkpoint.started",
        reviewer_role=role.value,
        checkpoint=checkpoint.value,
        plan_digest=plan_digest,
    )
    prompt = build_specialist_review_prompt(
        loaded_input=deps.loaded,
        workspace=deps.workspace_root,
        output_goal=deps.output_goal,
        stop_hint=deps.stop_hint,
        plan=plan,
        plan_digest=plan_digest,
        embed_threshold=deps.embed_threshold,
        reviewer_role=role,
        checkpoint=checkpoint,
        review_tool_command=resolve_review_tool_command(),
        agent_context=deps.resolve_review_context(),
    )
    return await _run_specialist_review_session(
        deps,
        plan=plan,
        run_state=run_state,
        plan_digest=plan_digest,
        role=role,
        checkpoint=checkpoint,
        prompt=prompt,
        result_path=result_path,
    )


def load_specialist_review(
    output_dir: Path,
    *,
    plan_digest: str,
    role: ReviewerRole,
    plan: PlanState | None = None,
) -> SpecialistReviewResult | None:
    path = specialist_review_result_path(
        output_dir,
        role=role,
        plan_digest=plan_digest,
    )
    if plan is None:
        from top_down_planning.persistence import load_plan

        plan = load_plan(output_dir)
    if plan is None:
        return None
    return _load_cached_specialist_review(path, plan_digest, plan=plan, role=role)


def _load_cached_specialist_review(
    path: Path,
    plan_digest: str,
    *,
    plan: PlanState,
    role: ReviewerRole,
) -> SpecialistReviewResult | None:
    if not path.is_file():
        return None
    try:
        result = load_review_result(path, stage="specialist_review")
    except ReviewToolError:
        return None
    if not isinstance(result, SpecialistReviewResult):
        return None
    if result.plan_digest != plan_digest or result.reviewer_role != role:
        return None
    errors = validate_specialist_review(result, plan=plan, expected_digest=plan_digest)
    if errors:
        return None
    return result


async def _run_specialist_review_session(
    deps: CheckpointFlowDeps,
    *,
    plan: PlanState,
    run_state: RunState,
    plan_digest: str,
    role: ReviewerRole,
    checkpoint: ReviewCheckpoint,
    prompt: str,
    result_path: Path,
) -> SpecialistReviewResult | None:
    reviews_dir_path = result_path.parent
    reviews_dir_path.mkdir(parents=True, exist_ok=True)
    prefix = reviews_dir_path / f"{role.value}-{checkpoint.value}"
    prompt_path = Path(f"{prefix}-request-prompt.md")
    events_path = Path(f"{prefix}-agent.ndjson")
    log_path = Path(f"{prefix}-agent.log")
    prompt_path.write_text(prompt, encoding="utf-8")
    reset_review_result(result_path)

    session_env = build_review_session_env(
        result_path=result_path,
        stage="specialist_review",
        review_tool_command=resolve_review_tool_command(),
    )
    limits = run_state.limits
    plan_backup = backup_canonical_plan(deps.output_dir)
    min_plan_items = len(plan.plan)

    for attempt in range(1, deps.review.max_retries + 1):
        try:
            await deps.client.run_session(
                workspace=deps.workspace_root,
                prompt=prompt,
                prompt_path=prompt_path,
                timeout_seconds=limits.session_timeout_seconds,
                events_path=events_path if deps.audit else None,
                log_path=log_path if deps.audit else None,
                renderer=deps.renderer,
                session_mode="agent",
                extra_env=session_env,
                model=deps.resolve_review_model(),
            )
        except UserInterrupted:
            raise
        except CursorSessionError:
            if attempt >= deps.review.max_retries:
                return None
            continue
        finally:
            restore_canonical_plan(deps.output_dir, plan_backup, min_items=min_plan_items)

        try:
            result = load_review_result(result_path, stage="specialist_review")
        except ReviewToolError:
            if attempt >= deps.review.max_retries:
                return None
            continue
        if not isinstance(result, SpecialistReviewResult):
            if attempt >= deps.review.max_retries:
                return None
            continue
        errors = validate_specialist_review(
            result,
            plan=plan,
            expected_digest=plan_digest,
        )
        if errors:
            reset_review_result(result_path)
            if attempt >= deps.review.max_retries:
                return None
            continue
        if deps.audit:
            write_json(result_path, result.model_dump(mode="json"))
        deps.stream.emit(
            "review.checkpoint.completed",
            reviewer_role=role.value,
            checkpoint=checkpoint.value,
            decision=result.decision.value,
            findings=len(result.findings),
        )
        return result
    return None


def disposition_complete(planning_state: PlanningState) -> bool:
    return not unresolved_finding_ids(planning_state)


def record_dispositions(
    planning_state: PlanningState,
    records: list[FindingDispositionRecord],
) -> PlanningState:
    from top_down_planning.models import PlanningStateUpdate

    return merge_planning_state_update(
        planning_state,
        PlanningStateUpdate(finding_dispositions=records),
    )
