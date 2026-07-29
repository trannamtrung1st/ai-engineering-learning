"""Whole-output semantic review after final deliverables are written."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from top_down_planning.console_renderer import ConsoleRenderer
from top_down_planning.cursor_client import CursorClient
from top_down_planning.errors import CursorSessionError, UserInterrupted
from top_down_planning.input_loader import LoadedOutputGoal
from top_down_planning.models import (
    PlanState,
    RenderBatchSchedule,
    RenderOutputReviewDecision,
    RenderOutputReviewStatus,
    RenderedOutputReviewResult,
    ReviewFindingSeverity,
)
from top_down_planning.persistence import (
    rendered_output_review_result_path,
    write_json,
)
from top_down_planning.prompts import build_render_output_review_prompt
from top_down_planning.render_deliverables import DeliverableOutput
from top_down_planning.review_tool import (
    ReviewToolError,
    build_review_session_env,
    load_review_result,
    reset_review_result,
)


@dataclass
class RenderReviewDeps:
    workspace_root: Path
    output_dir: Path
    output_goal: LoadedOutputGoal
    embed_threshold: int
    client: CursorClient
    renderer: ConsoleRenderer
    audit: bool
    resolve_review_context: callable
    resolve_review_model: callable
    session_timeout_seconds: int = 600


def validate_render_output_review(
    result: RenderedOutputReviewResult,
    *,
    plan: PlanState | None = None,
    deliverable_paths: list[str] | None = None,
    schedule_batch_indices: list[int] | None = None,
) -> list[str]:
    errors: list[str] = []
    if not result.summary.strip():
        errors.append("Review summary must not be empty")
    blocking_or_major = [
        finding
        for finding in result.findings
        if finding.severity
        in {ReviewFindingSeverity.BLOCKING, ReviewFindingSeverity.MAJOR}
    ]
    if result.decision == RenderOutputReviewDecision.APPROVE and blocking_or_major:
        errors.append("approve decision cannot contain blocking or major findings")
    if result.decision == RenderOutputReviewDecision.NEEDS_REVISION and not (
        result.affected_batch_indices or result.affected_artifact_paths or result.findings
    ):
        errors.append(
            "needs_revision must identify affected batches, artifacts, or findings"
        )
    if result.decision == RenderOutputReviewDecision.BLOCKED and not result.summary.strip():
        errors.append("blocked decision must include a summary")

    valid_item_ids = {item.id for item in plan.plan} if plan is not None else None
    allowed_artifacts = set(deliverable_paths or [])
    allowed_batches = set(schedule_batch_indices or [])

    for index, finding in enumerate(result.findings, start=1):
        prefix = f"Finding {index}"
        if not finding.description.strip():
            errors.append(f"{prefix}: description must not be empty")
        for node_id in finding.plan_item_ids:
            if valid_item_ids is not None and node_id not in valid_item_ids:
                errors.append(f"{prefix}: unknown plan item id {node_id!r}")
        for artifact_path in finding.artifact_paths:
            if allowed_artifacts and artifact_path not in allowed_artifacts:
                errors.append(
                    f"{prefix}: artifact path {artifact_path!r} is not in scope"
                )

    for batch_index in result.affected_batch_indices:
        if allowed_batches and batch_index not in allowed_batches:
            errors.append(f"affected batch index {batch_index} is not in schedule scope")
    for artifact_path in result.affected_artifact_paths:
        if allowed_artifacts and artifact_path not in allowed_artifacts:
            errors.append(f"affected artifact path {artifact_path!r} is not in scope")

    return errors


async def run_render_output_review(
    deps: RenderReviewDeps,
    *,
    plan: PlanState,
    plan_digest: str,
    schedule: RenderBatchSchedule,
    schedule_digest: str,
    deliverable: DeliverableOutput,
    max_retries: int,
) -> RenderedOutputReviewResult | None:
    result_path = rendered_output_review_result_path(deps.output_dir)
    reset_review_result(result_path)

    prompt = build_render_output_review_prompt(
        output_dir=deps.output_dir,
        workspace=deps.workspace_root,
        output_goal=deps.output_goal,
        plan_digest=plan_digest,
        schedule_digest=schedule_digest,
        deliverable_digest=deliverable.digest,
        deliverable_paths=sorted(deliverable.files.keys()),
        output_goal_digest=schedule.output_goal_digest,
        embed_threshold=deps.embed_threshold,
        agent_context=deps.resolve_review_context(),
    )

    review_env = build_review_session_env(
        result_path=result_path,
        stage="rendered_output_review",  # type: ignore[arg-type]
    )

    attempt_prefix = deps.output_dir / ".planning-output" / "render" / "reviews" / "output-review"
    prompt_path = Path(str(attempt_prefix) + "-request-prompt.md")
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt, encoding="utf-8")

    for attempt in range(1, max_retries + 1):
        try:
            await deps.client.run_session(
                workspace=deps.workspace_root,
                prompt=prompt,
                prompt_path=prompt_path,
                timeout_seconds=deps.session_timeout_seconds,
                events_path=Path(str(attempt_prefix) + f"-{attempt:03d}-agent.ndjson")
                if deps.audit
                else None,
                log_path=Path(str(attempt_prefix) + f"-{attempt:03d}-agent.log")
                if deps.audit
                else None,
                renderer=deps.renderer,
                session_mode="agent",
                model=deps.resolve_review_model(),
                extra_env=review_env,
            )
        except UserInterrupted:
            raise
        except CursorSessionError as exc:
            if attempt >= max_retries:
                deps.renderer.warn(f"Output review session failed: {exc}")
                return None
            continue

        try:
            raw = load_review_result(result_path, stage="rendered_output_review")  # type: ignore[arg-type]
        except ReviewToolError as exc:
            if attempt >= max_retries:
                deps.renderer.warn(f"Output review result invalid: {exc}")
                return None
            continue

        if not isinstance(raw, RenderedOutputReviewResult):
            if attempt >= max_retries:
                return None
            continue

        result = raw
        digest_errors: list[str] = []
        if result.plan_digest != plan_digest:
            digest_errors.append(
                f"plan_digest mismatch: expected {plan_digest}, "
                f"got {result.plan_digest}"
            )
        if result.output_goal_digest != schedule.output_goal_digest:
            digest_errors.append(
                f"output_goal_digest mismatch: expected {schedule.output_goal_digest}, "
                f"got {result.output_goal_digest}"
            )
        if result.schedule_digest != schedule_digest:
            digest_errors.append(
                f"schedule_digest mismatch: expected {schedule_digest}, "
                f"got {result.schedule_digest}"
            )
        if result.deliverable_output_digest != deliverable.digest:
            digest_errors.append(
                f"deliverable_output_digest mismatch: expected {deliverable.digest}, "
                f"got {result.deliverable_output_digest}"
            )
        if digest_errors:
            if attempt >= max_retries:
                return None
            continue

        validation_errors = validate_render_output_review(
            result,
            plan=plan,
            deliverable_paths=sorted(deliverable.files.keys()),
            schedule_batch_indices=[
                batch.batch_index for batch in schedule.batches
            ],
        )
        if validation_errors:
            if attempt >= max_retries:
                return None
            continue

        write_json(result_path, result.model_dump(mode="json"))
        return result

    return None


def review_status_from_decision(
    decision: RenderOutputReviewDecision,
) -> RenderOutputReviewStatus:
    if decision == RenderOutputReviewDecision.APPROVE:
        return RenderOutputReviewStatus.APPROVED
    if decision == RenderOutputReviewDecision.NEEDS_REVISION:
        return RenderOutputReviewStatus.NEEDS_REVISION
    return RenderOutputReviewStatus.BLOCKED
