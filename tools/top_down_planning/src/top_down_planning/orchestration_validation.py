"""Deterministic orchestration validation gates."""

from __future__ import annotations

from top_down_planning.completeness import structural_errors
from top_down_planning.models import DecompositionStatus, PlanState, PlanningState
from top_down_planning.planning_state import unresolved_finding_ids
from top_down_planning.render_brief import actionable_leaf_items


def orchestration_errors(
    plan: PlanState,
    *,
    planning_state: PlanningState,
    output_goal_text: str,
) -> list[str]:
    errors = list(structural_errors(plan))
    errors.extend(_unique_id_errors(plan))
    errors.extend(_actionable_leaf_errors(plan))
    errors.extend(_coverage_errors(plan, planning_state, output_goal_text))
    errors.extend(_finding_errors(planning_state))
    return errors


def _unique_id_errors(plan: PlanState) -> list[str]:
    ids = [item.id for item in plan.plan]
    if len(ids) != len(set(ids)):
        return ["Plan contains duplicate item ids"]
    return []


def _actionable_leaf_errors(plan: PlanState) -> list[str]:
    errors: list[str] = []
    for item in actionable_leaf_items(plan):
        if not item.expected_outputs:
            errors.append(f"{item.id} actionable leaf missing expected_outputs")
        if not item.acceptance_criteria:
            errors.append(f"{item.id} actionable leaf missing acceptance_criteria")
        vague = [
            criterion
            for criterion in item.acceptance_criteria
            if len(criterion.strip()) < 8
        ]
        if vague:
            errors.append(f"{item.id} has vague acceptance criteria")
        if item.decomposition_status == DecompositionStatus.BLOCKED and not item.blocked_reason:
            errors.append(f"{item.id} blocked leaf missing blocked_reason")
    return errors


def _coverage_errors(
    plan: PlanState,
    planning_state: PlanningState,
    output_goal_text: str,
) -> list[str]:
    errors: list[str] = []
    if planning_state.coverage_map:
        covered = {branch for mapping in planning_state.coverage_map for branch in mapping.branch_ids}
        plan_ids = {item.id for item in plan.plan}
        for branch_id in covered:
            if branch_id not in plan_ids:
                errors.append(f"coverage_map references unknown branch {branch_id}")
    elif output_goal_text.strip():
        # Soft requirement: encourage explicit coverage mapping in full mode.
        pass
    # Every branch should map to something when coverage map exists
    if planning_state.coverage_map:
        mapped_branches = {
            branch
            for mapping in planning_state.coverage_map
            for branch in mapping.branch_ids
        }
        for item in plan.plan:
            if item.parent_id is None and item.id not in mapped_branches and item.decomposition_status not in {
                DecompositionStatus.OUT_OF_SCOPE,
            }:
                errors.append(
                    f"{item.id} top-level branch is not mapped in coverage_map"
                )
    return errors


def _finding_errors(planning_state: PlanningState) -> list[str]:
    unresolved = unresolved_finding_ids(planning_state)
    if unresolved:
        return [
            "Unresolved reviewer findings remain: " + ", ".join(sorted(unresolved))
        ]
    return []
