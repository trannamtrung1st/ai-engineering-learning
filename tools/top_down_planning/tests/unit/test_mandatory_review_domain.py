"""Domain models for mandatory review gates (proposal Result Contracts / State Model)."""

from __future__ import annotations

import pytest

from top_down_planning.domain.reviews import (
    FINDING_DISPOSITIONS,
    MANDATORY_REVIEW_TRANSITIONS,
    OPEN_FINDING_DISPOSITIONS,
    FindingVerificationEntry,
    FindingVerificationResult,
    ReviewFinding,
    ReviewLoop,
    ScopeBlockerReviewResult,
    assert_mandatory_review_transition,
    blocking_unresolved_finding_ids,
    can_transition_mandatory_review,
    digests_equal,
    find_whole_plan_approval,
    is_approval_eligible,
    is_mandatory_gate_approval_record,
    stage_digest_matches_artifact,
    validate_blocker_review_decision,
    validate_finding_disposition,
    validate_mandatory_lifecycle_status,
    validate_verification_decision,
    verification_findings_closed,
)


DIGEST_A = "digest-aaa"
DIGEST_B = "digest-bbb"


def _finding(
    finding_id: str = "finding-1",
    *,
    status: str = "unresolved",
    importance: str = "blocking",
) -> ReviewFinding:
    return ReviewFinding(
        id=finding_id,
        severity=("blocker" if importance == "blocking" else "minor"),  # type: ignore[arg-type]
        category="other",
        target_refs=["item-a"],
        issue="Coverage gap",
        recommended_change="Add acceptance",
        status=status,  # type: ignore[arg-type]
    )


def _verified_result(
    *,
    digest: str = DIGEST_A,
    disposition: str = "resolved",
) -> FindingVerificationResult:
    return FindingVerificationResult(
        target_digest=digest,
        decision="verified",
        finding_set_id="fs-1",
        finding_results=[
            FindingVerificationEntry(
                finding_id="finding-1",
                disposition=disposition,  # type: ignore[arg-type]
                evidence=["tests/unit/test_mandatory_review_domain.py"],
            )
        ],
        summary="Findings closed.",
    )


def _blocker_approve(*, digest: str = DIGEST_A) -> ScopeBlockerReviewResult:
    return ScopeBlockerReviewResult(
        target_digest=digest,
        decision="approve",
        scope_id="whole_plan",
        acceptance_criteria_checked=["Core Invariant"],
        summary="No blockers.",
    )


def test_finding_dispositions_match_proposal() -> None:
    assert FINDING_DISPOSITIONS == {
        "resolved",
        "partially_resolved",
        "unresolved",
        "superseded",
        "invalid",
    }
    assert OPEN_FINDING_DISPOSITIONS == {"unresolved", "partially_resolved"}
    closed = FINDING_DISPOSITIONS - OPEN_FINDING_DISPOSITIONS
    assert closed == {"resolved", "superseded", "invalid"}
    for disposition in FINDING_DISPOSITIONS:
        assert validate_finding_disposition(disposition) == disposition


def test_partially_resolved_blocks_like_unresolved() -> None:
    findings = [
        _finding("f-open", status="partially_resolved"),
        _finding("f-invalid", status="invalid"),
    ]
    assert blocking_unresolved_finding_ids(findings) == ["f-open"]


def test_verification_and_blocker_result_round_trip() -> None:
    verification = FindingVerificationResult(
        target_digest=DIGEST_A,
        decision="needs_revision",
        finding_set_id="fs-9",
        finding_results=[
            FindingVerificationEntry(
                finding_id="finding-1",
                disposition="partially_resolved",
                evidence=["e1"],
                direct_side_effects=["side-1"],
            )
        ],
        new_direct_side_effect_findings=[_finding("finding-side")],
        summary="Still open.",
    )
    blocker = ScopeBlockerReviewResult(
        target_digest=DIGEST_A,
        decision="blockers_found",
        scope_id="whole_output",
        blocking_findings=[_finding("finding-new")],
        acceptance_criteria_checked=["acceptance-a"],
        summary="New blockers.",
    )

    assert FindingVerificationResult.from_dict(verification.to_dict()).to_dict() == (
        verification.to_dict()
    )
    assert ScopeBlockerReviewResult.from_dict(blocker.to_dict()).to_dict() == (
        blocker.to_dict()
    )
    assert validate_verification_decision("verified") == "verified"
    assert validate_blocker_review_decision("approve") == "approve"


def test_review_loop_round_trip_preserves_lifecycle_fields() -> None:
    loop = ReviewLoop(
        id="review-whole-plan-1",
        type="whole_plan",
        reviewer_session_id="rev-1",
        target_revision=3,
        scope={"kind": "whole_plan"},
        status="changes_requested",
        findings=[_finding()],
        revision_cycles=1,
        lifecycle_status="verification_pending",
        active_stage="finding_verification",
        finding_set_id="fs-1",
        blocker_review_rounds=2,
    )
    restored = ReviewLoop.from_dict(loop.to_dict())
    assert restored.lifecycle_status == "verification_pending"
    assert restored.active_stage == "finding_verification"
    assert restored.finding_set_id == "fs-1"
    assert restored.blocker_review_rounds == 2
    assert restored.to_dict() == loop.to_dict()


def test_mandatory_lifecycle_transitions_match_state_model() -> None:
    expected = {
        "review_pending": {
            "findings_open",
            "scope_review_pending",
            "blocker_review_pending",
            "review_incomplete",
        },
        "findings_open": {"revision_in_progress", "blocked", "review_incomplete"},
        "revision_in_progress": {"verification_pending", "limit_reached"},
        "verification_pending": {
            "findings_closed",
            "revision_in_progress",
            "blocked",
            "limit_reached",
            "review_incomplete",
        },
        "findings_closed": {
            "scope_review_pending",
            "blocker_review_pending",
            "limit_reached",
        },
        "scope_review_pending": {
            "approved",
            "findings_open",
            "blocked",
            "limit_reached",
            "review_incomplete",
        },
        "blocker_review_pending": {
            "approved",
            "findings_open",
            "blocked",
            "limit_reached",
            "review_incomplete",
        },
        "approved": set(),
        "blocked": set(),
        "limit_reached": set(),
        "review_incomplete": {
            "review_pending",
            "findings_open",
            "scope_review_pending",
            "blocker_review_pending",
            "verification_pending",
        },
    }
    assert {key: set(value) for key, value in MANDATORY_REVIEW_TRANSITIONS.items()} == (
        expected
    )
    assert can_transition_mandatory_review("findings_closed", "scope_review_pending")
    assert can_transition_mandatory_review("findings_closed", "blocker_review_pending")
    assert not can_transition_mandatory_review("findings_open", "approved")
    assert_mandatory_review_transition("scope_review_pending", "approved")
    assert_mandatory_review_transition("blocker_review_pending", "approved")
    with pytest.raises(ValueError, match="illegal mandatory review transition"):
        assert_mandatory_review_transition("limit_reached", "approved")
    assert validate_mandatory_lifecycle_status("limit_reached") == "limit_reached"


def test_digest_helpers_enforce_equality_rules() -> None:
    assert digests_equal(DIGEST_A, DIGEST_A)
    assert not digests_equal(DIGEST_A, DIGEST_B)
    assert not digests_equal(DIGEST_A, None)
    assert not digests_equal("", DIGEST_A)
    assert stage_digest_matches_artifact(
        stage_target_digest=DIGEST_A,
        current_artifact_digest=DIGEST_A,
    )
    assert not stage_digest_matches_artifact(
        stage_target_digest=DIGEST_A,
        current_artifact_digest=DIGEST_B,
    )
    assert not digests_equal(DIGEST_A, DIGEST_B)
    assert digests_equal(DIGEST_A, DIGEST_A)


def test_mandatory_gate_approval_record_requires_blocker_stage() -> None:
    incomplete = {
        "type": "whole_plan",
        "status": "approve",
        "target_revision": 0,
        "lifecycle_status": "review_pending",
    }
    assert is_mandatory_gate_approval_record(incomplete) is False

    complete = {
        "type": "whole_plan",
        "status": "approve",
        "target_revision": 0,
        "lifecycle_status": "approved",
        "active_stage": "scope_blocker_review",
        "blocker_review_result": {
            "stage": "scope_blocker_review",
            "decision": "approve",
            "target_digest": DIGEST_A,
            "scope_id": "whole_plan",
            "blocking_findings": [],
        },
    }
    assert is_mandatory_gate_approval_record(complete) is True

    reviews = [
        incomplete,
        complete,
    ]
    assert find_whole_plan_approval(reviews, 0) == complete


def test_approval_eligible_clear_path_without_verification_result() -> None:
    blocker = _blocker_approve()
    assert is_approval_eligible(
        verification=None,
        blocker_review=blocker,
        current_artifact_digest=DIGEST_A,
        lifecycle_status="blocker_review_pending",
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"lifecycle_status": "limit_reached"},
        {"lifecycle_status": "blocked"},
        {
            "verification": _verified_result(disposition="unresolved"),
        },
        {
            "verification": FindingVerificationResult(
                target_digest=DIGEST_A,
                decision="verified",
                finding_set_id="fs-1",
                finding_results=[
                    FindingVerificationEntry(
                        finding_id="finding-1",
                        disposition="resolved",
                        direct_side_effects=["regression"],
                    )
                ],
            )
        },
        {
            "blocker_review": ScopeBlockerReviewResult(
                target_digest=DIGEST_A,
                decision="blockers_found",
                scope_id="whole_plan",
                blocking_findings=[_finding()],
            )
        },
        {"current_artifact_digest": DIGEST_B},
        {
            "verification": _verified_result(digest=DIGEST_B),
        },
        {
            "blocker_review": _blocker_approve(digest=DIGEST_B),
        },
    ],
)
def test_approval_not_eligible_when_invariant_broken(kwargs: dict) -> None:
    base = {
        "verification": _verified_result(),
        "blocker_review": _blocker_approve(),
        "current_artifact_digest": DIGEST_A,
    }
    base.update(kwargs)
    assert is_approval_eligible(**base) is False


def test_verification_findings_closed_rejects_open_or_side_effects() -> None:
    assert verification_findings_closed(
        [FindingVerificationEntry(finding_id="f1", disposition="resolved")]
    )
    assert not verification_findings_closed(
        [FindingVerificationEntry(finding_id="f1", disposition="partially_resolved")]
    )
    assert not verification_findings_closed(
        [
            FindingVerificationEntry(
                finding_id="f1",
                disposition="resolved",
                direct_side_effects=["leak"],
            )
        ]
    )
    assert not verification_findings_closed([])
