"""Per-batch review sessions during cumulative render authoring."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from top_down_planning.console_renderer import ConsoleRenderer
from top_down_planning.cursor_client import CursorClient
from top_down_planning.errors import CursorSessionError, UserInterrupted
from top_down_planning.input_loader import LoadedOutputGoal
from top_down_planning.models import (
    RenderBatchItem,
    RenderBatchReviewDecision,
    RenderBatchReviewResult,
    ReviewFindingSeverity,
)
from top_down_planning.persistence import batch_review_result_path, write_json
from top_down_planning.prompts import build_render_batch_review_prompt
from top_down_planning.render_deliverables import DeliverableOutput
from top_down_planning.review_tool import (
    ReviewToolError,
    build_review_session_env,
    load_review_result,
    reset_review_result,
)


@dataclass
class RenderBatchReviewDeps:
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


def validate_render_batch_review(result: RenderBatchReviewResult) -> list[str]:
    errors: list[str] = []
    blocking_or_major = [
        finding
        for finding in result.findings
        if finding.severity
        in {ReviewFindingSeverity.BLOCKING, ReviewFindingSeverity.MAJOR}
    ]
    if result.decision == RenderBatchReviewDecision.APPROVE and blocking_or_major:
        errors.append("approve decision cannot contain blocking or major findings")
    if result.decision == RenderBatchReviewDecision.NEEDS_REVISION and not result.findings:
        errors.append("needs_revision must include findings")
    if result.decision == RenderBatchReviewDecision.BLOCKED and not result.summary.strip():
        errors.append("blocked decision must include a summary")
    return errors


async def run_render_batch_review(
    deps: RenderBatchReviewDeps,
    *,
    batch: RenderBatchItem,
    plan_digest: str,
    schedule_digest: str,
    deliverable: DeliverableOutput,
    max_retries: int,
) -> RenderBatchReviewResult | None:
    result_path = batch_review_result_path(deps.output_dir, batch.batch_index)
    reset_review_result(result_path)

    prompt = build_render_batch_review_prompt(
        output_dir=deps.output_dir,
        workspace=deps.workspace_root,
        output_goal=deps.output_goal,
        plan_digest=plan_digest,
        schedule_digest=schedule_digest,
        batch_index=batch.batch_index,
        batch_item_ids=batch.item_ids,
        deliverable_digest=deliverable.digest,
        deliverable_paths=sorted(deliverable.files.keys()),
        output_goal_digest=deps.output_goal.digest,
        embed_threshold=deps.embed_threshold,
        agent_context=deps.resolve_review_context(),
    )

    review_env = build_review_session_env(
        result_path=result_path,
        stage="render_batch_review",  # type: ignore[arg-type]
    )

    attempt_prefix = (
        deps.output_dir
        / ".planning-output"
        / "render"
        / "batches"
        / f"{batch.batch_index:03d}"
        / "review"
    )
    prompt_path = attempt_prefix.with_name(attempt_prefix.name + "-request-prompt.md")
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt, encoding="utf-8")

    for attempt in range(1, max_retries + 1):
        try:
            await deps.client.run_session(
                workspace=deps.workspace_root,
                prompt=prompt,
                prompt_path=prompt_path,
                timeout_seconds=deps.session_timeout_seconds,
                events_path=attempt_prefix / f"agent-{attempt:03d}.ndjson"
                if deps.audit
                else None,
                log_path=attempt_prefix / f"agent-{attempt:03d}.log"
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
                deps.renderer.warning(f"Batch review session failed: {exc}")
                return None
            continue

        try:
            raw = load_review_result(result_path, stage="render_batch_review")
        except ReviewToolError as exc:
            if attempt >= max_retries:
                deps.renderer.warning(f"Batch review result invalid: {exc}")
                return None
            continue

        if not isinstance(raw, RenderBatchReviewResult):
            if attempt >= max_retries:
                return None
            continue

        result = raw
        if result.batch_index != batch.batch_index:
            return None
        if result.plan_digest != plan_digest:
            return None
        if result.output_goal_digest != deps.output_goal.digest:
            return None
        if result.schedule_digest != schedule_digest:
            return None
        if result.deliverable_output_digest != deliverable.digest:
            return None

        validation_errors = validate_render_batch_review(result)
        if validation_errors:
            if attempt >= max_retries:
                return None
            continue

        write_json(result_path, result.model_dump(mode="json"))
        return result

    return None
