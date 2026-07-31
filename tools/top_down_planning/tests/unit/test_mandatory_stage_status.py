"""Stage-native loop status and orchestration decision (no legacy mapping)."""

from __future__ import annotations

import pytest

from top_down_planning.domain.reviews import (
    ReviewLoop,
    mandatory_stage_respond_decision,
    validate_mandatory_stage_decision,
)


def test_mandatory_stage_respond_decision_requires_result_payloads() -> None:
    verification_loop = ReviewLoop(
        id="r1",
        type="whole_plan",
        reviewer_session_id="s",
        target_revision=1,
        scope={"kind": "whole_plan"},
        status="verified",
        active_stage="finding_verification",
        verification_result=None,
    )
    with pytest.raises(ValueError, match="missing verification_result"):
        mandatory_stage_respond_decision(verification_loop)

    blocker_loop = ReviewLoop(
        id="r2",
        type="whole_plan",
        reviewer_session_id="s",
        target_revision=1,
        scope={"kind": "whole_plan"},
        status="approve",
        active_stage="scope_blocker_review",
        blocker_review_result=None,
    )
    with pytest.raises(ValueError, match="missing blocker_review_result"):
        mandatory_stage_respond_decision(blocker_loop)


def test_validate_mandatory_stage_decision_returns_stage_native_values() -> None:
    assert validate_mandatory_stage_decision("finding_verification", "verified") == "verified"
    assert validate_mandatory_stage_decision("scope_blocker_review", "approve") == "approve"
    assert validate_mandatory_stage_decision("initial_review", "approved") == "approved"


def test_gate_approve_closes_respond_before_lifecycle_approved() -> None:
    from top_down_planning.domain.reviews import (
        is_review_respond_closed,
        is_terminal_review_loop,
    )

    loop = ReviewLoop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "whole_plan"},
        status="approve",
        lifecycle_status="blocker_review_pending",
        active_stage="scope_blocker_review",
        blocker_review_result={
            "stage": "scope_blocker_review",
            "decision": "approve",
            "target_digest": "digest",
            "scope_id": "whole_plan",
            "blocking_findings": [],
            "summary": "Clear.",
        },
    )
    assert is_review_respond_closed(loop) is True
    assert is_terminal_review_loop(loop) is False

    initial_clear = ReviewLoop(
        id="review-whole-plan-02",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "whole_plan"},
        status="approved",
        lifecycle_status="review_pending",
        active_stage=None,
    )
    assert is_review_respond_closed(initial_clear) is False
    assert is_terminal_review_loop(initial_clear) is False
