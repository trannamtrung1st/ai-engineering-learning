"""Cross-cutting acceptance: Core Invariant, digests, and Loop Bounds.

Locks Final Recommendation across domain helpers and both mandatory gates:
verified finding closure alone never approves; approval requires a clear fresh
scope_review against the current artifact digest; limit_reached/blocked
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
    ScopeReviewResult,
    apply_discovery_response,
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
    approved_means_start_scope_review,
    prepare_scope_review_loop,
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
    make_review_loop,
    save_review_payload,
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


def _clear_blocker(*, digest: str = DIGEST) -> ScopeReviewResult:
    return ScopeReviewResult(
        target_digest=digest,
        decision="approved",
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
            scope_review_result=None,
            current_artifact_digest=DIGEST,
        )
        is False
    )

    initial = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=1,
        scope={"kind": "whole_plan"},
        status="approved",
        findings=[],
        lifecycle_status="findings_closed",
        active_stage="finding_verification",
        revise_at="blocker",
    )
    assert approved_means_final_approval(initial) is False
    assert approved_means_start_scope_review(initial) is True

    blocker_pending = prepare_scope_review_loop(initial)
    assert blocker_pending.active_stage == "scope_review"
    assert blocker_pending.status == "pending"
    assert approved_means_final_approval(blocker_pending) is True
    fields = stage_package_fields(blocker_pending)
    assert fields["freshness"]["omit_prior_finding_framing"] is True
    assert "findings" not in fields
    assert fields["finding_set_id"] == blocker_pending.finding_set_id
    assert blocker_pending.finding_set_id is not None


def test_scope_review_approval_recorded_requires_approved_result() -> None:
    from top_down_planning.domain.reviews import (
        needs_fresh_scope_review_clear,
        ready_for_mandatory_final_approval,
        scope_review_approval_recorded,
    )

    without_result = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=1,
        scope={"kind": "whole_plan"},
        status="approved",
        active_stage="scope_review",
        lifecycle_status="scope_review_pending",
    )
    assert scope_review_approval_recorded(without_result) is False
    assert needs_fresh_scope_review_clear(without_result) is True
    assert ready_for_mandatory_final_approval(without_result) is False

    with_result = ReviewLoop.from_dict(
        {
            **without_result.to_dict(),
            "scope_review_result": _clear_blocker().to_dict(),
        }
    )
    assert scope_review_approval_recorded(with_result) is True
    assert needs_fresh_scope_review_clear(with_result) is False
    assert ready_for_mandatory_final_approval(with_result) is True

    malformed = ReviewLoop.from_dict(
        {
            **without_result.to_dict(),
            "scope_review_result": {
                "stage": "scope_review",
                "decision": "",
                "target_digest": DIGEST,
                "scope_id": "whole_plan",
            },
        }
    )
    assert scope_review_approval_recorded(malformed) is False


def test_scope_review_advisory_clears_stale_scope_review_result() -> None:
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=1,
        scope={"kind": "whole_plan"},
        status="pending",
        active_stage="scope_review",
        lifecycle_status="scope_review_pending",
        finding_set_id="fs-10",
        scope_review_result=_clear_blocker().to_dict(),
        revise_at="major",
    )
    updated, _findings, outcome = apply_discovery_response(
        loop,
        {
            "finding_set_id": "fs-10",
            "reported_findings": [
                ReviewFinding(
                    id="finding-opt",
                    severity="minor",
                    category="other",
                    target_refs=["item-a"],
                    issue="Optional",
                    recommended_change="Polish",
                ).to_dict()
            ],
            "review_completed": True,
            "summary": "Optional only",
        },
        stage="scope_review",
    )
    assert outcome == "pending"
    assert updated.status == "advisory_pending"
    assert updated.scope_review_result is None


def test_mandatory_gate_next_actor_after_initial_review_advisory() -> None:
    from top_down_planning.domain.reviews import mandatory_gate_next_actor

    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=1,
        scope={"kind": "whole_plan"},
        status="approved",
        lifecycle_status="review_pending",
        active_stage="initial_review",
        revise_at="major",
    )
    assert mandatory_gate_next_actor(loop) == "reviewer"


def test_mandatory_gate_next_actor_omits_reviewer_when_scope_clear_recorded() -> None:
    from top_down_planning.domain.reviews import mandatory_gate_next_actor

    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "whole_plan"},
        status="approved",
        lifecycle_status="scope_review_pending",
        active_stage="scope_review",
        scope_review_result=_clear_blocker().to_dict(),
        revise_at="blocker",
    )
    assert mandatory_gate_next_actor(loop) is None


def test_core_invariant_requires_verified_clear_scope_review_and_digest_match() -> None:
    assert (
        is_approval_eligible(
            verification=_closed_verification(),
            scope_review_result=_clear_blocker(),
            current_artifact_digest=DIGEST,
            lifecycle_status="scope_review_pending",
        )
        is True
    )
    assert (
        is_approval_eligible(
            verification=_closed_verification(digest=DIGEST_STALE),
            scope_review_result=_clear_blocker(),
            current_artifact_digest=DIGEST,
        )
        is False
    )
    assert (
        is_approval_eligible(
            verification=_closed_verification(),
            scope_review_result=_clear_blocker(digest=DIGEST_STALE),
            current_artifact_digest=DIGEST,
        )
        is False
    )
    assert (
        is_approval_eligible(
            verification=_closed_verification(),
            scope_review_result=ScopeReviewResult(
                target_digest=DIGEST,
                decision="changes_requested",
                scope_id="whole_plan",
                reported_findings=[
                    ReviewFinding(
                        id="finding-new",
                        severity="blocker",
                category="other",
                        target_refs=["item-a"],
                        issue="Still blocked",
                        recommended_change="Fix",
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
            scope_review_result=_clear_blocker(),
            current_artifact_digest=DIGEST,
            lifecycle_status=lifecycle,
        )
        is False
    )
    limits = MandatoryReviewLimits(max_revision_cycles=1, max_scope_review_rounds=1)
    exhausted = reject_approval_when_budget_exhausted(
        revision_cycles=1,
        scope_review_rounds=0,
        limits=limits,
        findings=[
            ReviewFinding(
                id="finding-open",
                severity="blocker",
                category="other",
                target_refs=["item-a"],
                issue="Open",
                recommended_change="Fix",
            )
        ],
    )
    assert exhausted is not None
    assert exhausted.lifecycle_status == "limit_reached"
    assert exhausted.decision == "blocked"
    assert (
        approval_allowed_under_loop_bounds(
            revision_cycles=1,
            scope_review_rounds=0,
            limits=limits,
            verification=_closed_verification(),
            scope_review_result=_clear_blocker(),
            current_artifact_digest=DIGEST,
            findings=[],
        )
        is False
    )


def test_whole_plan_approval_requires_fresh_scope_review_gate(tmp_path: Path) -> None:
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
    assert review["status"] == "approved"
    assert review["active_stage"] == "scope_review"
    assert review["scope_review_rounds"] == 1
    assert review.get("approved_digests")
    assert "plan" in review["approved_digests"]


def test_whole_output_approval_requires_fresh_scope_review_gate(tmp_path: Path) -> None:
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
    assert review["status"] == "approved"
    assert review["active_stage"] == "scope_review"
    assert review["scope_review_rounds"] == 1
    assert review.get("approved_digests")
    assert "output" in review["approved_digests"]


def test_whole_output_scope_review_round_limit_rejects_without_approval(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_output_review(
        store,
        limits={"max_revision_cycles": 5, "max_scope_review_rounds": 1},
        provider=provider,
    )
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "leaf.txt").write_text("leaf artifact", encoding="utf-8")
    run_id = "run-20260101T000801-000801"
    from tests.helpers import (
        save_review_payload,
        apply_production,
        done_events,
        enter_mandatory_verification_pending,
        mandatory_scope_review_found_respond_request,
        mandatory_initial_respond_request,
        mandatory_verification_respond_request,
        respond_review,
        prepare_loop_for_scope_review_respond,
    )

    # Initial clear → first blocker finds issues → revise → verify clear →
    # second blocker would be needed but budget is 1.
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
    prepare_loop_for_scope_review_respond(
        store,
        run_id,
        "review-whole-output-01",
        target_revision=1,
    )
    respond_review(
        store,
        run_id,
        mandatory_scope_review_found_respond_request(
            store,
            run_id,
            loop_id="review-whole-output-01",
            target_revision=1,
            review_type="whole_output",
            findings=[
                {
                    "id": "finding-blocker-01",
                    "severity": "blocker",
                    "category": "correctness",
                    "target_refs": ["item-leaf"],
                    "issue": "Still blocked.",
                    "recommended_change": "Fix coverage.",
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
        },
        handler="submit_completion",
        phase=WHOLE_OUTPUT_REVIEW,
    )()
    loop = store.load_review(run_id, "review-whole-output-01")
    finding_set_id = str(loop.get("finding_set_id") or "review-whole-output-01-fs-01")
    enter_mandatory_verification_pending(
        store,
        run_id,
        "review-whole-output-01",
        target_revision=2,
        finding_set_id=finding_set_id,
    )
    respond_review(
        store,
        run_id,
        mandatory_verification_respond_request(
            store,
            run_id,
            loop_id="review-whole-output-01",
            target_revision=2,
            review_type="whole_output",
            finding_set_id=finding_set_id,
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
    assert result.status == "paused"
    assert result.outcome is None
    assert "max_scope_review_rounds" in (result.reason or "")
    run = store.load_run(run_id)
    assert run.get("stop", {}).get("code") == "limit_exhausted"
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
    save_review_payload(store, run_id, {
            "id": "review-whole-plan-01",
            "type": "whole_plan",
            "revise_at": "blocker",
            "reviewer_session_id": "stub-session-reviewer",
            "target_revision": 0,
            "scope": {"kind": "whole_plan"},
            "status": "pending",
            "findings": [],
            "lifecycle_status": "scope_review_pending",
            "active_stage": "scope_review",
            "scope_review_rounds": 1,
            "finding_set_id": "review-whole-plan-01-fs-01",
            "review_record_schema_version": 2,
            "review_contract_version": 2,
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
    from tests.helpers import enrich_whole_plan_review_respond_payload

    with pytest.raises(RequestError, match="target_digest does not match current plan digest"):
        ReviewAgentService(store, run_id).respond(
            enrich_whole_plan_review_respond_payload(
                store,
                run_id,
                {
                    "loop_id": "review-whole-plan-01",
                    "target_revision": 0,
                    "stage": "scope_review",
                    "finding_set_id": "review-whole-plan-01-fs-01",
                    "reported_findings": [],
                    "review_completed": True,
                    "target_digest": "not-the-current-plan-digest",
                    "scope_id": "whole_plan",
                    "summary": "clear",
                },
            ),
            capability_token=token,
        )


def test_mandatory_review_loop_fields_survive_persistence(tmp_path: Path) -> None:
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
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess-a",
        target_revision=2,
        scope={"kind": "whole_plan"},
        status="pending",
        findings=[
            ReviewFinding(
                id="finding-1",
                severity="blocker",
                category="other",
                target_refs=["item-root"],
                issue="Gap",
                recommended_change="Fix",
                status="resolved",
            )
        ],
        revision_cycles=1,
        lifecycle_status="verification_pending",
        active_stage="finding_verification",
        finding_set_id="review-whole-plan-01-fs-02",
        scope_review_rounds=1,
        revise_at="blocker",
    )
    save_review_payload(store, run_id, loop.to_dict())
    restored = ReviewLoop.from_dict(store.load_review(run_id, loop.id))
    assert restored.lifecycle_status == "verification_pending"
    assert restored.active_stage == "finding_verification"
    assert restored.finding_set_id == "review-whole-plan-01-fs-02"
    assert restored.scope_review_rounds == 1
    assert restored.findings[0].status == "resolved"
    assert approved_means_final_approval(restored) is False
