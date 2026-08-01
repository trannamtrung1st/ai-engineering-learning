"""Regression tests for mandatory verification finding merge."""

from __future__ import annotations

import pytest

from tests.helpers import make_review_loop
from top_down_planning.domain.reviews import (
    ReviewFinding,
    ReviewLoop,
    merge_verification_findings,
)


def _loop_with_open_finding() -> ReviewLoop:
    return make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=1,
        scope={"kind": "whole_plan"},
        findings=[
            ReviewFinding(
                id="finding-open",
                severity="blocker",
                category="other",
                target_refs=["item-api"],
                issue="Gap in API coverage.",
                recommended_change="Add acceptance criteria.",
                status="unresolved",
            )
        ],
        lifecycle_status="verification_pending",
        active_stage="finding_verification",
        finding_set_id="review-whole-plan-01-fs-01",
        revise_at="blocker",
    )


def test_empty_finding_results_cannot_wipe_open_findings() -> None:
    loop = _loop_with_open_finding()
    with pytest.raises(ValueError, match="missing required finding_id"):
        merge_verification_findings(
            loop,
            {
                "stage": "finding_verification",
                "decision": "verified",
                "finding_set_id": "review-whole-plan-01-fs-01",
                "finding_results": [],
                "new_direct_side_effect_findings": [],
                "target_digest": "digest-1",
            },
        )


def test_merge_preserves_finding_metadata() -> None:
    loop = _loop_with_open_finding()
    merged, _ = merge_verification_findings(
        loop,
        {
            "stage": "finding_verification",
            "decision": "verified",
            "finding_set_id": "review-whole-plan-01-fs-01",
            "finding_results": [
                {
                    "finding_id": "finding-open",
                    "disposition": "resolved",
                    "evidence": ["tests added"],
                    "direct_side_effects": [],
                }
            ],
            "new_direct_side_effect_findings": [],
            "target_digest": "digest-1",
        },
    )
    assert merged[0].issue == "Gap in API coverage."
    assert merged[0].recommended_change == "Add acceptance criteria."
    assert merged[0].target_refs == ["item-api"]
    assert merged[0].status == "resolved"
