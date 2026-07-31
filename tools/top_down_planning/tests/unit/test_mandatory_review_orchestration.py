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
    prepare_loop_for_blocker_respond,
    mandatory_blocker_found_respond_request,
    mandatory_initial_respond_request,
    mandatory_verification_respond_request,
    respond_review,
    script_reviewer_allocate,
    script_verification_then_blocker_approval,
)
from tests.unit.test_whole_plan_review import _create_run_at_whole_plan_review
from tests.unit.test_whole_output_review import _create_run_at_whole_output_review


def test_whole_plan_clear_path_requires_blocker_review(tmp_path: Path) -> None:
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
    assert len(started) == 2
    assert len(resumed) == 0
    assert any(event.get("type") == "whole_plan_scope_review_started" for event in events)


def test_whole_plan_blocker_reopen_returns_to_verification(tmp_path: Path) -> None:
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
    prepare_loop_for_blocker_respond(
        store,
        run_id,
        "review-whole-plan-01",
        target_revision=0,
    )
    respond_review(
        store,
        run_id,
        mandatory_blocker_found_respond_request(
            store,
            run_id,
            loop_id="review-whole-plan-01",
            target_revision=0,
            review_type="whole_plan",
            findings=[
                {
                    "id": "finding-blocker-01",
                    "importance": "blocking",
                    "target_refs": ["item-api"],
                    "issue": "Missing deliverable coverage.",
                    "required_change": "Add leaf acceptance.",
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
    script_verification_then_blocker_approval(
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


def test_whole_plan_blocker_round_limit_rejects(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_plan_review(
        store,
        limits={"max_revision_cycles": 5, "max_blocker_review_rounds": 1},
        provider=provider,
    )
    run_id = "run-20260101T000301-000301"

    script_reviewer_allocate(provider)
    provider.script_turn(
        done_events(text="initial clear"),
        mutate_store=respond_review(
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
        ),
    )
    prepare_loop_for_blocker_respond(
        store,
        run_id,
        "review-whole-plan-01",
        target_revision=0,
    )
    script_reviewer_allocate(provider)
    provider.script_turn(
        done_events(text="blockers found"),
        mutate_store=respond_review(
            store,
            run_id,
            mandatory_blocker_found_respond_request(
                store,
                run_id,
                loop_id="review-whole-plan-01",
                target_revision=0,
                review_type="whole_plan",
                findings=[
                    {
                        "id": "finding-blocker-01",
                        "importance": "blocking",
                        "target_refs": ["item-api"],
                        "issue": "Still blocked.",
                        "required_change": "Fix coverage.",
                        "status": "unresolved",
                    }
                ],
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id="review-whole-plan-01",
        ),
    )
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
    loop_payload = dict(loop)
    loop_payload["lifecycle_status"] = "verification_pending"
    loop_payload["active_stage"] = "finding_verification"
    loop_payload["status"] = "pending"
    loop_payload["target_revision"] = 1
    store.save_review(run_id, loop_payload)
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
    assert result.outcome == "rejected"
    assert "max_scope_review_rounds" in (result.reason or "")
    review = store.load_review(run_id, "review-whole-plan-01")
    assert review.get("lifecycle_status") == "limit_reached"


def test_whole_output_clear_path_requires_blocker_review(tmp_path: Path) -> None:
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
    assert len(started) == 2
    assert len(resumed) == 0
    assert any(event.get("type") == "whole_output_scope_review_started" for event in events)
