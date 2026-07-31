"""Scope-review naming and strict no-legacy validation."""

from __future__ import annotations

import pytest

from top_down_planning.domain.reviews import (
    ReviewFinding,
    ReviewLoop,
    ScopeReviewResult,
    is_mandatory_gate_approval_record,
    merge_scope_review_findings,
    prepare_review_incomplete_retry,
    validate_lifecycle_status,
    validate_review_stage,
    validate_scope_review_decision,
)
from top_down_planning.orchestrator.mandatory_review_stages import (
    approved_means_start_scope_review,
    is_scope_review_stage,
    prepare_scope_review_loop,
    stage_package_fields,
)


def _finding(finding_id: str, *, severity: str = "minor") -> ReviewFinding:
    return ReviewFinding(
        id=finding_id,
        severity=severity,  # type: ignore[arg-type]
        category="other",
        target_refs=["item-a"],
        issue=f"issue {finding_id}",
        recommended_change="fix",
    )


def test_legacy_scope_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="legacy review stage"):
        validate_review_stage("scope_blocker_review")
    with pytest.raises(ValueError, match="legacy lifecycle status"):
        validate_lifecycle_status("blocker_review_pending")
    with pytest.raises(ValueError, match="legacy scope review decision"):
        validate_scope_review_decision("approve")
    with pytest.raises(ValueError, match="legacy scope review decision"):
        validate_scope_review_decision("blockers_found")


def test_prepare_scope_review_loop_writes_scope_review_fields() -> None:
    loop = ReviewLoop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "whole_plan"},
        status="approved",
        lifecycle_status="review_pending",
        findings=[],
        revise_at="blocker",
    )
    assert approved_means_start_scope_review(loop) is True
    prepared = prepare_scope_review_loop(loop)
    assert prepared.active_stage == "scope_review"
    assert prepared.lifecycle_status == "scope_review_pending"
    assert is_scope_review_stage(prepared) is True
    assert prepared.scope_review_rounds == 0
    payload = prepared.to_dict()
    assert payload["active_stage"] == "scope_review"
    assert payload["lifecycle_status"] == "scope_review_pending"
    assert payload.get("scope_review_rounds", 0) == 0
    assert "scope_review_rounds" not in payload
    fields = stage_package_fields(prepared)
    assert fields["stage"] == "scope_review"
    assert fields["respond_contract"]["stage"] == "scope_review"
    assert "reported_findings" in fields["respond_contract"]["required_fields"]


def test_scope_review_result_uses_reported_findings_only() -> None:
    loop = ReviewLoop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "whole_plan"},
        status="pending",
        active_stage="scope_review",
        finding_set_id="fs-1",
        findings=[],
        revise_at="blocker",
    )
    reported = [
        _finding("f-minor", severity="minor"),
        _finding("f-major", severity="major"),
        _finding("f-blocker", severity="blocker"),
    ]
    findings = merge_scope_review_findings(loop, reported)
    result = ScopeReviewResult(
        target_digest="digest",
        decision="changes_requested",
        scope_id="whole_plan",
        reported_findings=reported,
        summary="All severities.",
    )
    assert {finding.id for finding in findings} == {"f-minor", "f-major", "f-blocker"}
    assert result.decision == "changes_requested"
    payload = result.to_dict()
    assert payload["stage"] == "scope_review"
    assert len(payload["reported_findings"]) == 3

    restored = ScopeReviewResult.from_dict(
        {
            "stage": "scope_review",
            "decision": "approved",
            "target_digest": "digest",
            "scope_id": "whole_plan",
            "reported_findings": [],
            "summary": "Clear.",
        }
    )
    assert restored.stage == "scope_review"
    assert restored.decision == "approved"


def test_review_loop_rejects_legacy_persisted_fields() -> None:
    with pytest.raises(ValueError, match="legacy lifecycle status"):
        ReviewLoop.from_dict(
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
                "lifecycle_status": "blocker_review_pending",
                "active_stage": "scope_blocker_review",
            }
        )


def test_mandatory_gate_approval_requires_canonical_record() -> None:
    assert is_mandatory_gate_approval_record(
        {
            "type": "whole_plan",
            "status": "approved",
            "lifecycle_status": "approved",
            "active_stage": "scope_review",
            "revise_at": "blocker",
            "findings": [],
            "finding_actions": [],
            "scope_review_result": {
                "stage": "scope_review",
                "decision": "approved",
                "target_digest": "digest",
                "scope_id": "whole_plan",
                "reported_findings": [],
            },
        }
    )


def test_incomplete_retry_restores_scope_review_pending() -> None:
    loop = ReviewLoop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "whole_plan"},
        status="review_incomplete",
        lifecycle_status="review_incomplete",
        active_stage="scope_review",
        finding_set_id="fs-1",
        revise_at="blocker",
        review_incomplete={
            "stage": "scope_review",
            "finding_set_id": "fs-1",
            "reason": "unavailable",
        },
    )
    retried = prepare_review_incomplete_retry(loop)
    assert retried.status == "pending"
    assert retried.lifecycle_status == "scope_review_pending"
    assert retried.active_stage == "scope_review"
