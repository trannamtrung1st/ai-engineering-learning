"""Mandatory review gate orchestration coverage."""

from __future__ import annotations

from pathlib import Path

from top_down_planning.orchestrator import WholePlanReviewOrchestrator, WholeOutputReviewOrchestrator
from top_down_planning.orchestrator.phases import PLAN_VALIDATED, OUTPUT_VALIDATED, WHOLE_PLAN_REVIEW
from top_down_planning.persistence import FileRunStore
from core_tools.provider import StubProvider
from tests.helpers import (
    apply_plan,
    done_events,
    enter_mandatory_verification_pending,
    prepare_loop_for_scope_review_respond,
    mandatory_scope_review_found_respond_request,
    mandatory_initial_respond_request,
    mandatory_verification_respond_request,
    respond_review,
    script_verification_then_scope_review_approval,
)
from tests.unit.test_whole_plan_review import _create_run_at_whole_plan_review
from tests.unit.test_whole_output_review import _create_run_at_whole_output_review


def test_whole_plan_clear_path_requires_scope_review(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_plan_review(store, provider=provider)
    run_id = "run-20260101T000301-000301"
    from tests.integration.e2e_helpers import script_whole_plan_review

    script_whole_plan_review(provider, store, run_id, decision="approved")

    result = WholePlanReviewOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.phase == PLAN_VALIDATED
    review = store.load_review(run_id, "review-whole-plan-01")
    assert review["active_stage"] == "scope_review"
    assert review["scope_review_rounds"] == 1
    assert review["status"] == "approved"
    events = store.load_events(run_id)
    started = [event for event in events if event.get("type") == "reviewer_session_started"]
    resumed = [event for event in events if event.get("type") == "reviewer_session_resumed"]
    ended = [event for event in events if event.get("type") == "reviewer_session_ended"]
    assert len(started) == 2
    assert len(resumed) == 0
    assert len(ended) == 2
    assert started[0]["stage"] == "initial_review"
    assert started[1]["stage"] == "scope_review"
    assert any(event.get("type") == "whole_plan_scope_review_started" for event in events)


def test_whole_plan_scope_review_reopen_returns_to_verification(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_plan_review(store, provider=provider)
    run_id = "run-20260101T000301-000301"

    respond_review(
        store,
        run_id,
        mandatory_initial_respond_request(
            store,
            run_id,
            loop_id="review-whole-plan-01",
            target_revision=0,
            review_type="whole_plan",
        ),
        phase=WHOLE_PLAN_REVIEW,
        loop_id="review-whole-plan-01",
    )()
    prepare_loop_for_scope_review_respond(
        store,
        run_id,
        "review-whole-plan-01",
        target_revision=0,
    )
    respond_review(
        store,
        run_id,
        mandatory_scope_review_found_respond_request(
            store,
            run_id,
            loop_id="review-whole-plan-01",
            target_revision=0,
            review_type="whole_plan",
            findings=[
                {
                    "id": "finding-blocker-01",
                    "severity": "blocker",
                    "category": "correctness",
                    "target_refs": ["item-api"],
                    "issue": "Missing deliverable coverage.",
                    "recommended_change": "Add leaf acceptance.",
                    "status": "unresolved",
                }
            ],
        ),
        phase=WHOLE_PLAN_REVIEW,
        loop_id="review-whole-plan-01",
    )()
    apply_plan(
        store,
        run_id,
        base_revision=0,
        operations=[
            {
                "op": "update_item",
                "item_id": "item-api",
                "patch": {
                    "acceptance": ["API behavior is verifiable.", "Health check exists."]
                },
            }
        ],
        phase=WHOLE_PLAN_REVIEW,
    )()
    script_verification_then_scope_review_approval(
        provider,
        store,
        run_id,
        loop_id="review-whole-plan-01",
        phase=WHOLE_PLAN_REVIEW,
        target_revision=1,
    )

    result = WholePlanReviewOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.phase == PLAN_VALIDATED
    review = store.load_review(run_id, "review-whole-plan-01")
    assert review["scope_review_rounds"] == 2
    assert review["finding_set_id"]


def test_whole_plan_scope_review_round_limit_rejects(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_plan_review(
        store,
        limits={"max_revision_cycles": 5, "max_scope_review_rounds": 1},
        provider=provider,
    )
    run_id = "run-20260101T000301-000301"

    respond_review(
        store,
        run_id,
        mandatory_initial_respond_request(
            store,
            run_id,
            loop_id="review-whole-plan-01",
            target_revision=0,
            review_type="whole_plan",
        ),
        phase=WHOLE_PLAN_REVIEW,
        loop_id="review-whole-plan-01",
    )()
    prepare_loop_for_scope_review_respond(
        store,
        run_id,
        "review-whole-plan-01",
        target_revision=0,
    )
    respond_review(
        store,
        run_id,
        mandatory_scope_review_found_respond_request(
                store,
                run_id,
                loop_id="review-whole-plan-01",
                target_revision=0,
                review_type="whole_plan",
                findings=[
                    {
                        "id": "finding-blocker-01",
                        "severity": "blocker",
                        "category": "correctness",
                        "target_refs": ["item-api"],
                        "issue": "Still blocked.",
                        "recommended_change": "Fix coverage.",
                        "status": "unresolved",
                    }
                ],
        ),
        phase=WHOLE_PLAN_REVIEW,
        loop_id="review-whole-plan-01",
    )()
    apply_plan(
        store,
        run_id,
        base_revision=0,
        operations=[
            {
                "op": "update_item",
                "item_id": "item-api",
                "patch": {"acceptance": ["API behavior is verifiable.", "Extra."]},
            }
        ],
        phase=WHOLE_PLAN_REVIEW,
    )()
    loop = store.load_review(run_id, "review-whole-plan-01")
    enter_mandatory_verification_pending(
        store,
        run_id,
        "review-whole-plan-01",
        target_revision=1,
        finding_set_id=str(loop.get("finding_set_id") or "fs-1"),
    )
    respond_review(
        store,
        run_id,
        mandatory_verification_respond_request(
            store,
            run_id,
            loop_id="review-whole-plan-01",
            target_revision=1,
            review_type="whole_plan",
            finding_set_id=str(loop.get("finding_set_id") or "fs-1"),
            finding_results=[
                {
                    "finding_id": "finding-blocker-01",
                    "disposition": "resolved",
                    "evidence": ["fixed"],
                    "direct_side_effects": [],
                }
            ],
        ),
        phase=WHOLE_PLAN_REVIEW,
        loop_id="review-whole-plan-01",
    )()

    result = WholePlanReviewOrchestrator(store, run_id, provider).run()

    assert result.ok is False
    assert result.status == "paused"
    assert result.outcome is None
    assert "max_scope_review_rounds" in (result.reason or "")
    run = store.load_run(run_id)
    assert run.get("stop", {}).get("code") == "limit_exhausted"
    review = store.load_review(run_id, "review-whole-plan-01")
    assert review.get("lifecycle_status") == "limit_reached"


def test_whole_output_clear_path_requires_scope_review(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_output_review(store, provider=provider)
    run_id = "run-20260101T000801-000801"
    from tests.integration.e2e_helpers import script_whole_output_review

    script_whole_output_review(provider, store, run_id, decision="approved")

    result = WholeOutputReviewOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.phase == OUTPUT_VALIDATED
    review = store.load_review(run_id, "review-whole-output-01")
    assert review["active_stage"] == "scope_review"
    assert review["scope_review_rounds"] == 1
    assert review["status"] == "approved"
    events = store.load_events(run_id)
    started = [event for event in events if event.get("type") == "reviewer_session_started"]
    resumed = [event for event in events if event.get("type") == "reviewer_session_resumed"]
    ended = [event for event in events if event.get("type") == "reviewer_session_ended"]
    assert len(started) == 2
    assert len(resumed) == 0
    assert len(ended) == 2
    assert started[0]["stage"] == "initial_review"
    assert started[1]["stage"] == "scope_review"
    assert any(event.get("type") == "whole_output_scope_review_started" for event in events)
