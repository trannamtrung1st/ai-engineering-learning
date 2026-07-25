"""Precondition checks for render-only mode."""

from __future__ import annotations

from pathlib import Path

from top_down_planning.completeness import is_plan_complete, structural_errors
from top_down_planning.digest import compute_plan_digest
from top_down_planning.errors import PlanningToolError
from top_down_planning.input_loader import LoadedOutputGoal
from top_down_planning.models import (
    ConfirmationDecision,
    DecompositionStatus,
    FinalConfirmationResult,
    PlanState,
    ReviewDecision,
    ReviewStatus,
    WholePlanReviewResult,
)
from top_down_planning.persistence import (
    final_confirmation_result_path,
    load_plan,
    load_run_state,
    whole_plan_review_result_path,
)
from top_down_planning.review_validator import (
    validate_final_confirmation,
    validate_whole_plan_review,
)


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
        whole_path = whole_plan_review_result_path(output_dir)
        confirm_path = final_confirmation_result_path(output_dir)

        if not whole_path.is_file() or not confirm_path.is_file():
            raise PlanningToolError(
                "Render-only cannot proceed: semantic review artifacts are missing.\n"
                "No planning or rendering action was performed."
            )

        import json

        whole_result = WholePlanReviewResult.model_validate(
            json.loads(whole_path.read_text(encoding="utf-8"))
        )
        confirm_result = FinalConfirmationResult.model_validate(
            json.loads(confirm_path.read_text(encoding="utf-8"))
        )

        whole_errors = validate_whole_plan_review(
            whole_result,
            plan=plan,
            expected_digest=plan_digest,
        )
        if whole_errors:
            raise PlanningToolError(
                "Render-only cannot proceed: stale or invalid whole-plan review:\n"
                + "\n".join(f"  - {error}" for error in whole_errors)
                + "\nNo planning or rendering action was performed."
            )

        if whole_result.decision != ReviewDecision.APPROVE:
            raise PlanningToolError(
                "Render-only cannot proceed: whole-plan review is not approved.\n"
                "No planning or rendering action was performed."
            )

        confirm_errors = validate_final_confirmation(
            confirm_result,
            plan=plan,
            expected_digest=plan_digest,
            deterministic_validation_passed=True,
        )
        if confirm_errors:
            raise PlanningToolError(
                "Render-only cannot proceed: stale final confirmation:\n"
                + "\n".join(f"  - {error}" for error in confirm_errors)
                + "\nNo planning or rendering action was performed."
            )

        if confirm_result.decision != ConfirmationDecision.CONFIRMED:
            raise PlanningToolError(
                "Render-only cannot proceed: final confirmation is not confirmed.\n"
                "No planning or rendering action was performed."
            )

        if confirm_result.plan_digest != plan_digest:
            raise PlanningToolError(
                "Render-only cannot proceed: final confirmation references plan digest "
                f"{confirm_result.plan_digest}, but the current canonical plan digest is "
                f"{plan_digest}.\n\nThe planning output must be reviewed and confirmed "
                "again before rendering.\nNo planning or rendering action was performed."
            )

        blocking = [
            finding
            for finding in whole_result.findings + confirm_result.findings
            if finding.severity.value in {"blocking", "major"}
        ]
        if blocking:
            raise PlanningToolError(
                "Render-only cannot proceed: unresolved blocking or major findings remain.\n"
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
