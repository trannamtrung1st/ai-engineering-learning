"""Post-decomposition finalization gate."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from top_down_planning.checkpoint_flow import load_specialist_review
from top_down_planning.completeness import compute_final_status
from top_down_planning.digest import compute_plan_digest
from top_down_planning.errors import PlanningToolError
from top_down_planning.input_loader import LoadedOutputGoal
from top_down_planning.models import (
    FinalStatus,
    PlanState,
    ReviewCheckpoint,
    ReviewConfig,
    ReviewDecision,
    ReviewerRole,
    ReviewStage,
    ReviewState,
    ReviewStatus,
    RunState,
    SessionStrategy,
)
from top_down_planning.orchestration_validation import orchestration_errors
from top_down_planning.persistence import (
    load_planning_state,
    load_review_state,
    save_plan,
    save_review_state,
    save_run_state,
    update_final_status,
    update_review_status,
)
from top_down_planning.planning_state import new_planning_state, unresolved_finding_ids
from top_down_planning.session_strategy import checkpoint_enabled
from top_down_planning.stream_events import StreamEmitter


@dataclass
class ReviewFlowDeps:
    output_dir: Path
    output_goal: LoadedOutputGoal
    review: ReviewConfig
    strategy: SessionStrategy
    stream: StreamEmitter


async def run_post_decomposition_flow(
    deps: ReviewFlowDeps,
    *,
    plan: PlanState,
    run_state: RunState,
) -> tuple[PlanState, RunState, bool]:
    """Return (plan, run_state, should_render)."""
    output_dir = deps.output_dir

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

    planning_state = load_planning_state(output_dir) or new_planning_state()
    plan_digest = compute_plan_digest(plan)
    errors = orchestration_errors(
        plan,
        planning_state=planning_state,
        output_goal_text=deps.output_goal.text,
    )
    if errors:
        update_review_status(plan, ReviewStatus.BLOCKED)
        update_final_status(
            plan,
            FinalStatus.INCOMPLETE_BLOCKED,
            "Deterministic orchestration validation failed.",
        )
        save_plan(output_dir, plan)
        save_run_state(output_dir, run_state)
        return plan, run_state, False

    unresolved = unresolved_finding_ids(planning_state)
    if unresolved:
        update_review_status(plan, ReviewStatus.BLOCKED)
        update_final_status(
            plan,
            FinalStatus.INCOMPLETE_BLOCKED,
            "Unresolved reviewer findings remain: " + ", ".join(sorted(unresolved)),
        )
        save_plan(output_dir, plan)
        save_run_state(output_dir, run_state)
        return plan, run_state, False

    if (
        deps.strategy.final_adversarial_review
        and checkpoint_enabled(deps.strategy, ReviewCheckpoint.FINAL_CANDIDATE)
    ):
        adversarial = load_specialist_review(
            output_dir,
            plan_digest=plan_digest,
            role=ReviewerRole.ADVERSARIAL,
        )
        if adversarial is None:
            raise PlanningToolError(
                "Final adversarial review artifact is missing for the current plan digest."
            )
        if adversarial.decision != ReviewDecision.APPROVE:
            update_review_status(plan, ReviewStatus.BLOCKED)
            update_final_status(
                plan,
                FinalStatus.INCOMPLETE_BLOCKED,
                adversarial.summary or "Final adversarial review did not approve the plan.",
            )
            save_plan(output_dir, plan)
            save_run_state(output_dir, run_state)
            return plan, run_state, False

    review_state = load_review_state(output_dir) or ReviewState()
    review_state.plan_digest = plan_digest
    review_state.stage = ReviewStage.COMPLETE
    if ReviewCheckpoint.FINAL_CANDIDATE.value not in review_state.completed_checkpoints:
        review_state.completed_checkpoints.append(ReviewCheckpoint.FINAL_CANDIDATE.value)
    save_review_state(output_dir, review_state)

    deps.stream.emit("review.completed", decision=ReviewDecision.APPROVE.value)
    update_review_status(plan, ReviewStatus.CONFIRMED)
    update_final_status(
        plan,
        FinalStatus.COMPLETE,
        "Planning, checkpoint reviews, and deterministic validation completed successfully.",
    )
    save_plan(output_dir, plan)
    save_run_state(output_dir, run_state)
    return plan, run_state, True
