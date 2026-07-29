"""Precondition checks for render-only mode."""

from __future__ import annotations

from pathlib import Path

from top_down_planning.checkpoint_flow import load_specialist_review, specialist_review_result_path
from top_down_planning.completeness import is_plan_complete, structural_errors
from top_down_planning.digest import compute_plan_digest
from top_down_planning.errors import PlanningToolError
from top_down_planning.input_loader import LoadedOutputGoal
from top_down_planning.models import (
    DecompositionStatus,
    PlanState,
    ReviewCheckpoint,
    ReviewDecision,
    ReviewStatus,
    ReviewerRole,
)
from top_down_planning.orchestration_validation import orchestration_errors
from top_down_planning.persistence import (
    load_plan,
    load_planning_state,
    load_run_state,
    planning_state_path,
)
from top_down_planning.planning_state import new_planning_state, unresolved_finding_ids
from top_down_planning.review_validator import validate_specialist_review
from top_down_planning.session_strategy import checkpoint_enabled


def validate_render_only_preconditions(
    output_dir: Path,
    *,
    output_goal: LoadedOutputGoal,
    goal_overridden: bool,
) -> tuple[PlanState, str]:
    """Return confirmed plan and plan digest, or raise PlanningToolError."""
    plan = load_plan(output_dir)
    if plan is None:
        raise PlanningToolError(
            "Render-only cannot proceed: canonical plan.yaml is missing.\n"
            "No planning or rendering action was performed."
        )

    run_state = load_run_state(output_dir)
    if run_state is None:
        raise PlanningToolError(
            "Render-only cannot proceed: run-state.json is missing.\n"
            "No planning or rendering action was performed."
        )

    needs_expansion = [
        item.id
        for item in plan.plan
        if item.decomposition_status == DecompositionStatus.NEEDS_EXPANSION
    ]
    if needs_expansion:
        raise PlanningToolError(
            "Render-only cannot proceed: plan items remain in needs_expansion: "
            f"{', '.join(needs_expansion)}.\n"
            "No planning or rendering action was performed."
        )

    struct_errors = structural_errors(plan)
    if struct_errors:
        raise PlanningToolError(
            "Render-only cannot proceed: invalid structural plan state:\n"
            + "\n".join(f"  - {error}" for error in struct_errors)
            + "\nNo planning or rendering action was performed."
        )

    if not is_plan_complete(plan):
        raise PlanningToolError(
            "Render-only cannot proceed: the canonical plan is not complete.\n"
            "No planning or rendering action was performed."
        )

    plan_digest = compute_plan_digest(plan)

    review_status = plan.result.review_status
    if review_status == ReviewStatus.SKIPPED:
        pass
    elif review_status == ReviewStatus.CONFIRMED:
        if not planning_state_path(output_dir).is_file():
            raise PlanningToolError(
                "Render-only cannot proceed: planning-state.yaml is missing.\n"
                "No planning or rendering action was performed."
            )

        planning_state = load_planning_state(output_dir) or new_planning_state()
        errors = orchestration_errors(
            plan,
            planning_state=planning_state,
            output_goal_text=output_goal.text,
        )
        if errors:
            raise PlanningToolError(
                "Render-only cannot proceed: orchestration validation failed:\n"
                + "\n".join(f"  - {error}" for error in errors)
                + "\nNo planning or rendering action was performed."
            )

        unresolved = unresolved_finding_ids(planning_state)
        if unresolved:
            raise PlanningToolError(
                "Render-only cannot proceed: unresolved reviewer findings remain: "
                f"{', '.join(sorted(unresolved))}.\n"
                "No planning or rendering action was performed."
            )

        strategy = run_state.session_strategy
        if (
            strategy.final_adversarial_review
            and checkpoint_enabled(strategy, ReviewCheckpoint.FINAL_CANDIDATE)
        ):
            adversarial = load_specialist_review(
                output_dir,
                plan_digest=plan_digest,
                role=ReviewerRole.ADVERSARIAL,
                plan=plan,
            )
            if adversarial is None:
                raise PlanningToolError(
                    "Render-only cannot proceed: final adversarial review artifact is missing.\n"
                    "No planning or rendering action was performed."
                )
            validation_errors = validate_specialist_review(
                adversarial,
                plan=plan,
                expected_digest=plan_digest,
            )
            if validation_errors:
                raise PlanningToolError(
                    "Render-only cannot proceed: stale or invalid adversarial review:\n"
                    + "\n".join(f"  - {error}" for error in validation_errors)
                    + "\nNo planning or rendering action was performed."
                )
            if adversarial.decision != ReviewDecision.APPROVE:
                raise PlanningToolError(
                    "Render-only cannot proceed: final adversarial review did not approve the plan.\n"
                    "No planning or rendering action was performed."
                )
            artifact_path = specialist_review_result_path(
                output_dir,
                role=ReviewerRole.ADVERSARIAL,
                plan_digest=plan_digest,
            )
            if not artifact_path.is_file():
                raise PlanningToolError(
                    "Render-only cannot proceed: adversarial review artifact file is missing.\n"
                    "No planning or rendering action was performed."
                )
    else:
        raise PlanningToolError(
            "Render-only cannot proceed: plan review status is "
            f"{review_status.value}; expected confirmed or skipped.\n"
            "No planning or rendering action was performed."
        )

    if not goal_overridden and run_state.output_goal_digest != output_goal.digest:
        raise PlanningToolError(
            "Render-only cannot proceed: output goal digest mismatch.\n"
            "Supply --output-goal or --output-goal-file to rerender with a revised goal.\n"
            "No planning or rendering action was performed."
        )

    return plan, plan_digest
