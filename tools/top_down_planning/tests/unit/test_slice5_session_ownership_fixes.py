"""Slice 5 durable-ID uniqueness, termination ownership, and poller regressions."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core_tools.provider import StubProvider
from core_tools.provider.errors import ProviderSessionError
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.session_lineage import SESSION_PROVIDER_ID_BOUND
from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.orchestrator.provider_turns import LiteralBoundarySignal, _drain_provider_turn
from top_down_planning.orchestrator.session_events import (
    end_primary_session_with_audit,
    end_reviewer_session_with_audit,
    sync_persisted_session_id,
    sync_reviewer_loop_session_id,
)
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, done_events, make_review_loop, save_review_payload


def _sample_plan() -> Plan:
    return Plan(
        id="plan-slice5-ownership",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Root",
                kind="aggregate",
            )
        },
    )


def _create_run(store: FileRunStore, run_id: str) -> dict:
    return store.create_run(
        run_id,
        plan=_sample_plan(),
        **create_run_kwargs(store.root),
    )


def _save_reviewer_loop(
    store: FileRunStore,
    run_id: str,
    *,
    loop_id: str,
    session_id: str | None,
) -> None:
    loop = make_review_loop(
        id=loop_id,
        type="whole_plan",
        reviewer_session_id=session_id,
        target_revision=0,
        scope={"kind": "whole_plan"},
        revise_at="blocker",
    )
    save_review_payload(store, run_id, loop.to_dict())


def _stub_provider(turn_count: int = 2) -> StubProvider:
    provider = StubProvider()
    for _ in range(turn_count):
        provider.script_turn(done_events(text="session registered"))
    return provider


def _lineage_roles(store: FileRunStore, run_id: str) -> list[str]:
    return [
        str(event.get("role"))
        for event in store.load_events(run_id)
        if event.get("type") == SESSION_PROVIDER_ID_BOUND
    ]


class _BlockingStreamProvider:
    def __init__(
        self,
        *,
        abort_error: BaseException | None = None,
        yield_first: bool = False,
    ) -> None:
        self.released = threading.Event()
        self.aborted: list[str] = []
        self.abort_error = abort_error
        self.yield_first = yield_first

    def stream_events(self, session_id: str):
        if self.yield_first:
            yield {"type": "assistant", "text": "hi"}
        self.released.wait(timeout=30)
        return
        yield

    def abort_turn(self, session_id: str, *, timeout: float = 2.0) -> None:
        self.aborted.append(session_id)
        self.released.set()
        if self.abort_error is not None:
            raise self.abort_error

    def wait_turn_settled(self, session_id: str, *, timeout: float = 30.0) -> None:
        return

    def canonical_session_id(self, session_id: str) -> str:
        return session_id


def test_reviewer_durable_id_collision_with_planner_fails_closed(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T005101-005101"
    _create_run(store, run_id)
    provider = _stub_provider()
    planner_id = provider.start_primary_session("planner", {"goal": "x"})
    from top_down_planning.orchestrator.session_events import (
        commit_primary_provider_session_binding,
    )

    commit_primary_provider_session_binding(
        store,
        run_id,
        role="planner",
        provider_session_id=planner_id,
        provider="stub",
    )
    reviewer_id = provider.start_reviewer_session({"loop_id": "review-whole-plan-01"})
    _save_reviewer_loop(
        store,
        run_id,
        loop_id="review-whole-plan-01",
        session_id=reviewer_id,
    )
    before_review = store.load_review(run_id, "review-whole-plan-01")
    before_run = store.load_run(run_id)
    before_tokens = list(getattr(provider, "_capability_token", None) and [provider._capability_token] or [])

    with pytest.raises(ProviderSessionError):
        sync_reviewer_loop_session_id(
            provider,
            store,
            run_id,
            "review-whole-plan-01",
            planner_id,
        )

    after_review = store.load_review(run_id, "review-whole-plan-01")
    after_run = store.load_run(run_id)
    assert after_review["revision"] == before_review["revision"]
    assert after_run["revision"] == before_run["revision"]
    assert after_run["sessions"] == before_run["sessions"]
    assert "reviewer" not in _lineage_roles(store, run_id)
    assert provider._capability_token == (before_tokens[0] if before_tokens else None)
    assert planner_id in {s["session_id"] for s in provider.list_active_sessions()}
    assert reviewer_id in {s["session_id"] for s in provider.list_active_sessions()}


def test_reviewer_durable_id_collision_with_producer_fails_closed(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T005102-005102"
    _create_run(store, run_id)
    provider = _stub_provider()
    producer_id = provider.start_primary_session("producer", {"goal": "x"})
    from top_down_planning.orchestrator.session_events import (
        commit_primary_provider_session_binding,
    )

    commit_primary_provider_session_binding(
        store,
        run_id,
        role="producer",
        provider_session_id=producer_id,
        provider="stub",
    )
    reviewer_id = provider.start_reviewer_session({"loop_id": "review-whole-plan-01"})
    _save_reviewer_loop(
        store,
        run_id,
        loop_id="review-whole-plan-01",
        session_id=reviewer_id,
    )

    with pytest.raises(ProviderSessionError):
        sync_reviewer_loop_session_id(
            provider,
            store,
            run_id,
            "review-whole-plan-01",
            producer_id,
        )
    assert reviewer_id in {s["session_id"] for s in provider.list_active_sessions()}
    assert producer_id in {s["session_id"] for s in provider.list_active_sessions()}


def test_planner_durable_id_collision_with_reviewer_fails_closed(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T005103-005103"
    _create_run(store, run_id)
    provider = _stub_provider()
    reviewer_id = provider.start_reviewer_session({"loop_id": "review-whole-plan-01"})
    _save_reviewer_loop(
        store,
        run_id,
        loop_id="review-whole-plan-01",
        session_id=reviewer_id,
    )
    sync_reviewer_loop_session_id(
        provider,
        store,
        run_id,
        "review-whole-plan-01",
        reviewer_id,
    )
    planner_id = provider.start_primary_session("planner", {"goal": "x"})
    before_run = store.load_run(run_id)
    before_review = store.load_review(run_id, "review-whole-plan-01")

    with pytest.raises(ProviderSessionError):
        sync_persisted_session_id(
            provider,
            store,
            run_id,
            reviewer_id,
            role="planner",
        )

    after_run = store.load_run(run_id)
    after_review = store.load_review(run_id, "review-whole-plan-01")
    assert after_run["revision"] == before_run["revision"]
    assert after_review["revision"] == before_review["revision"]
    assert planner_id in {s["session_id"] for s in provider.list_active_sessions()}
    assert reviewer_id in {s["session_id"] for s in provider.list_active_sessions()}


def test_same_logical_session_canonicalization_is_idempotent(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T005104-005104"
    _create_run(store, run_id)
    provider = _stub_provider()
    planner_id = provider.start_primary_session("planner", {"goal": "x"})
    first = sync_persisted_session_id(
        provider, store, run_id, planner_id, role="planner"
    )
    second = sync_persisted_session_id(
        provider, store, run_id, planner_id, role="planner"
    )
    assert first == planner_id
    assert second == planner_id

    reviewer_id = provider.start_reviewer_session({"loop_id": "review-whole-plan-01"})
    _save_reviewer_loop(
        store,
        run_id,
        loop_id="review-whole-plan-01",
        session_id=reviewer_id,
    )
    once = sync_reviewer_loop_session_id(
        provider, store, run_id, "review-whole-plan-01", reviewer_id
    )
    twice = sync_reviewer_loop_session_id(
        provider, store, run_id, "review-whole-plan-01", reviewer_id
    )
    assert once == reviewer_id
    assert twice == reviewer_id


def test_reviewer_termination_rejects_planner_session(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T005105-005105"
    _create_run(store, run_id)
    provider = _stub_provider()
    planner_id = provider.start_primary_session("planner", {"goal": "x"})
    reviewer_id = provider.start_reviewer_session({"loop_id": "review-01"})
    append_event = MagicMock()
    with patch.object(provider, "terminate_session", wraps=provider.terminate_session) as terminate:
        with pytest.raises(ProviderSessionError):
            end_reviewer_session_with_audit(
                append_event,
                provider,
                phase="whole_plan_review",
                session_id=planner_id,
            )
        terminate.assert_not_called()
    active = {s["session_id"] for s in provider.list_active_sessions()}
    assert planner_id in active
    assert reviewer_id in active
    append_event.assert_not_called()


def test_reviewer_termination_rejects_producer_session(tmp_path: Path) -> None:
    provider = _stub_provider()
    producer_id = provider.start_primary_session("producer", {"goal": "x"})
    append_event = MagicMock()
    with patch.object(provider, "terminate_session", wraps=provider.terminate_session) as terminate:
        with pytest.raises(ProviderSessionError):
            end_reviewer_session_with_audit(
                append_event,
                provider,
                phase="production",
                session_id=producer_id,
            )
        terminate.assert_not_called()
    assert producer_id in {s["session_id"] for s in provider.list_active_sessions()}
    ended_types = [call.args[0] for call in append_event.call_args_list]
    assert "reviewer_session_ended" not in ended_types


def test_primary_termination_rejects_reviewer_session(tmp_path: Path) -> None:
    provider = _stub_provider()
    reviewer_id = provider.start_reviewer_session({"loop_id": "review-01"})
    append_event = MagicMock()
    with patch.object(provider, "terminate_session", wraps=provider.terminate_session) as terminate:
        with pytest.raises(ProviderSessionError):
            end_primary_session_with_audit(
                append_event,
                provider,
                role="planner",
                phase="planning",
                session_id=reviewer_id,
            )
        terminate.assert_not_called()
    assert reviewer_id in {s["session_id"] for s in provider.list_active_sessions()}
    ended_types = [call.args[0] for call in append_event.call_args_list]
    assert "planner_session_ended" not in ended_types


def test_drain_aborts_after_event_without_hanging() -> None:
    provider = _BlockingStreamProvider(yield_first=True)

    started = time.monotonic()
    signal = _drain_provider_turn(
        provider,
        "sess-1",
        allowed_signals=frozenset(),
        on_boundary=LiteralBoundarySignal("paused"),
    )
    assert time.monotonic() - started < 1.0
    assert signal == "paused"
    assert "sess-1" in provider.aborted


def test_boundary_callback_exception_reaches_drain_owner() -> None:
    provider = _BlockingStreamProvider()

    with pytest.raises(RuntimeError, match="boundary failed"):
        _drain_provider_turn(
            provider,
            "sess-1",
            allowed_signals=frozenset(),
            on_boundary=LiteralBoundarySignal(error="boundary failed"),
        )


def test_blocking_boundary_callback_cannot_hang_join() -> None:
    provider = _BlockingStreamProvider()

    started = time.monotonic()
    _drain_provider_turn(
        provider,
        "sess-1",
        allowed_signals=frozenset(),
        on_boundary=LiteralBoundarySignal("paused"),
    )
    assert time.monotonic() - started < 1.0
    assert [
        thread
        for thread in threading.enumerate()
        if thread.name == "tdp-boundary-poll" and thread.is_alive()
    ] == []
    provider.released.set()


def test_poller_abort_exception_reaches_drain_owner() -> None:
    provider = _BlockingStreamProvider(abort_error=RuntimeError("abort failed"))

    with pytest.raises(RuntimeError, match="abort failed"):
        _drain_provider_turn(
            provider,
            "sess-1",
            allowed_signals=frozenset(),
            on_boundary=LiteralBoundarySignal("paused"),
        )


def test_normal_idle_boundary_aborts_and_stops_poller() -> None:
    provider = _BlockingStreamProvider()

    signal = _drain_provider_turn(
        provider,
        "sess-1",
        allowed_signals=frozenset(),
        on_boundary=LiteralBoundarySignal("batch_closed"),
    )
    assert signal == "batch_closed"
    assert "sess-1" in provider.aborted
    assert provider.released.is_set()
