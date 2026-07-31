"""Cross-cutting acceptance: Core Invariant, digests, and Loop Bounds.

Locks Final Recommendation across domain helpers and both mandatory gates:
verified finding closure alone never approves; approval requires a clear fresh
scope_blocker_review against the current artifact digest; limit_reached/blocked
never convert to approval.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.agent_tool import RequestError, ReviewAgentService
from top_down_planning.domain.reviews import (
    FindingVerificationEntry,
    FindingVerificationResult,
    MandatoryReviewLimits,
    ReviewFinding,
    ReviewLoop,
    ScopeBlockerReviewResult,
    approval_allowed_under_loop_bounds,
    is_approval_eligible,
    reject_approval_when_budget_exhausted,
)
from top_down_planning.orchestrator import (
    WholeOutputReviewOrchestrator,
    WholePlanReviewOrchestrator,
)
from top_down_planning.orchestrator.mandatory_review_stages import (
    approved_means_final_approval,
    approved_means_start_blocker_review,
    prepare_blocker_review_loop,
    stage_package_fields,
)
from top_down_planning.orchestrator.phases import (
    OUTPUT_VALIDATED,
    PLAN_VALIDATED,
    WHOLE_OUTPUT_REVIEW,
    WHOLE_PLAN_REVIEW,
)
from top_down_planning.persistence import FileRunStore
from core_tools.provider import StubProvider
from tests.helpers import (
    create_run_kwargs,
    grant_capability,
    minimal_resolved_config,
    script_mandatory_clear_approval,
)
from tests.unit.test_whole_output_review import _create_run_at_whole_output_review
from tests.unit.test_whole_plan_review import _create_run_at_whole_plan_review

DIGEST = "artifact-digest-current"
DIGEST_STALE = "artifact-digest-stale"


def _closed_verification(*, digest: str = DIGEST) -> FindingVerificationResult:
    return FindingVerificationResult(
        target_digest=digest,
        decision="verified",
        finding_set_id="fs-1",
        finding_results=[
            FindingVerificationEntry(
                finding_id="finding-1",
                disposition="resolved",
                evidence=["closed"],
            )
        ],
        summary="Known findings closed.",
    )


def _clear_blocker(*, digest: str = DIGEST) -> ScopeBlockerReviewResult:
    return ScopeBlockerReviewResult(
        target_digest=digest,
        decision="approve",
        scope_id="whole_plan",
        acceptance_criteria_checked=["Core Invariant"],
        summary="No remaining blockers.",
    )


def test_core_invariant_finding_closure_alone_never_approves() -> None:
    """Final Recommendation: no approval merely because known findings closed."""

    verification = _closed_verification()
    assert (
        is_approval_eligible(
            verification=verification,
            blocker_review=None,
            current_artifact_digest=DIGEST,
        )
        is False
    )

    initial = ReviewLoop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=1,
        scope={"kind": "whole_plan"},
        status="approved",
        findings=[],
        lifecycle_status="findings_closed",
        active_stage="finding_verification",
    )
    assert approved_means_final_approval(initial) is False
    assert approved_means_start_blocker_review(initial) is True

    blocker_pending = prepare_blocker_review_loop(initial)
    assert blocker_pending.active_stage == "scope_blocker_review"
    assert blocker_pending.status == "pending"
    assert approved_means_final_approval(blocker_pending) is True
    fields = stage_package_fields(blocker_pending)
    assert fields["freshness"]["omit_prior_finding_framing"] is True
    assert "findings" not in fields
    assert "finding_set_id" not in fields


def test_core_invariant_requires_verified_clear_blocker_and_digest_match() -> None:
    assert (
        is_approval_eligible(
            verification=_closed_verification(),
            blocker_review=_clear_blocker(),
            current_artifact_digest=DIGEST,
            lifecycle_status="blocker_review_pending",
        )
        is True
    )
    assert (
        is_approval_eligible(
            verification=_closed_verification(digest=DIGEST_STALE),
            blocker_review=_clear_blocker(),
            current_artifact_digest=DIGEST,
        )
        is False
    )
    assert (
        is_approval_eligible(
            verification=_closed_verification(),
            blocker_review=_clear_blocker(digest=DIGEST_STALE),
            current_artifact_digest=DIGEST,
        )
        is False
    )
    assert (
        is_approval_eligible(
            verification=_closed_verification(),
            blocker_review=ScopeBlockerReviewResult(
                target_digest=DIGEST,
                decision="blockers_found",
                scope_id="whole_plan",
                blocking_findings=[
                    ReviewFinding(
                        id="finding-new",
                        importance="blocking",
                        target_refs=["item-a"],
                        issue="Still blocked",
                        required_change="Fix",
                    )
                ],
            ),
            current_artifact_digest=DIGEST,
        )
        is False
    )


@pytest.mark.parametrize("lifecycle", ["limit_reached", "blocked"])
def test_loop_bounds_terminals_never_approve(lifecycle: str) -> None:
    assert (
        is_approval_eligible(
            verification=_closed_verification(),
            blocker_review=_clear_blocker(),
            current_artifact_digest=DIGEST,
            lifecycle_status=lifecycle,
        )
        is False
    )
    limits = MandatoryReviewLimits(max_revision_cycles=1, max_blocker_review_rounds=1)
    exhausted = reject_approval_when_budget_exhausted(
        revision_cycles=1,
        blocker_review_rounds=0,
        limits=limits,
        findings=[
            ReviewFinding(
                id="finding-open",
                importance="blocking",
                target_refs=["item-a"],
                issue="Open",
                required_change="Fix",
            )
        ],
    )
    assert exhausted is not None
    assert exhausted.lifecycle_status == "limit_reached"
    assert exhausted.decision == "blocked"
    assert (
        approval_allowed_under_loop_bounds(
            revision_cycles=1,
            blocker_review_rounds=0,
            limits=limits,
            verification=_closed_verification(),
            blocker_review=_clear_blocker(),
            current_artifact_digest=DIGEST,
            findings=[],
        )
        is False
    )


def test_whole_plan_approval_requires_fresh_blocker_gate(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_plan_review(store, provider=provider)
    run_id = "run-20260101T000301-000301"
    script_mandatory_clear_approval(
        provider,
        store,
        run_id,
        loop_id="review-whole-plan-01",
        phase=WHOLE_PLAN_REVIEW,
        target_revision=0,
    )

    result = WholePlanReviewOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.phase == PLAN_VALIDATED
    review = store.load_review(run_id, "review-whole-plan-01")
    assert review["status"] == "approve"
    assert review["active_stage"] == "scope_blocker_review"
    assert review["blocker_review_rounds"] == 1
    assert review.get("approved_digests")
    assert "plan" in review["approved_digests"]


def test_whole_output_approval_requires_fresh_blocker_gate(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_output_review(store, provider=provider)
    run_id = "run-20260101T000801-000801"
    script_mandatory_clear_approval(
        provider,
        store,
        run_id,
        loop_id="review-whole-output-01",
        phase=WHOLE_OUTPUT_REVIEW,
        target_revision=1,
    )

    result = WholeOutputReviewOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.phase == OUTPUT_VALIDATED
    review = store.load_review(run_id, "review-whole-output-01")
    assert review["status"] == "approve"
    assert review["active_stage"] == "scope_blocker_review"
    assert review["blocker_review_rounds"] == 1
    assert review.get("approved_digests")
    assert "output" in review["approved_digests"]


def test_whole_output_blocker_round_limit_rejects_without_approval(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_output_review(
        store,
        limits={"max_revision_cycles": 5, "max_blocker_review_rounds": 1},
        provider=provider,
    )
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "leaf.txt").write_text("leaf artifact", encoding="utf-8")
    run_id = "run-20260101T000801-000801"
    from tests.helpers import (
        apply_production,
        done_events,
        mandatory_blocker_found_respond_request,
        mandatory_initial_respond_request,
        mandatory_verification_respond_request,
        respond_review,
        script_reviewer_allocate,
        prepare_loop_for_blocker_respond,
    )

    # Initial clear → first blocker finds issues → revise → verify clear →
    # second blocker would be needed but budget is 1.
    script_reviewer_allocate(provider)
    provider.script_turn(
        done_events(text="initial clear"),
        mutate_store=respond_review(
            store,
            run_id,
            mandatory_initial_respond_request(
                store,
                run_id,
                loop_id="review-whole-output-01",
                target_revision=1,
                review_type="whole_output",
            ),
            phase=WHOLE_OUTPUT_REVIEW,
            loop_id="review-whole-output-01",
        ),
    )
    prepare_loop_for_blocker_respond(
        store,
        run_id,
        "review-whole-output-01",
        target_revision=1,
    )
    respond_review(
        store,
        run_id,
        mandatory_blocker_found_respond_request(
            store,
            run_id,
            loop_id="review-whole-output-01",
            target_revision=1,
            review_type="whole_output",
            findings=[
                {
                    "id": "finding-blocker-01",
                    "importance": "blocking",
                    "target_refs": ["item-leaf"],
                    "issue": "Still blocked.",
                    "required_change": "Fix coverage.",
                    "status": "unresolved",
                }
            ],
        ),
        phase=WHOLE_OUTPUT_REVIEW,
        loop_id="review-whole-output-01",
    )()
    apply_production(
        store,
        run_id,
        {
            "production_revision": 2,
            "evidence_revision": True,
            "plan_items": ["item-leaf"],
            "dispositions": {
                "item-leaf": {
                    "disposition": "completed",
                    "evidence": "Addressed blocker.",
                }
            },
            "outputs": [
                {
                    "id": "output-leaf",
                    "type": "artifact",
                    "ref": "artifacts/leaf.txt",
                }
            ],
            "contributions": [
                {
                    "item_id": "item-leaf",
                    "output_refs": ["output-leaf"],
                    "summary": "Revised evidence.",
                }
            ],
            "summary": "Addressed blocker finding.",
        },
        handler="apply",
        phase=WHOLE_OUTPUT_REVIEW,
    )()
    apply_production(
        store,
        run_id,
        {
            "goal_assessment": "Output goal is fully met after revision.",
            "goal_met": True,
        },
        handler="submit_completion",
        phase=WHOLE_OUTPUT_REVIEW,
    )()
    loop = store.load_review(run_id, "review-whole-output-01")
    loop_payload = dict(loop)
    loop_payload["lifecycle_status"] = "verification_pending"
    loop_payload["active_stage"] = "finding_verification"
    loop_payload["status"] = "pending"
    loop_payload["target_revision"] = 2
    loop_payload["finding_set_id"] = str(loop.get("finding_set_id") or "review-whole-output-01-fs-01")
    store.save_review(run_id, loop_payload)
    respond_review(
        store,
        run_id,
        mandatory_verification_respond_request(
            store,
            run_id,
            loop_id="review-whole-output-01",
            target_revision=2,
            review_type="whole_output",
            finding_set_id=str(loop_payload["finding_set_id"]),
            finding_results=[
                {
                    "finding_id": "finding-blocker-01",
                    "disposition": "resolved",
                    "evidence": ["fixed"],
                    "direct_side_effects": [],
                }
            ],
        ),
        phase=WHOLE_OUTPUT_REVIEW,
        loop_id="review-whole-output-01",
    )()

    result = WholeOutputReviewOrchestrator(store, run_id, provider).run()

    assert result.ok is False
    assert result.outcome == "rejected"
    assert "max_blocker_review_rounds" in (result.reason or "")
    run = store.load_run(run_id)
    assert run.get("phase") != OUTPUT_VALIDATED


def test_review_respond_rejects_stale_target_digest(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T003501-003501"
    from top_down_planning.domain.models import Plan, PlanItem

    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        kind="aggregate",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver.",
        items={"item-root": root},
    )
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
        phase=WHOLE_PLAN_REVIEW,
    )
    store.save_review(
        run_id,
        {
            "id": "review-whole-plan-01",
            "type": "whole_plan",
            "reviewer_session_id": "stub-session-reviewer",
            "target_revision": 0,
            "scope": {"kind": "whole_plan"},
            "status": "pending",
            "findings": [],
            "lifecycle_status": "blocker_review_pending",
            "active_stage": "scope_blocker_review",
            "blocker_review_rounds": 1,
        },
    )
    token = grant_capability(
        store,
        run_id,
        role="reviewer",
        phase=WHOLE_PLAN_REVIEW,
        session_kind="reviewer",
        session_id="stub-session-reviewer",
        loop_id="review-whole-plan-01",
    )
    with pytest.raises(RequestError, match="target_digest"):
        ReviewAgentService(store, run_id).respond(
            {
                "loop_id": "review-whole-plan-01",
                "target_revision": 0,
                "stage": "scope_blocker_review",
                "decision": "approve",
                "blocking_findings": [],
                "target_digest": "not-the-current-plan-digest",
                "findings": [],
            },
            capability_token=token,
        )


def test_two_stage_loop_fields_survive_persistence(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T003601-003601"
    from top_down_planning.domain.models import Plan, PlanItem

    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        kind="aggregate",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=2,
        output_goal="Deliver.",
        items={"item-root": root},
    )
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
        phase=WHOLE_PLAN_REVIEW,
    )
    loop = ReviewLoop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess-a",
        target_revision=2,
        scope={"kind": "whole_plan"},
        status="pending",
        findings=[
            ReviewFinding(
                id="finding-1",
                importance="blocking",
                target_refs=["item-root"],
                issue="Gap",
                required_change="Fix",
                status="resolved",
            )
        ],
        revision_cycles=1,
        lifecycle_status="verification_pending",
        active_stage="finding_verification",
        finding_set_id="review-whole-plan-01-fs-02",
        blocker_review_rounds=1,
    )
    store.save_review(run_id, loop.to_dict())
    restored = ReviewLoop.from_dict(store.load_review(run_id, loop.id))
    assert restored.lifecycle_status == "verification_pending"
    assert restored.active_stage == "finding_verification"
    assert restored.finding_set_id == "review-whole-plan-01-fs-02"
    assert restored.blocker_review_rounds == 1
    assert restored.findings[0].status == "resolved"
    assert approved_means_final_approval(restored) is False
