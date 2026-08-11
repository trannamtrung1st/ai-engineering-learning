"""Tests for bounded reviewer session release after terminal review decisions."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core_tools.provider import StubProvider
from core_tools.provider.errors import ProviderTurnError
from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.orchestrator import ProviderRunError, RunEngine, WholeOutputReviewOrchestrator, WholePlanReviewOrchestrator
from top_down_planning.orchestrator.phases import PLAN_VALIDATED, WHOLE_OUTPUT_REVIEW, WHOLE_PLAN_REVIEW
from top_down_planning.observability import ObservabilityContext
from top_down_planning.orchestrator.session_events import (
    end_reviewer_session_with_audit,
    release_reviewer_session_after_decision,
    reviewer_session_audit_fields,
    sync_reviewer_loop_session_id,
)
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.session_bindings import binding_provider_session_id
from tests.helpers import (
    make_review_loop,
    done_events,
    mandatory_initial_respond_request,
    respond_review,
    save_review_payload,
)
from tests.integration.e2e_helpers import script_whole_plan_review
from tests.unit.test_whole_plan_review import _create_run_at_whole_plan_review
from tests.unit.test_whole_output_review import _create_run_at_whole_output_review


def test_reviewer_session_audit_fields_includes_stage_for_mandatory_only() -> None:
    mandatory = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "whole_plan"},
        active_stage="finding_verification",
    )
    focused = make_review_loop(
        id="review-focused-plan-01",
        type="focused_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "focused_plan", "item_ids": ["item-a"]},
    )
    assert reviewer_session_audit_fields(mandatory) == {
        "loop_id": "review-whole-plan-01",
        "review_type": "whole_plan",
        "stage": "finding_verification",
    }
    assert reviewer_session_audit_fields(focused) == {
        "loop_id": "review-focused-plan-01",
        "review_type": "focused_plan",
    }


def test_release_reviewer_session_after_decision_releases_on_terminal_status(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T009903-009903"
    _create_run_at_whole_plan_review(store, run_id=run_id)
    provider = StubProvider()
    provider.script_turn(done_events(text="review session registered"))
    session_id = provider.start_reviewer_session({"loop_id": "review-whole-plan-01"})
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id=session_id,
        target_revision=0,
        scope={"kind": "whole_plan"},
        revise_at="blocker",
        status="approved",
        active_stage="scope_review",
    )
    save_review_payload(store, run_id, loop.to_dict())
    events: list[dict] = []

    def append_event(event_type: str, **fields: object) -> None:
        events.append({"type": event_type, **fields})

    decision = release_reviewer_session_after_decision(
        append_event,
        provider,
        store,
        run_id,
        phase=WHOLE_PLAN_REVIEW,
        loop_id="review-whole-plan-01",
        session_id=session_id,
    )

    assert decision == "approved"
    assert provider.list_active_sessions() == []
    assert events[0]["type"] == "reviewer_session_ended"
    assert events[0]["stage"] == "scope_review"
    assert events[0]["review_type"] == "whole_plan"


def test_end_reviewer_session_with_audit_terminates_and_records_event() -> None:
    provider = StubProvider()
    provider.script_turn(done_events(text="review session registered"))
    session_id = provider.start_reviewer_session({"loop_id": "review-01"})
    events: list[dict] = []

    def append_event(event_type: str, **fields: object) -> None:
        events.append({"type": event_type, **fields})

    canonical = end_reviewer_session_with_audit(
        append_event,
        provider,
        phase=WHOLE_PLAN_REVIEW,
        session_id=session_id,
        loop_id="review-01",
        review_type="whole_plan",
    )

    assert canonical.session_id == session_id
    assert provider.list_active_sessions() == []
    assert len(events) == 1
    assert events[0]["type"] == "reviewer_session_ended"
    assert events[0]["session_id"] == session_id
    assert events[0]["role"] == "reviewer"
    assert events[0]["phase"] == WHOLE_PLAN_REVIEW
    assert events[0]["loop_id"] == "review-01"


def test_end_reviewer_session_with_audit_is_idempotent() -> None:
    provider = StubProvider()
    provider.script_turn(done_events(text="review session registered"))
    session_id = provider.start_reviewer_session({"loop_id": "review-01"})
    append_event = MagicMock()

    end_reviewer_session_with_audit(
        append_event,
        provider,
        phase=WHOLE_PLAN_REVIEW,
        session_id=session_id,
    )
    end_reviewer_session_with_audit(
        append_event,
        provider,
        phase=WHOLE_PLAN_REVIEW,
        session_id=session_id,
    )

    assert provider.list_active_sessions() == []
    assert append_event.call_count == 1


def test_sync_reviewer_loop_session_id_before_release(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T009901-009901"
    _create_run_at_whole_plan_review(store, run_id=run_id)
    provider = StubProvider()
    provider.script_turn(done_events(text="review session registered"))
    session_id = provider.start_reviewer_session({"loop_id": "review-whole-plan-01"})
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id=session_id,
        target_revision=0,
        scope={"kind": "whole_plan"},
        revise_at="blocker",
    )
    save_review_payload(store, run_id, loop.to_dict())

    canonical = sync_reviewer_loop_session_id(
        provider,
        store,
        run_id,
        "review-whole-plan-01",
        session_id,
    )
    events: list[dict] = []

    def append_event(event_type: str, **fields: object) -> None:
        events.append({"type": event_type, **fields})

    end_reviewer_session_with_audit(
        append_event,
        provider,
        phase=WHOLE_PLAN_REVIEW,
        session_id=session_id,
        loop_id="review-whole-plan-01",
        review_type="whole_plan",
    )

    review = store.load_review(run_id, "review-whole-plan-01")
    assert binding_provider_session_id(review.get("reviewer_binding")) == canonical
    assert provider.list_active_sessions() == []
    assert events[0]["session_id"] == canonical


def test_completed_reviewer_turn_releases_session_before_phase_return(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_plan_review(store, provider=provider)
    run_id = "run-20260101T000301-000301"
    script_whole_plan_review(provider, store, run_id, decision="approved")

    result = WholePlanReviewOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.phase == PLAN_VALIDATED
    reviewer_sessions = [
        session
        for session in provider.list_active_sessions()
        if session.get("role") == "reviewer"
    ]
    assert reviewer_sessions == []
    ended = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == "reviewer_session_ended"
    ]
    assert len(ended) == 2


def test_reviewer_auto_retries_when_turn_ends_without_decision(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000301-000301"
    _create_run_at_whole_plan_review(store, run_id=run_id, provider=provider)
    provider.script_turn(done_events(text="review turn without respond"))
    script_whole_plan_review(provider, store, run_id, decision="approved")

    result = WholePlanReviewOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.phase == PLAN_VALIDATED
    events = store.load_events(run_id)
    assert any(event.get("type") == "reviewer_gate_turn_retried" for event in events)


def test_reviewer_gate_turn_limit_pauses_run(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000301-000301"
    _create_run_at_whole_plan_review(
        store,
        run_id=run_id,
        provider=provider,
        limits={"review": {"max_agent_turns_per_gate": 1}},
    )
    provider.script_turn(done_events(text="review turn without respond"))

    result = WholePlanReviewOrchestrator(store, run_id, provider).run()

    assert result.ok is False
    run = store.load_run(run_id)
    assert run["status"] == "paused"
    assert run["stop"]["code"] == "limit_exhausted"
    assert (
        run["stop"]["details"]["limit"] == "limits.review.max_agent_turns_per_gate"
    )
    events = store.load_events(run_id)
    assert any(event.get("type") == "reviewer_gate_turns_exhausted" for event in events)


def test_run_engine_does_not_duplicate_reviewer_session_ended(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_plan_review(store, provider=provider)
    run_id = "run-20260101T000301-000301"
    script_whole_plan_review(provider, store, run_id, decision="approved")

    engine = RunEngine(
        store,
        create_provider=lambda _config, _workspace: provider,
        observability=ObservabilityContext(run_id=run_id),
    )
    result = engine.continue_run(run_id, single_step=True)

    assert result.ok is True
    assert result.phase == PLAN_VALIDATED
    ended = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == "reviewer_session_ended"
    ]
    assert len(ended) == 2
    assert not any(
        session.get("role") == "reviewer"
        for session in provider.list_active_sessions()
    )


def test_whole_plan_recheck_resumes_after_changes_requested_release(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_plan_review(
        store,
        provider=provider,
        limits={"review": {"max_agent_turns_per_gate": 1}},
    )
    run_id = "run-20260101T000301-000301"
    provider.script_turn(
        done_events(text="review turn"),
        mutate_store=respond_review(
            store,
            run_id,
            mandatory_initial_respond_request(
                store,
                run_id,
                loop_id="review-whole-plan-01",
                target_revision=0,
                review_type="whole_plan",
                findings=[
                    {
                        "id": "finding-01",
                        "severity": "blocker",
                        "category": "other",
                        "target_refs": ["item-api"],
                        "issue": "API outcome is too vague.",
                        "recommended_change": "Add concrete acceptance criteria.",
                        "status": "unresolved",
                    }
                ],
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id="review-whole-plan-01",
        ),
    )

    provider.script_turn(done_events(text="planner revises after findings"))
    provider.script_turn(done_events(text="verification recheck queued"))

    result = WholePlanReviewOrchestrator(store, run_id, provider).run()
    assert result.ok is False
    assert store.load_run(run_id)["stop"]["code"] == "limit_exhausted"

    review = store.load_review(run_id, "review-whole-plan-01")
    canonical = binding_provider_session_id(review.get("reviewer_binding"))
    events = store.load_events(run_id)
    ended = [event for event in events if event.get("type") == "reviewer_session_ended"]
    resumed = [
        event for event in events if event.get("type") == "reviewer_session_resumed"
    ]

    assert canonical
    assert ended
    assert ended[0]["session_id"] == canonical
    assert resumed
    assert any(event["session_id"] == canonical for event in resumed)
    assert canonical in provider._sessions


def test_reviewer_turn_aborts_inflight_stream_when_decision_recorded(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    aborted_sessions: list[str] = []

    class _AbortTrackingProvider(StubProvider):
        def abort_turn(self, session_id: str) -> None:
            aborted_sessions.append(session_id)
            super().abort_turn(session_id)

    provider = _AbortTrackingProvider()
    _create_run_at_whole_output_review(store, provider=provider)
    run_id = "run-20260101T000801-000801"
    production = store.load_production(run_id)
    target_revision = int(production["output_revision"])

    provider.script_turn(
        [
            {"type": "assistant", "text": "reviewing output"},
            {"type": "assistant", "text": "still streaming without done"},
        ],
        mutate_store=respond_review(
            store,
            run_id,
            mandatory_initial_respond_request(
                store,
                run_id,
                loop_id="review-whole-output-01",
                target_revision=target_revision,
                review_type="whole_output",
                decision="changes_requested",
                findings=[
                    {
                        "id": "finding-01",
                        "severity": "blocker",
                        "category": "correctness",
                        "target_refs": ["item-leaf"],
                        "issue": "Output evidence is missing.",
                        "recommended_change": "Add artifact reference.",
                        "status": "unresolved",
                    }
                ],
            ),
            phase=WHOLE_OUTPUT_REVIEW,
            loop_id="review-whole-output-01",
        ),
    )

    with pytest.raises((ProviderRunError, ProviderTurnError)):
        WholeOutputReviewOrchestrator(store, run_id, provider).run()

    assert aborted_sessions
    events = store.load_events(run_id)
    ended = [event for event in events if event.get("type") == "reviewer_session_ended"]
    assert ended
    assert not any(
        session.get("role") == "reviewer"
        for session in provider.list_active_sessions()
    )
