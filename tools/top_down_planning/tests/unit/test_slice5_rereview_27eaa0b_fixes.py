"""Slice 5 rereview 27eaa0b: cooperative cancellation, durable replacement identity."""

from __future__ import annotations

import signal
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.persistence import PersistenceError
from core_tools.provider.errors import ProviderTurnError
from top_down_planning.domain.session_lineage import (
    SESSION_REPLACED,
    SESSION_REPLACEMENT_FAILED,
)
from top_down_planning.orchestrator.errors import (
    ProviderRunError,
    SessionRecoveryExhausted,
)
from top_down_planning.orchestrator.phases import PLANNING, WHOLE_PLAN_REVIEW
from tests.helpers import done_events, make_review_loop
from top_down_planning.orchestrator.provider_turns import (
    _drain_provider_turn,
    _invoke_boundary_bounded,
    build_planner_turn_recovery,
    build_reviewer_turn_recovery,
    consume_provider_turn_with_session_recovery,
    consume_reviewer_provider_turn_with_session_recovery,
    LiteralBoundarySignal,
)
from top_down_planning.orchestrator.session_context import ensure_primary_session
from top_down_planning.orchestrator.session_events import discard_unbound_provider_session
from top_down_planning.orchestrator.session_recovery import (
    replace_primary_session,
    replace_reviewer_session,
)
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.session_bindings import get_primary_binding
from tests.unit.test_slice5_rereview_2af6712b_fixes import _lineage
from tests.unit.test_slice5_rereview_c947561_fixes import _PendingSameIdStub
from tests.unit.test_slice5_rereview_ee5de8e_fixes import (
    _ForcedIdStub,
    _RecordingDrainProvider,
    _active_ids,
    _create_run,
    _requested,
    _save_reviewer_loop,
    _scripted,
)


class _PendingSameIdOnStreamStub(_PendingSameIdStub):
    def __init__(self) -> None:
        super().__init__()
        self._first_id: str | None = None

    def start_primary_session(self, role, request, *, model=None):
        session_id = super().start_primary_session(role, request, model=model)
        if self._starts == 1:
            self._first_id = session_id
        return session_id

    def start_reviewer_session(self, request, *, model=None):
        session_id = super().start_reviewer_session(request, model=model)
        if self._starts == 1:
            self._first_id = session_id
        return session_id

    def stream_events(self, session_id):
        if session_id == self.pending_id and self._first_id is not None:
            self.aliases[self.pending_id] = self._first_id
        yield from super().stream_events(session_id)


class _TerminateReturnsStillActive(_ForcedIdStub):
    def __init__(self, *, sticky_id: str) -> None:
        super().__init__()
        self.sticky_id = sticky_id

    def terminate_session(self, session_id: str, *, timeout: float = 2.0) -> None:
        canonical = self.canonical_session_id(session_id)
        if canonical == self.sticky_id or session_id == self.sticky_id:
            return
        return super().terminate_session(session_id, timeout=timeout)


class _TimeoutAwareInternalTypeError:
    def __init__(self) -> None:
        self.invocations = 0

    def terminate_session(self, session_id: str, *, timeout: float) -> None:
        del timeout
        self.invocations += 1
        self._side_effect = session_id
        raise TypeError("internal")

    def canonical_session_id(self, session_id: str) -> str:
        return session_id

    def list_active_sessions(self):
        return [{"session_id": "sess-typed"}]


def test_discard_preserves_internal_typeerror_from_timeout_aware_terminate() -> None:
    provider = _TimeoutAwareInternalTypeError()
    with pytest.raises(TypeError, match="internal") as caught:
        discard_unbound_provider_session(
            provider,
            "sess-typed",
            preexisting_ids=set(),
            timeout=0.1,
        )
    assert provider.invocations == 1
    assert caught.value.__cause__ is None
    assert "must accept timeout=" not in str(caught.value)


class SleepThenOk:
    def __call__(self) -> str | None:
        time.sleep(0.15)
        return "ok"


def test_boundary_probe_does_not_extend_preexisting_itimer() -> None:
    if not hasattr(signal, "setitimer"):
        pytest.skip("ITIMER_REAL is unavailable")

    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    fired = {"n": 0}

    def _on_alrm(_signum, _frame) -> None:
        fired["n"] += 1

    previous = signal.signal(signal.SIGALRM, _on_alrm)
    worker = BoundaryWorker()
    worker.start()
    try:
        signal.setitimer(signal.ITIMER_REAL, 0.5)
        try:
            result = worker.invoke(SleepThenOk(), timeout=1.0)
            remaining, _interval = signal.getitimer(signal.ITIMER_REAL)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
    finally:
        signal.signal(signal.SIGALRM, previous)
        worker.close()
    assert result == "ok"
    assert remaining == 0 or remaining < 0.45


def test_drain_from_non_main_thread_never_uses_async_exc() -> None:
    errors: list[BaseException] = []
    result: list[str | None] = []

    def worker() -> None:
        try:
            with patch("ctypes.pythonapi.PyThreadState_SetAsyncExc") as async_exc:
                outcome = _drain_provider_turn(
                    _RecordingDrainProvider(
                        yield_event={"type": "done", "text": "ok"}
                    ),
                    "sess-worker",
                    allowed_signals=frozenset(),
                    on_boundary=LiteralBoundarySignal("paused"),
                )
                result.append(outcome)
                if async_exc.call_count:
                    errors.append(AssertionError("SetAsyncExc was used"))
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert errors == []
    assert result == ["paused"]


def test_primary_consume_rejects_same_id_replacement_without_session_replaced(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T040101-040101"
    _create_run(store, run_id)
    provider = _scripted(_PendingSameIdOnStreamStub())
    old_id = ensure_primary_session(
        store,
        run_id,
        provider,
        role="planner",
        phase="planning",
        requested=_requested("planner"),
        manifest={"goal": "x"},
        append_event=lambda *_a, **_k: None,
        resume_request={"goal": "x"},
    )
    provider.mark_session_stalled(old_id)
    provider.script_turn(done_events(text="replacement turn"))
    started_generation = get_primary_binding(store.load_run(run_id), "planner").generation
    with pytest.raises(SessionRecoveryExhausted):
        consume_provider_turn_with_session_recovery(
            store,
            run_id,
            provider,
            old_id,
            allowed_signals=frozenset(),
            recovery=build_planner_turn_recovery(
                store,
                run_id,
                phase=PLANNING,
                expected_next_action="continue planning",
                append_event=lambda *_a, **_k: None,
                model="test-model",
            ),
        )
    run = store.load_run(run_id)
    assert run["status"] == "failed"
    assert run["stop"]["code"] == "session_recovery_exhausted"
    replaced = _lineage(store, run_id, SESSION_REPLACED)
    failed = _lineage(store, run_id, SESSION_REPLACEMENT_FAILED)
    assert replaced == []
    assert len(failed) == 1
    assert failed[0]["generation"] != started_generation
    assert failed[0]["reason"] == "replacement_identity_conflict"
    binding = get_primary_binding(run, "planner")
    assert binding is not None
    assert binding.provider_session_id != old_id
    assert provider.pending_id not in _active_ids(provider)
    assert old_id not in _active_ids(provider)


def test_reviewer_consume_rejects_same_id_replacement_without_session_replaced(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T040102-040102"
    _create_run(store, run_id)
    provider = _scripted(_PendingSameIdOnStreamStub())
    old_id = provider.start_reviewer_session({"loop_id": "review-whole-plan-01"})
    _save_reviewer_loop(store, run_id, loop_id="review-whole-plan-01", session_id=old_id)
    provider.mark_session_stalled(old_id)
    provider.script_turn(done_events(text="replacement reviewer"))
    with pytest.raises(SessionRecoveryExhausted):
        consume_reviewer_provider_turn_with_session_recovery(
            store,
            run_id,
            provider,
            old_id,
            loop_id="review-whole-plan-01",
            recovery=build_reviewer_turn_recovery(
                store,
                run_id,
                loop_id="review-whole-plan-01",
                phase=WHOLE_PLAN_REVIEW,
                expected_next_action="continue review",
                append_event=lambda *_a, **_k: None,
                model="test-model",
                review_package={"loop_id": "review-whole-plan-01"},
            ),
        )
    run = store.load_run(run_id)
    assert run["status"] == "failed"
    assert run["stop"]["code"] == "session_recovery_exhausted"
    assert _lineage(store, run_id, SESSION_REPLACED) == []
    failed = _lineage(store, run_id, SESSION_REPLACEMENT_FAILED)
    assert len(failed) == 1
    assert failed[0]["reason"] == "replacement_identity_conflict"
    assert provider.pending_id not in _active_ids(provider)


def _replace_kwargs(old_id: str) -> dict:
    return {
        "role": "planner",
        "phase": "planning",
        "old_provider_session_id": old_id,
        "phase_action_id": "action-still-active",
        "append_event": lambda *_a, **_k: None,
        "model": "test-model",
        "manifest": {"goal": "x"},
    }


def test_primary_release_still_active_fails_run_with_lineage(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T040202-040202"
    _create_run(store, run_id)
    base = _scripted(_ForcedIdStub())
    old_id = ensure_primary_session(
        store,
        run_id,
        base,
        role="planner",
        phase="planning",
        requested=_requested("planner"),
        manifest={"goal": "x"},
        append_event=lambda *_a, **_k: None,
        resume_request={"goal": "x"},
    )
    provider = _TerminateReturnsStillActive(sticky_id=old_id)
    provider._sessions = base._sessions
    _scripted(provider)
    with pytest.raises(ProviderRunError, match="still active"):
        replace_primary_session(store, run_id, provider, **_replace_kwargs(old_id))
    run = store.load_run(run_id)
    assert run["status"] == "failed"
    assert run["stop"]["code"] == "state_integrity_failure"
    failed = _lineage(store, run_id, SESSION_REPLACEMENT_FAILED)
    assert len(failed) == 1
    assert failed[0]["reason"] == "orchestrator_invariant_failure"
    candidates = [sid for sid in _active_ids(provider) if sid != old_id]
    assert candidates == []


def test_reviewer_release_still_active_fails_run_with_lineage(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T040203-040203"
    _create_run(store, run_id)
    base = _scripted(_ForcedIdStub())
    old_id = base.start_reviewer_session({"loop_id": "review-whole-plan-01"})
    _save_reviewer_loop(store, run_id, loop_id="review-whole-plan-01", session_id=old_id)
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id=old_id,
        target_revision=0,
        scope={"kind": "whole_plan"},
        revise_at="blocker",
    )
    provider = _TerminateReturnsStillActive(sticky_id=old_id)
    provider._sessions = base._sessions
    _scripted(provider)
    with pytest.raises(ProviderRunError, match="still active"):
        replace_reviewer_session(
            store,
            run_id,
            provider,
            loop=loop,
            phase="whole_plan_review",
            old_provider_session_id=old_id,
            phase_action_id="action-r-still-active",
            append_event=lambda *_a, **_k: None,
            model="test-model",
            manifest={"loop_id": "review-whole-plan-01"},
        )
    run = store.load_run(run_id)
    assert run["status"] == "failed"
    assert run["stop"]["code"] == "state_integrity_failure"
    failed = _lineage(store, run_id, SESSION_REPLACEMENT_FAILED)
    assert len(failed) == 1
    assert failed[0]["reason"] == "orchestrator_invariant_failure"


def test_recording_failure_preserves_original_provider_cause(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T040301-040301"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    old_id = ensure_primary_session(
        store,
        run_id,
        provider,
        role="planner",
        phase="planning",
        requested=_requested("planner"),
        manifest={"goal": "x"},
        append_event=lambda *_a, **_k: None,
        resume_request={"goal": "x"},
    )

    def boom_start(*_a, **_k):
        raise ProviderTurnError("provider timeout")

    provider.start_primary_session = boom_start  # type: ignore[method-assign]
    with patch(
        "top_down_planning.orchestrator.session_recovery.emit_session_replacement_failed",
        side_effect=PersistenceError("lineage write failed"),
    ):
        with pytest.raises(PersistenceError, match="lineage write failed") as caught:
            replace_primary_session(store, run_id, provider, **_replace_kwargs(old_id))
    assert isinstance(caught.value.__cause__, ProviderTurnError)
    assert "provider timeout" in str(caught.value.__cause__)


def test_recording_failure_preserves_original_persistence_cause(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T040302-040302"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    old_id = ensure_primary_session(
        store,
        run_id,
        provider,
        role="planner",
        phase="planning",
        requested=_requested("planner"),
        manifest={"goal": "x"},
        append_event=lambda *_a, **_k: None,
        resume_request={"goal": "x"},
    )
    with patch(
        "top_down_planning.orchestrator.session_recovery.assert_expected_run_revision",
        side_effect=PersistenceError("load after generation write"),
    ), patch(
        "top_down_planning.orchestrator.session_recovery.emit_session_replacement_failed",
        side_effect=PersistenceError("lineage write failed"),
    ):
        with pytest.raises(PersistenceError, match="lineage write failed") as caught:
            replace_primary_session(store, run_id, provider, **_replace_kwargs(old_id))
    assert isinstance(caught.value.__cause__, PersistenceError)
    assert "load after generation write" in str(caught.value.__cause__)


def test_recording_failure_preserves_original_invariant_cause(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T040303-040303"
    _create_run(store, run_id)
    base = _scripted(_ForcedIdStub())
    old_id = ensure_primary_session(
        store,
        run_id,
        base,
        role="planner",
        phase="planning",
        requested=_requested("planner"),
        manifest={"goal": "x"},
        append_event=lambda *_a, **_k: None,
        resume_request={"goal": "x"},
    )
    provider = _TerminateReturnsStillActive(sticky_id=old_id)
    provider._sessions = base._sessions
    _scripted(provider)
    with patch(
        "top_down_planning.orchestrator.session_recovery.emit_session_replacement_failed",
        side_effect=PersistenceError("lineage write failed"),
    ):
        with pytest.raises(PersistenceError, match="lineage write failed") as caught:
            replace_primary_session(store, run_id, provider, **_replace_kwargs(old_id))
    assert isinstance(caught.value.__cause__, ProviderRunError)
    assert "still active" in str(caught.value.__cause__)
