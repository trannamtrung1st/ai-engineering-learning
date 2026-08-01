"""No-legacy contract: deprecated fields and aliases are rejected."""

from __future__ import annotations

import pytest

from tests.helpers import review_loop_dict_with_binding

from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.domain.reviews import (
    MandatoryReviewLimits,
    ReviewFinding,
    ReviewLoop,
    ScopeReviewResult,
)


def test_review_finding_rejects_legacy_importance_and_required_change() -> None:
    with pytest.raises(ValueError, match="legacy finding field importance"):
        ReviewFinding.from_dict(
            {
                "id": "f1",
                "importance": "blocking",
                "severity": "blocker",
                "target_refs": ["item-a"],
                "issue": "gap",
                "recommended_change": "Fix",
            }
        )
    with pytest.raises(ValueError, match="finding requires recommended_change"):
        ReviewFinding.from_dict(
            {
                "id": "f2",
                "severity": "blocker",
                "target_refs": ["item-a"],
                "issue": "gap",
                "required_change": "Fix",
            }
        )


def test_scope_review_result_rejects_blocking_findings() -> None:
    with pytest.raises(ValueError, match="blocking_findings"):
        ScopeReviewResult.from_dict(
            {
                "stage": "scope_review",
                "decision": "approved",
                "target_digest": "d",
                "scope_id": "whole_plan",
                "blocking_findings": [],
            }
        )


def test_review_loop_to_dict_uses_scope_review_fields() -> None:
    loop = ReviewLoop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "whole_plan"},
        status="approved",
        lifecycle_status="approved",
        active_stage="scope_review",
        scope_review_rounds=2,
        revise_at="blocker",
        scope_review_result=ScopeReviewResult(
            target_digest="d",
            decision="approved",
            scope_id="whole_plan",
        ).to_dict(),
    )
    payload = loop.to_dict()
    assert payload["scope_review_rounds"] == 2
    assert "scope_review_result" in payload
    assert "blocker_review_result" not in payload


def test_legacy_persisted_blocker_fields_are_rejected() -> None:
    with pytest.raises(ValueError, match="legacy field blocker_review_result"):
        ReviewLoop.from_dict(review_loop_dict_with_binding(
            {
                "id": "review-whole-plan-01",
                "type": "whole_plan",
                "reviewer_session_id": "sess",
                "target_revision": 0,
                "scope": {"kind": "whole_plan"},
                "status": "approved",
                "findings": [],
                "revision_cycles": 0,
                "revise_at": "blocker",
                "blocker_review_result": {
                    "stage": "scope_review",
                    "decision": "approved",
                    "target_digest": "d",
                    "scope_id": "whole_plan",
                },
            }
        ))


def test_mandatory_limits_reject_legacy_config_key() -> None:
    with pytest.raises(ValueError, match="max_blocker_review_rounds"):
        MandatoryReviewLimits.from_mapping({"max_blocker_review_rounds": 3})
