"""Phase 4 scope_review naming and legacy readers."""

from __future__ import annotations

from top_down_planning.domain.reviews import (
    ReviewFinding,
    ReviewLoop,
    ScopeReviewResult,
    build_scope_review_result,
    canonicalize_lifecycle_status,
    canonicalize_review_stage,
    canonicalize_scope_review_decision,
    is_mandatory_gate_approval_record,
    prepare_review_incomplete_retry,
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


def test_canonicalize_maps_legacy_scope_names() -> None:
    assert canonicalize_review_stage("scope_blocker_review") == "scope_review"
    assert canonicalize_lifecycle_status("blocker_review_pending") == "scope_review_pending"
    assert canonicalize_scope_review_decision("approve") == "approved"
    assert canonicalize_scope_review_decision("blockers_found") == "changes_requested"


def test_prepare_scope_review_loop_writes_new_names() -> None:
    loop = ReviewLoop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "whole_plan"},
        status="approved",
        lifecycle_status="review_pending",
        findings=[],
    )
    assert approved_means_start_scope_review(loop) is True
    prepared = prepare_scope_review_loop(loop)
    assert prepared.active_stage == "scope_review"
    assert prepared.lifecycle_status == "scope_review_pending"
    assert is_scope_review_stage(prepared) is True
    payload = prepared.to_dict()
    assert payload["active_stage"] == "scope_review"
    assert payload["lifecycle_status"] == "scope_review_pending"
    assert payload["scope_review_rounds"] == 1
    assert payload["blocker_review_rounds"] == 1
    fields = stage_package_fields(prepared)
    assert fields["stage"] == "scope_review"
    assert fields["respond_contract"]["stage"] == "scope_review"
    assert "reported_findings" in fields["respond_contract"]["preferred_fields"]


def test_scope_review_result_accepts_legacy_payload_and_writes_new_names() -> None:
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
    )
    findings, result = build_scope_review_result(
        {
            "stage": "scope_blocker_review",
            "decision": "blockers_found",
            "target_digest": "digest",
            "scope_id": "whole_plan",
            "blocking_findings": [
                _finding("f-minor", severity="minor").to_dict(),
                _finding("f-major", severity="major").to_dict(),
                _finding("f-blocker", severity="blocker").to_dict(),
            ],
            "summary": "All severities.",
        },
        loop,
    )
    assert {finding.id for finding in findings} == {"f-minor", "f-major", "f-blocker"}
    assert result.decision == "changes_requested"
    assert [finding.severity for finding in result.reported_findings] == [
        "minor",
        "major",
        "blocker",
    ]
    payload = result.to_dict()
    assert payload["stage"] == "scope_review"
    assert payload["decision"] == "changes_requested"
    assert len(payload["reported_findings"]) == 3
    assert payload["blocking_findings"] == payload["reported_findings"]

    legacy = ScopeReviewResult.from_dict(
        {
            "stage": "scope_blocker_review",
            "decision": "approve",
            "target_digest": "digest",
            "scope_id": "whole_plan",
            "blocking_findings": [],
            "summary": "Clear.",
        }
    )
    assert legacy.stage == "scope_review"
    assert legacy.decision == "approved"
    assert legacy.reported_findings == []


def test_review_loop_reads_legacy_scope_fields() -> None:
    restored = ReviewLoop.from_dict(
        {
            "id": "review-whole-plan-01",
            "type": "whole_plan",
            "reviewer_session_id": "sess",
            "target_revision": 0,
            "scope": {"kind": "whole_plan"},
            "status": "approve",
            "findings": [],
            "revision_cycles": 0,
            "lifecycle_status": "blocker_review_pending",
            "active_stage": "scope_blocker_review",
            "blocker_review_rounds": 2,
            "blocker_review_result": {
                "stage": "scope_blocker_review",
                "decision": "approve",
                "target_digest": "digest",
                "scope_id": "whole_plan",
                "blocking_findings": [],
                "summary": "Clear.",
            },
            "exhausted_budget": "blocker_review",
        }
    )
    assert restored.active_stage == "scope_review"
    assert restored.lifecycle_status == "scope_review_pending"
    assert restored.blocker_review_rounds == 2
    assert restored.exhausted_budget == "scope_review"
    assert is_mandatory_gate_approval_record(
        {
            "status": "approve",
            "lifecycle_status": "approved",
            "active_stage": "scope_blocker_review",
            "blocker_review_result": {
                "stage": "scope_blocker_review",
                "decision": "approve",
                "target_digest": "digest",
                "scope_id": "whole_plan",
                "blocking_findings": [],
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
        review_incomplete={
            "stage": "scope_blocker_review",
            "finding_set_id": "fs-1",
            "reason": "unavailable",
        },
    )
    retried = prepare_review_incomplete_retry(loop)
    assert retried.status == "pending"
    assert retried.lifecycle_status == "scope_review_pending"
    assert retried.active_stage == "scope_review"
