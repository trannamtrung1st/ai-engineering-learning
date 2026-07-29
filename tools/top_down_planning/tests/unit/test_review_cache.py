"""Tests for cached specialist review reuse."""

from __future__ import annotations

from top_down_planning.checkpoint_flow import _load_cached_specialist_review
from top_down_planning.models import (
    ReviewCheckpoint,
    ReviewDecision,
    ReviewerRole,
    SpecialistReviewResult,
)
from top_down_planning.persistence import write_json
from tests.plan_factory import make_root_plan


def test_cached_specialist_review_matches_digest(tmp_path) -> None:
    plan = make_root_plan()
    digest = "a" * 64
    result = SpecialistReviewResult(
        reviewer_role=ReviewerRole.COVERAGE_BOUNDARY,
        plan_digest=digest,
        checkpoint=ReviewCheckpoint.INITIAL_STRUCTURE,
        decision=ReviewDecision.APPROVE,
        summary="Approved",
    )
    path = tmp_path / "coverage_boundary.json"
    write_json(path, result.model_dump(mode="json"))

    loaded = _load_cached_specialist_review(
        path,
        digest,
        plan=plan,
        role=ReviewerRole.COVERAGE_BOUNDARY,
    )
    assert loaded is not None
    assert loaded.summary == "Approved"


def test_cached_specialist_review_rejects_stale_digest(tmp_path) -> None:
    plan = make_root_plan()
    result = SpecialistReviewResult(
        reviewer_role=ReviewerRole.COVERAGE_BOUNDARY,
        plan_digest="old-digest",
        checkpoint=ReviewCheckpoint.INITIAL_STRUCTURE,
        decision=ReviewDecision.APPROVE,
        summary="Approved",
    )
    path = tmp_path / "coverage_boundary.json"
    write_json(path, result.model_dump(mode="json"))

    loaded = _load_cached_specialist_review(
        path,
        "new-digest",
        plan=plan,
        role=ReviewerRole.COVERAGE_BOUNDARY,
    )
    assert loaded is None
