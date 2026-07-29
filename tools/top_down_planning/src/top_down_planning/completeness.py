"""Plan completeness and final status calculation."""

from __future__ import annotations

from top_down_planning.models import (
    DecompositionStatus,
    FinalStatus,
    PlanState,
    PlanningLimits,
    ReadinessStatus,
)
from top_down_planning.render_brief import actionable_leaf_items
from top_down_planning.scheduler import expandable_items
from top_down_planning.state_updates import detect_dependency_cycles


def is_leaf(plan: PlanState, item_id: str) -> bool:
    return not any(child.parent_id == item_id for child in plan.plan)


def count_by_status(plan: PlanState) -> dict[str, int]:
    counts = {
        "actionable": 0,
        "blocked": 0,
        "out_of_scope": 0,
        "needs_expansion": 0,
        "expanded": 0,
    }
    for item in plan.plan:
        if item.decomposition_status == DecompositionStatus.ACTIONABLE:
            counts["actionable"] += 1
        elif item.decomposition_status == DecompositionStatus.BLOCKED:
            counts["blocked"] += 1
        elif item.decomposition_status == DecompositionStatus.OUT_OF_SCOPE:
            counts["out_of_scope"] += 1
        elif item.decomposition_status == DecompositionStatus.NEEDS_EXPANSION:
            counts["needs_expansion"] += 1
        elif item.decomposition_status == DecompositionStatus.EXPANDED:
            counts["expanded"] += 1
    return counts


def leaf_actionable_count(plan: PlanState) -> int:
    return len(actionable_leaf_items(plan))


def structural_errors(plan: PlanState) -> list[str]:
    errors: list[str] = []
    ids = {item.id for item in plan.plan}
    for item in plan.plan:
        if item.parent_id is not None and item.parent_id not in ids:
            errors.append(f"{item.id} references missing parent {item.parent_id}")
        for dep in item.dependencies:
            if dep not in ids:
                errors.append(f"{item.id} references missing dependency {dep}")
        if item.decomposition_status == DecompositionStatus.EXPANDED and is_leaf(
            plan, item.id
        ):
            errors.append(f"{item.id} is expanded but has no children")
        if item.decomposition_status == DecompositionStatus.ACTIONABLE and not is_leaf(
            plan, item.id
        ):
            errors.append(f"{item.id} is actionable but is not a leaf")
    errors.extend(detect_dependency_cycles(plan))
    return errors


def is_plan_complete(plan: PlanState) -> bool:
    if expandable_items(plan):
        return False
    if structural_errors(plan):
        return False
    for item in plan.plan:
        if item.decomposition_status == DecompositionStatus.NEEDS_EXPANSION:
            return False
        if item.decomposition_status not in {
            DecompositionStatus.EXPANDED,
            DecompositionStatus.ACTIONABLE,
            DecompositionStatus.BLOCKED,
            DecompositionStatus.OUT_OF_SCOPE,
        }:
            return False
    return True


def compute_final_status(
    plan: PlanState,
    *,
    limit_reached: bool = False,
    failed: bool = False,
) -> FinalStatus:
    if failed:
        return FinalStatus.FAILED
    if is_plan_complete(plan):
        return FinalStatus.COMPLETE
    if limit_reached:
        return FinalStatus.INCOMPLETE_LIMIT_REACHED
    if expandable_items(plan) and any(
        item.decomposition_status == DecompositionStatus.BLOCKED for item in plan.plan
    ):
        return FinalStatus.INCOMPLETE_BLOCKED
    return FinalStatus.PLANNING


def limit_reached(
    *,
    iteration: int,
    limits: PlanningLimits,
) -> bool:
    return iteration >= limits.max_iterations
