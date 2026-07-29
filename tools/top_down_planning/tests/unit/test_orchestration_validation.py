from top_down_planning.models import (
    CoverageMapping,
    DecompositionStatus,
    PlanItem,
    PlanningState,
)
from top_down_planning.orchestration_validation import orchestration_errors
from top_down_planning.planning_state import new_planning_state
from tests.plan_factory import make_root_plan


def _expanded_plan_with_children() -> tuple:
    plan = make_root_plan(
        input_file="idea.md",
        output_goal="goal",
        input_digest="a",
        output_goal_digest="b",
    )
    root = plan.plan[0]
    root.decomposition_status = DecompositionStatus.EXPANDED
    root.title = "Root workstream"
    root.objective = "Coordinate child branches."
    plan.plan.append(
        PlanItem(
            id="item-002",
            parent_id="item-001",
            title="Branch A",
            objective="First branch.",
            depth=1,
            order=2,
            decomposition_status=DecompositionStatus.ACTIONABLE,
            expected_outputs=["Deliverable A"],
            acceptance_criteria=["Branch A is complete."],
        )
    )
    planning_state = new_planning_state()
    planning_state.coverage_map = [
        CoverageMapping(
            requirement="Branch A",
            branch_ids=["item-002"],
        )
    ]
    return plan, planning_state


def test_orchestration_validation_allows_unmapped_expanded_root() -> None:
    plan, planning_state = _expanded_plan_with_children()

    errors = orchestration_errors(
        plan,
        planning_state=planning_state,
        output_goal_text="Produce an actionable plan.",
    )

    assert not any("coverage_map" in error for error in errors)


def test_orchestration_validation_requires_mapped_actionable_root() -> None:
    plan, planning_state = _expanded_plan_with_children()
    plan.plan[0].decomposition_status = DecompositionStatus.ACTIONABLE
    plan.plan[0].expected_outputs = ["Plan"]
    plan.plan[0].acceptance_criteria = ["Complete"]

    errors = orchestration_errors(
        plan,
        planning_state=planning_state,
        output_goal_text="Produce an actionable plan.",
    )

    assert any(
        "item-001 top-level branch is not mapped in coverage_map" in error
        for error in errors
    )
