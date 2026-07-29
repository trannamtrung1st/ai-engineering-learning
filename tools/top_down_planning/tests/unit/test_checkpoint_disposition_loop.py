"""Tests for checkpoint review and post-disposition re-review."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from top_down_planning.checkpoint_flow import (
    CheckpointFlowDeps,
    _checkpoint_needs_disposition,
    run_checkpoint_reviews,
)
from top_down_planning.models import (
    CheckpointFinding,
    PlanningMode,
    ReviewCheckpoint,
    ReviewConfig,
    ReviewDecision,
    ReviewFindingCategory,
    ReviewFindingSeverity,
    ReviewerRole,
    SpecialistReviewResult,
)
from top_down_planning.planning_state import new_planning_state
from top_down_planning.session_strategy import resolve_session_strategy
from tests.plan_factory import make_root_plan


def _finding() -> CheckpointFinding:
    return CheckpointFinding(
        id="CB-001",
        severity=ReviewFindingSeverity.MAJOR,
        category=ReviewFindingCategory.SCOPE,
        reviewer_role=ReviewerRole.COVERAGE_BOUNDARY,
        affected_branches=["item-001"],
        observation="Overlap detected.",
    )


def test_checkpoint_needs_disposition() -> None:
    approved = SpecialistReviewResult(
        reviewer_role=ReviewerRole.COVERAGE_BOUNDARY,
        plan_digest="digest",
        checkpoint=ReviewCheckpoint.INITIAL_STRUCTURE,
        decision=ReviewDecision.APPROVE,
        summary="Looks good.",
    )
    needs_revision = approved.model_copy(
        update={"decision": ReviewDecision.NEEDS_REVISION, "findings": [_finding()]}
    )
    assert not _checkpoint_needs_disposition([approved])
    assert _checkpoint_needs_disposition([needs_revision])


@pytest.mark.asyncio
async def test_run_checkpoint_reviews_reruns_after_disposition(tmp_path, monkeypatch) -> None:
    plan = make_root_plan(
        input_file=str(tmp_path / "idea.md"),
        output_goal="Produce a plan",
        input_digest="a",
        output_goal_digest="b",
    )
    planning_state = new_planning_state()
    strategy = resolve_session_strategy(None, planning_mode=PlanningMode.FULL)
    review_calls = {"count": 0}

    async def fake_collect(*_args, **_kwargs):
        review_calls["count"] += 1
        if review_calls["count"] == 1:
            result = SpecialistReviewResult(
                reviewer_role=ReviewerRole.COVERAGE_BOUNDARY,
                plan_digest="digest-1",
                checkpoint=ReviewCheckpoint.INITIAL_STRUCTURE,
                decision=ReviewDecision.NEEDS_REVISION,
                summary="Needs boundary fixes.",
                findings=[_finding()],
            )
            return [result], [_finding()]
        result = SpecialistReviewResult(
            reviewer_role=ReviewerRole.COVERAGE_BOUNDARY,
            plan_digest="digest-2",
            checkpoint=ReviewCheckpoint.INITIAL_STRUCTURE,
            decision=ReviewDecision.APPROVE,
            summary="Approved after disposition.",
        )
        return [result], []

    disposition_calls = {"count": 0}

    async def fake_disposition(**_kwargs):
        disposition_calls["count"] += 1
        return plan, planning_state

    deps = CheckpointFlowDeps(
        workspace_root=tmp_path,
        output_dir=tmp_path / "planning-output",
        loaded=MagicMock(),
        output_goal=MagicMock(),
        stop_hint=None,
        embed_threshold=4000,
        client=MagicMock(),
        renderer=MagicMock(),
        stream=MagicMock(),
        audit=False,
        review=ReviewConfig(max_post_disposition_cycles=2),
        strategy=strategy,
        resolve_review_context=lambda: None,
        resolve_review_model=lambda: "auto",
        run_primary_disposition=fake_disposition,
    )

    import top_down_planning.checkpoint_flow as checkpoint_flow

    monkeypatch.setattr(
        checkpoint_flow,
        "_collect_checkpoint_findings",
        AsyncMock(side_effect=fake_collect),
    )

    returned_plan, returned_state, findings = await run_checkpoint_reviews(
        deps,
        plan=plan,
        planning_state=planning_state,
        run_state=MagicMock(
            limits=MagicMock(session_timeout_seconds=60),
            orchestration_metrics=MagicMock(
                reviewer_session_count=0,
                findings_by_reviewer={},
            ),
        ),
        checkpoint=ReviewCheckpoint.INITIAL_STRUCTURE,
    )

    assert returned_plan is plan
    assert returned_state is planning_state
    assert findings == []
    assert review_calls["count"] == 2
    assert disposition_calls["count"] == 1
