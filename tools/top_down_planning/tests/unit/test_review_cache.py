"""Tests for cached review result validation."""

from __future__ import annotations

import json
from pathlib import Path

from top_down_planning.models import (
    PlanItem,
    PlanState,
    ReviewDecision,
    ReviewFinding,
    ReviewFindingCategory,
    ReviewFindingSeverity,
    RevisionMode,
    SourceMetadata,
    WholePlanReviewResult,
)
from top_down_planning.review_flow import _load_cached_whole_plan_review
from top_down_planning.persistence import whole_plan_review_result_path, write_json


def _plan() -> PlanState:
    return PlanState(
        source=SourceMetadata(
            input_file="idea.md",
            output_goal="goal",
            input_digest="a",
            output_goal_digest="b",
        ),
        plan=[
            PlanItem(id="item-001", title="Root", objective="Objective"),
        ],
    )


def test_cached_approve_with_major_finding_is_rejected(tmp_path: Path) -> None:
    plan = _plan()
    digest = "abc123"
    result = WholePlanReviewResult(
        plan_digest=digest,
        decision=ReviewDecision.APPROVE,
        summary="Looks good",
        findings=[
            ReviewFinding(
                severity=ReviewFindingSeverity.MAJOR,
                category=ReviewFindingCategory.COVERAGE,
                revision_mode=RevisionMode.REOPEN,
                node_ids=["item-001"],
                description="Missing branch",
            )
        ],
    )
    path = whole_plan_review_result_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, result.model_dump(mode="json"))

    loaded = _load_cached_whole_plan_review(path, digest, plan=plan)
    assert loaded is None


def test_cached_valid_approve_is_reused(tmp_path: Path) -> None:
    plan = _plan()
    digest = "abc123"
    result = WholePlanReviewResult(
        plan_digest=digest,
        decision=ReviewDecision.APPROVE,
        summary="Looks good",
        findings=[],
    )
    path = whole_plan_review_result_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, result.model_dump(mode="json"))

    loaded = _load_cached_whole_plan_review(path, digest, plan=plan)
    assert loaded is not None
    assert loaded.decision == ReviewDecision.APPROVE
