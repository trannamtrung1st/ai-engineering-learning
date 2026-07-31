"""Phase 5: deprecated writers removed; legacy readers retained."""

from __future__ import annotations

from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.domain.reviews import (
    MandatoryReviewLimits,
    ReviewFinding,
    ReviewLoop,
    ScopeReviewResult,
)


def test_review_finding_to_dict_omits_importance_and_required_change() -> None:
    finding = ReviewFinding.from_dict(
        {
            "id": "f1",
            "importance": "blocking",
            "target_refs": ["item-a"],
            "issue": "gap",
            "required_change": "Fix",
        }
    )
    payload = finding.to_dict()
    assert payload["severity"] == "blocker"
    assert payload["recommended_change"] == "Fix"
    assert "importance" not in payload
    assert "required_change" not in payload


def test_scope_review_result_to_dict_omits_blocking_findings() -> None:
    result = ScopeReviewResult(
        target_digest="d",
        decision="approved",
        scope_id="whole_plan",
        reported_findings=[],
    )
    payload = result.to_dict()
    assert payload["stage"] == "scope_review"
    assert "reported_findings" in payload
    assert "blocking_findings" not in payload


def test_review_loop_to_dict_omits_legacy_blocker_keys() -> None:
    loop = ReviewLoop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "whole_plan"},
        status="approved",
        lifecycle_status="approved",
        active_stage="scope_review",
        blocker_review_rounds=2,
        blocker_review_result=ScopeReviewResult(
            target_digest="d",
            decision="approved",
            scope_id="whole_plan",
        ).to_dict(),
    )
    payload = loop.to_dict()
    assert payload["scope_review_rounds"] == 2
    assert "blocker_review_rounds" not in payload
    assert "scope_review_result" in payload
    assert "blocker_review_result" not in payload


def test_legacy_persisted_blocker_fields_still_load() -> None:
    restored = ReviewLoop.from_dict(
        {
            "id": "review-whole-plan-01",
            "type": "whole_plan",
            "reviewer_session_id": "sess",
            "target_revision": 0,
            "scope": {"kind": "whole_plan"},
            "status": "approve",
            "findings": [
                {
                    "id": "legacy",
                    "importance": "blocking",
                    "target_refs": ["item-a"],
                    "issue": "old",
                    "required_change": "fix",
                }
            ],
            "revision_cycles": 0,
            "lifecycle_status": "blocker_review_pending",
            "active_stage": "scope_blocker_review",
            "blocker_review_rounds": 1,
            "blocker_review_result": {
                "stage": "scope_blocker_review",
                "decision": "approve",
                "target_digest": "d",
                "scope_id": "whole_plan",
                "blocking_findings": [],
                "summary": "ok",
            },
        }
    )
    assert restored.findings[0].severity == "blocker"
    assert restored.findings[0].recommended_change == "fix"
    assert restored.active_stage == "scope_review"
    assert restored.lifecycle_status == "scope_review_pending"
    assert restored.blocker_review_rounds == 1
    assert restored.blocker_review_result is not None


def test_default_config_no_longer_writes_max_blocker_review_rounds() -> None:
    plan_limits = DEFAULT_CONFIG["limits"]["whole_plan_review"]
    assert "max_scope_review_rounds" in plan_limits
    assert "max_blocker_review_rounds" not in plan_limits
    assert "max_blocker_review_rounds" not in MandatoryReviewLimits().to_dict()
    # Legacy config key still readable.
    loaded = MandatoryReviewLimits.from_mapping({"max_blocker_review_rounds": 2})
    assert loaded.max_scope_review_rounds == 2
