"""Tests for plan digest computation."""

from __future__ import annotations

from top_down_planning.digest import compute_plan_digest
from top_down_planning.models import DecompositionStatus, PlanItem, PlanState, ResultMetadata, SourceMetadata


def _sample_plan() -> PlanState:
    source = SourceMetadata(
        input_file="idea.md",
        output_goal="Produce a plan",
        input_digest="input-digest",
        output_goal_digest="goal-digest",
    )
    return PlanState(
        source=source,
        plan=[
            PlanItem(
                id="item-001",
                title="Root",
                objective="Root objective",
                decomposition_status=DecompositionStatus.ACTIONABLE,
            )
        ],
        result=ResultMetadata(summary="done"),
    )


def test_plan_digest_is_stable() -> None:
    plan = _sample_plan()
    first = compute_plan_digest(plan)
    second = compute_plan_digest(plan)
    assert first == second
    assert len(first) == 64


def test_plan_digest_changes_when_plan_changes() -> None:
    plan = _sample_plan()
    before = compute_plan_digest(plan)
    plan.plan[0].title = "Changed"
    after = compute_plan_digest(plan)
    assert before != after


def test_plan_digest_excludes_result_metadata() -> None:
    plan = _sample_plan()
    before = compute_plan_digest(plan)
    plan.result.summary = "different summary"
    after = compute_plan_digest(plan)
    assert before == after
