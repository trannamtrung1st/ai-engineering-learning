"""Blocker reopen finding merge and orchestration decision helpers."""

from __future__ import annotations

from top_down_planning.domain.reviews import (
    ReviewFinding,
    ReviewLoop,
    build_scope_blocker_review_result,
    merge_blocker_reopen_findings,
)
from top_down_planning.orchestrator.mandatory_review_stages import (
    mandatory_orchestration_decision,
)


def test_merge_blocker_reopen_findings_preserves_prior_audit() -> None:
    loop = ReviewLoop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=1,
        scope={"kind": "whole_plan"},
        findings=[
            ReviewFinding(
                id="finding-old",
                severity="blocker",
                category="other",
                target_refs=["item-a"],
                issue="Old issue",
                recommended_change="Was fixed",
                status="resolved",
            )
        ],
        verification_result={
            "stage": "finding_verification",
            "decision": "verified",
            "target_digest": "d1",
            "finding_set_id": "fs-1",
            "finding_results": [],
            "summary": "",
        },
    )
    new_blocker = ReviewFinding(
        id="finding-new",
        severity="blocker",
                category="other",
        target_refs=["item-b"],
        issue="New blocker",
        recommended_change="Fix",
        status="unresolved",
    )
    merged, _ = build_scope_blocker_review_result(
        {
            "stage": "scope_blocker_review",
            "decision": "blockers_found",
            "target_digest": "d2",
            "scope_id": "whole_plan",
            "blocking_findings": [new_blocker.to_dict()],
            "acceptance_criteria_checked": ["Core Invariant"],
            "summary": "Blockers remain.",
        },
        loop,
    )
    ids = [finding.id for finding in merged]
    assert ids == ["finding-old", "finding-new"]
    assert merged[0].issue == "Old issue"
    assert merged[1].id == "finding-new"


def test_mandatory_orchestration_decision_reads_stage_results() -> None:
    verified_loop = ReviewLoop(
        id="r1",
        type="whole_plan",
        reviewer_session_id="s",
        target_revision=1,
        scope={"kind": "whole_plan"},
        status="verified",
        active_stage="finding_verification",
        verification_result={
            "stage": "finding_verification",
            "decision": "verified",
            "target_digest": "d",
            "finding_set_id": "fs",
            "finding_results": [],
            "summary": "",
        },
    )
    assert mandatory_orchestration_decision(verified_loop) == "verified"

    blocker_loop = ReviewLoop(
        id="r2",
        type="whole_plan",
        reviewer_session_id="s",
        target_revision=1,
        scope={"kind": "whole_plan"},
        status="blockers_found",
        active_stage="scope_blocker_review",
        blocker_review_result={
            "stage": "scope_blocker_review",
            "decision": "blockers_found",
            "target_digest": "d",
            "scope_id": "whole_plan",
            "blocking_findings": [],
            "summary": "",
        },
    )
    assert mandatory_orchestration_decision(blocker_loop) == "changes_requested"

    assert merge_blocker_reopen_findings(
        verified_loop,
        [
            ReviewFinding(
                id="finding-new",
                severity="blocker",
                category="other",
                target_refs=["item-a"],
                issue="x",
                recommended_change="y",
            )
        ],
    )[0].id == "finding-new"
