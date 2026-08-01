"""Tests for bounded reviewer session release after terminal review decisions."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core_tools.provider import StubProvider
from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.orchestrator import ProviderRunError, RunEngine, WholePlanReviewOrchestrator
from top_down_planning.orchestrator.phases import PLAN_VALIDATED, WHOLE_PLAN_REVIEW
from top_down_planning.observability import ObservabilityContext
from top_down_planning.orchestrator.session_events import (
    end_reviewer_session_with_audit,
    release_reviewer_session_after_decision,
    sync_reviewer_loop_session_id,
)
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.session_bindings import binding_provider_session_id
from tests.helpers import (
    make_review_loop,
    done_events,
    mandatory_initial_respond_request,
    respond_review,
    script_reviewer_allocate,
)
from tests.integration.e2e_helpers import script_whole_plan_review
from tests.unit.test_whole_plan_review import _create_run_at_whole_plan_review


def test_release_reviewer_session_after_decision_releases_on_terminal_status(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T009903-009903"
    _create_run_at_whole_plan_review(store, run_id=run_id)
    provider = StubProvider()
    script_reviewer_allocate(provider)
    session_id = provider.start_reviewer_session({"loop_id": "review-whole-plan-01"})
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id=session_id,
        target_revision=0,
        scope={"kind": "whole_plan"},
        revise_at="blocker",
        status="approved",
    )
    store.save_review(run_id, loop.to_dict())
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
        review_type="whole_plan",
        session_id=session_id,
    )

    assert decision == "approved"
    assert provider.list_active_sessions() == []
    assert events[0]["type"] == "reviewer_session_ended"


def test_end_reviewer_session_with_audit_terminates_and_records_event() -> None:
    provider = StubProvider()
    script_reviewer_allocate(provider)
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

    assert canonical == session_id
    assert provider.list_active_sessions() == []
    assert len(events) == 1
    assert events[0]["type"] == "reviewer_session_ended"
    assert events[0]["session_id"] == session_id
    assert events[0]["role"] == "reviewer"
    assert events[0]["phase"] == WHOLE_PLAN_REVIEW
    assert events[0]["loop_id"] == "review-01"


def test_end_reviewer_session_with_audit_is_idempotent() -> None:
    provider = StubProvider()
    script_reviewer_allocate(provider)
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
    script_reviewer_allocate(provider)
    session_id = provider.start_reviewer_session({"loop_id": "review-whole-plan-01"})
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id=session_id,
        target_revision=0,
        scope={"kind": "whole_plan"},
        revise_at="blocker",
    )
    store.save_review(run_id, loop.to_dict())

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


def test_pending_reviewer_turn_does_not_release_session(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_plan_review(store, provider=provider)
    run_id = "run-20260101T000301-000301"
    script_reviewer_allocate(provider)
    provider.script_turn(done_events(text="review turn without respond"))

    with pytest.raises(ProviderRunError, match="without a decision"):
        WholePlanReviewOrchestrator(store, run_id, provider).run()

    assert provider.list_active_sessions()
    ended = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == "reviewer_session_ended"
    ]
    assert ended == []


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
    _create_run_at_whole_plan_review(store, provider=provider)
    run_id = "run-20260101T000301-000301"
    script_reviewer_allocate(provider)
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

    with pytest.raises(ProviderRunError, match="without a decision"):
        WholePlanReviewOrchestrator(store, run_id, provider).run()

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
