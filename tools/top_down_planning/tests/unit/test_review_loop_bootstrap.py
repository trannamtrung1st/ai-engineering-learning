"""Tests for whole-review cold-resume bootstrap."""

from __future__ import annotations

from tests.helpers import make_review_loop
from top_down_planning.domain.reviews import (
    ReviewFinding,
    ReviewLoop,
    needs_primary_revision_resume,
    pending_interrupted_owner_revision,
    pending_unconsumed_revision_cycle_entry,
    prepare_limit_reached_retry,
)
from top_down_planning.orchestrator.review_loop_bootstrap import bootstrap_whole_review_loop


def _loop(**overrides) -> ReviewLoop:
    base = make_review_loop(
        id="review-whole-output-01",
        type="whole_output",
        reviewer_session_id="reviewer-1",
        target_revision=4,
        scope={"kind": "whole_output"},
        status="pending",
        findings=[
            ReviewFinding(
                id="finding-01",
                severity="blocker",
                category="other",
                target_refs=["item-a"],
                issue="Fix path.",
                recommended_change="Correct ref.",
                status="unresolved",
            )
        ],
        revision_cycles=1,
        revise_at="blocker",
        lifecycle_status="revision_in_progress",
        active_stage="finding_verification",
        pending_revision_cycle_entry=False,
    )
    kwargs = dict(
        id=overrides.get("id", base.id),
        type=overrides.get("type", base.type),
        reviewer_session_id=overrides.get("reviewer_session_id", base.reviewer_session_id),
        target_revision=overrides.get("target_revision", base.target_revision),
        scope=overrides.get("scope", base.scope),
        status=overrides.get("status", base.status),
        findings=overrides.get("findings", base.findings),
        revision_cycles=overrides.get("revision_cycles", base.revision_cycles),
        revise_at=overrides.get("revise_at", base.revise_at),
        lifecycle_status=overrides.get("lifecycle_status", base.lifecycle_status),
        active_stage=overrides.get("active_stage", base.active_stage),
        pending_revision_cycle_entry=overrides.get(
            "pending_revision_cycle_entry",
            base.pending_revision_cycle_entry,
        ),
    )
    for key, value in overrides.items():
        if key not in kwargs:
            kwargs[key] = value
    return make_review_loop(**kwargs)


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


def test_bootstrap_skips_owner_resume_after_verification_recheck() -> None:
    """normalize prepare_recheck must not be followed by primary owner resume."""

    loop = _loop(status="changes_requested", lifecycle_status="findings_open")
    resumed: list[str] = []

    def resume_interrupted(current: ReviewLoop) -> ReviewLoop:
        resumed.append(current.id)
        return current

    def normalize(current: ReviewLoop) -> tuple[ReviewLoop, bool]:
        # Simulate prepare_recheck delivery.
        return (
            make_review_loop(
                id=current.id,
                type=current.type,
                target_revision=5,
                scope=current.scope,
                status="pending",
                findings=current.findings,
                revision_cycles=current.revision_cycles,
                revise_at=current.revise_at,
                lifecycle_status="verification_pending",
                active_stage="finding_verification",
            ),
            True,
        )

    updated, deliver_on_existing_session = bootstrap_whole_review_loop(
        loop,
        current_revision=5,
        resume_interrupted_revision=resume_interrupted,
        normalize_loop_for_resume=normalize,
    )

    assert resumed == []
    assert updated.lifecycle_status == "verification_pending"
    assert deliver_on_existing_session is False


def test_bootstrap_normalizes_limit_reached_before_primary_revision_resume() -> None:
    """limit_reached revival must run before needs_primary_revision_resume."""

    loop = make_review_loop(
        id="review-whole-output-01",
        type="whole_output",
        target_revision=4,
        scope={"kind": "whole_output"},
        status="blocked",
        findings=_loop().findings,
        revision_cycles=1,
        revise_at="blocker",
        lifecycle_status="limit_reached",
        exhausted_budget="verification_revision",
        pending_revision_cycle_entry=True,
        active_stage="finding_verification",
        review_record_schema_version=2,
        review_contract_version=2,
    )
    order: list[str] = []

    def normalize(current: ReviewLoop) -> tuple[ReviewLoop, bool]:
        order.append("normalize")
        revived = prepare_limit_reached_retry(current)
        return revived, False

    def resume_interrupted(current: ReviewLoop) -> ReviewLoop:
        order.append("resume_interrupted")
        assert current.status == "pending"
        assert current.lifecycle_status == "revision_in_progress"
        assert current.pending_revision_cycle_entry is True
        return current

    updated, deliver_on_existing_session = bootstrap_whole_review_loop(
        loop,
        current_revision=4,
        resume_interrupted_revision=resume_interrupted,
        normalize_loop_for_resume=normalize,
    )

    assert order == ["normalize", "resume_interrupted"]
    assert updated.lifecycle_status == "revision_in_progress"
    assert deliver_on_existing_session is False


def _optional_finding() -> ReviewFinding:
    return ReviewFinding(
        id="finding-minor-01",
        severity="minor",
        category="other",
        target_refs=["item-a"],
        issue="Polish path.",
        recommended_change="Tighten wording.",
        status="unresolved",
    )


def test_pending_interrupted_owner_revision_after_limit_retry_without_required_findings() -> None:
    """Limit revival leaves owner revision pending even when only optional findings remain."""

    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        target_revision=1,
        scope={"kind": "whole_plan"},
        status="blocked",
        findings=[_optional_finding()],
        revision_cycles=5,
        revise_at="blocker",
        lifecycle_status="limit_reached",
        exhausted_budget="verification_revision",
        pending_revision_cycle_entry=True,
        active_stage="finding_verification",
        review_record_schema_version=2,
        review_contract_version=2,
        verification_result={"decision": "needs_revision"},
    )
    revived = prepare_limit_reached_retry(loop)

    assert revived.status == "pending"
    assert revived.lifecycle_status == "revision_in_progress"
    assert revived.revision_cycles == 5
    assert revived.pending_revision_cycle_entry is True
    assert pending_unconsumed_revision_cycle_entry(revived) is True
    assert pending_interrupted_owner_revision(revived, current_revision=1) is True
    assert needs_primary_revision_resume(revived, current_revision=1) is False


def test_bootstrap_resumes_owner_revision_when_only_optional_findings_remain_after_limit_retry() -> None:
    """Raising the revision cap must resume the pending owner turn, not replay needs_revision."""

    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        target_revision=1,
        scope={"kind": "whole_plan"},
        status="blocked",
        findings=[_optional_finding()],
        revision_cycles=5,
        revise_at="blocker",
        lifecycle_status="limit_reached",
        exhausted_budget="verification_revision",
        pending_revision_cycle_entry=True,
        active_stage="finding_verification",
        review_record_schema_version=2,
        review_contract_version=2,
        verification_result={"decision": "needs_revision"},
    )
    resumed: list[str] = []

    def normalize(current: ReviewLoop) -> tuple[ReviewLoop, bool]:
        return prepare_limit_reached_retry(current), False

    def resume_interrupted(current: ReviewLoop) -> ReviewLoop:
        resumed.append(current.id)
        assert current.status == "pending"
        assert current.lifecycle_status == "revision_in_progress"
        assert current.pending_revision_cycle_entry is True
        return current

    updated, deliver_on_existing_session = bootstrap_whole_review_loop(
        loop,
        current_revision=1,
        resume_interrupted_revision=resume_interrupted,
        normalize_loop_for_resume=normalize,
    )

    assert resumed == ["review-whole-plan-01"]
    assert updated.lifecycle_status == "revision_in_progress"
    assert deliver_on_existing_session is False


def test_pending_unconsumed_revision_cycle_entry_distinguishes_limit_block_from_mid_cycle() -> None:
    """verification_revision limit pause is not a charged mid-cycle interrupt."""

    blocked_before_entry = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        target_revision=1,
        scope={"kind": "whole_plan"},
        status="pending",
        findings=[_optional_finding()],
        revision_cycles=5,
        revise_at="blocker",
        lifecycle_status="revision_in_progress",
        pending_revision_cycle_entry=True,
        active_stage="finding_verification",
    )
    mid_cycle = _loop(pending_revision_cycle_entry=False)

    assert pending_unconsumed_revision_cycle_entry(blocked_before_entry) is True
    assert pending_unconsumed_revision_cycle_entry(mid_cycle) is False
    assert pending_interrupted_owner_revision(mid_cycle, current_revision=4) is True
