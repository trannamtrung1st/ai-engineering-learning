"""Tests for whole-review cold-resume bootstrap."""

from __future__ import annotations

from top_down_planning.domain.reviews import ReviewFinding, ReviewLoop, needs_primary_revision_resume
from top_down_planning.orchestrator.review_loop_bootstrap import bootstrap_whole_review_loop


def _loop(**overrides) -> ReviewLoop:
    base = ReviewLoop(
        id="review-whole-output-01",
        type="whole_output",
        reviewer_session_id="reviewer-1",
        target_revision=4,
        scope={"kind": "whole_output"},
        status="pending",
        findings=[
            ReviewFinding(
                id="finding-01",
                importance="blocking",
                target_refs=["item-a"],
                issue="Fix path.",
                required_change="Correct ref.",
                status="unresolved",
            )
        ],
        revision_cycles=1,
    )
    return ReviewLoop(
        id=overrides.get("id", base.id),
        type=overrides.get("type", base.type),
        reviewer_session_id=overrides.get("reviewer_session_id", base.reviewer_session_id),
        target_revision=overrides.get("target_revision", base.target_revision),
        scope=overrides.get("scope", base.scope),
        status=overrides.get("status", base.status),
        findings=overrides.get("findings", base.findings),
        revision_cycles=overrides.get("revision_cycles", base.revision_cycles),
    )


def test_needs_primary_revision_resume_detects_interrupted_cycle() -> None:
    loop = _loop()

    assert needs_primary_revision_resume(loop, current_revision=4) is True
    assert needs_primary_revision_resume(loop, current_revision=5) is False
    assert needs_primary_revision_resume(_loop(status="changes_requested"), current_revision=4) is False
    assert needs_primary_revision_resume(_loop(revision_cycles=0), current_revision=4) is False


def test_bootstrap_whole_review_loop_skips_duplicate_delivery_after_interrupt() -> None:
    loop = _loop()
    resumed: list[str] = []

    def resume_interrupted(current: ReviewLoop) -> ReviewLoop:
        resumed.append(current.id)
        return _loop(target_revision=5)

    def normalize(current: ReviewLoop) -> tuple[ReviewLoop, bool]:
        return current, False

    updated, deliver_on_existing_session = bootstrap_whole_review_loop(
        loop,
        current_revision=4,
        resume_interrupted_revision=resume_interrupted,
        normalize_loop_for_resume=normalize,
    )

    assert resumed == ["review-whole-output-01"]
    assert updated.target_revision == 5
    assert deliver_on_existing_session is False
