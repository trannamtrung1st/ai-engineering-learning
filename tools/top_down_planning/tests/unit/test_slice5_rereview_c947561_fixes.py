"""Slice 5 rereview c947561: bounded lifecycle, fail-closed publish, replacement identity."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.persistence import PersistenceError
from core_tools.provider.errors import ProviderSessionError
from top_down_planning.domain.session_lineage import (
    SESSION_PROVIDER_ID_BOUND,
    SESSION_REPLACED,
    SESSION_REPLACEMENT_FAILED,
    SESSION_REPLACEMENT_STARTED,
)
from top_down_planning.orchestrator.errors import ProviderRunError, SessionRecoveryPaused
from top_down_planning.orchestrator.provider_turns import (
    BOUNDARY_POLL_THREAD_NAME,
    _abort_provider_turn,
    _drain_provider_turn,
    _invoke_boundary_bounded,
)
from top_down_planning.orchestrator.reviewer_session import begin_reviewer_review
from top_down_planning.orchestrator.session_context import rotate_primary_session
from top_down_planning.orchestrator.session_events import (
    discard_if_unpublished,
    discard_unbound_provider_session,
    end_reviewer_session_with_audit,
    sync_persisted_session_id,
    sync_reviewer_loop_session_id,
)
from top_down_planning.orchestrator.session_recovery import (
    replace_primary_session,
    replace_reviewer_session,
)
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.commit import CommitSpec
from top_down_planning.persistence.session_bindings import get_primary_binding
from tests.helpers import make_review_loop
from tests.unit.test_slice5_rereview_2af6712b_fixes import _helper_threads, _lineage
from tests.unit.test_slice5_rereview_ee5de8e_fixes import (
    _ForcedIdStub,
    _active_ids,
    _create_run,
    _requested,
    _save_reviewer_loop,
    _scripted,
)


class _OldProtocolHangProvider:
    def __init__(self) -> None:
        self.invocations: list[str] = []

    def abort_turn(self, session_id: str) -> None:
        self.invocations.append(f"abort:{session_id}")
        threading.Event().wait()

    def terminate_session(self, session_id: str) -> None:
        self.invocations.append(f"terminate:{session_id}")
        threading.Event().wait()

    def wait_turn_settled(self, session_id: str, timeout: float = 30.0) -> None:
        return


class _TimeoutAwareTypeErrorProvider:
    def __init__(self) -> None:
        self.invocations: list[str] = []

    def abort_turn(self, session_id: str, *, timeout: float) -> None:
        self.invocations.append(f"abort:{session_id}:{timeout}")
        raise TypeError("internal after first invoke")

    def terminate_session(self, session_id: str, *, timeout: float) -> None:
        self.invocations.append(f"terminate:{session_id}:{timeout}")
        raise TypeError("internal after first invoke")

    def wait_turn_settled(self, session_id: str, *, timeout: float = 30.0) -> None:
        return


class _IgnoreLifecycleStreamProvider:
    def __init__(self) -> None:
        self._stop = threading.Event()

    def stream_events(self, session_id: str):
        while not self._stop.wait(timeout=0.05):
            pass
        return
        yield {"type": "done", "text": "never"}

    def abort_turn(self, session_id: str, *, timeout: float = 2.0) -> None:
        return

    def wait_turn_settled(self, session_id: str, *, timeout: float = 30.0) -> None:
        return

    def terminate_session(self, session_id: str, *, timeout: float = 2.0) -> None:
        return

    def canonical_session_id(self, session_id: str) -> str:
        return session_id


class _DiscardBoomStub(_ForcedIdStub):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.protected_ids: set[str] = set()

    def terminate_session(self, session_id: str, *, timeout: float = 2.0) -> None:
        canonical = self.canonical_session_id(session_id)
        if canonical in self.protected_ids or session_id in self.protected_ids:
            return super().terminate_session(session_id, timeout=timeout)
        raise RuntimeError(f"discard boom {session_id}")


class _PendingSameIdStub(_ForcedIdStub):
    def __init__(self) -> None:
        super().__init__()
        self._starts = 0
        self.pending_id = "cursor-pending-2"

    def start_primary_session(self, role, request, *, model=None):
        self._starts += 1
        session_id = super().start_primary_session(role, request, model=model or "test-model")
        if self._starts >= 2:
            session = self._sessions.pop(session_id)
            self._sessions[self.pending_id] = session
            return self.pending_id
        return session_id

    def start_reviewer_session(self, request, *, model=None):
        self._starts += 1
        session_id = super().start_reviewer_session(request, model=model or "test-model")
        if self._starts >= 2:
            session = self._sessions.pop(session_id)
            self._sessions[self.pending_id] = session
            return self.pending_id
        return session_id


def test_old_protocol_lifecycle_is_not_retried_unbounded() -> None:
    provider = _OldProtocolHangProvider()
    started = time.monotonic()
    with pytest.raises(TypeError):
        _abort_provider_turn(provider, "sess-old")
    assert time.monotonic() - started < 1.0
    assert provider.invocations == []


def test_timeout_aware_internal_typeerror_invokes_lifecycle_once() -> None:
    provider = _TimeoutAwareTypeErrorProvider()
    with pytest.raises(TypeError, match="internal after first invoke"):
        _abort_provider_turn(provider, "sess-typed")
    with pytest.raises(TypeError, match="internal after first invoke"):
        from top_down_planning.orchestrator.provider_turns import _terminate_provider_session

        _terminate_provider_session(provider, "sess-typed")
    assert provider.invocations == [
        "abort:sess-typed:2.0",
        "terminate:sess-typed:2.0",
    ]


def test_boundary_callback_that_ignores_cancel_leaves_no_helper() -> None:
    from tests.unit.test_slice5_rereview_41a27ee_fixes import NeverReturnBoundary

    stop = threading.Event()
    with patch("ctypes.pythonapi.PyThreadState_SetAsyncExc") as async_exc:
        with pytest.raises(ProviderRunError, match="boundary probe exceeded timeout"):
            _invoke_boundary_bounded(NeverReturnBoundary(), stop, timeout=0.4)
    assert async_exc.call_count == 0
    survivors = [
        thread
        for thread in threading.enumerate()
        if thread.name == BOUNDARY_POLL_THREAD_NAME and thread.is_alive()
    ]
    assert survivors == []


def test_event_pump_is_stopped_when_stream_ignores_abort_and_terminate() -> None:
    pytest.skip("covered by test_cursor_drain_abort_leaves_no_event_pump")


def test_rejected_candidate_hanging_terminate_is_bounded() -> None:
    provider = _scripted(_ForcedIdStub())

    def hang_terminate(session_id: str, *, timeout: float = 2.0) -> None:
        threading.Event().wait(timeout=timeout)

    provider.terminate_session = hang_terminate  # type: ignore[method-assign]
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    started = time.monotonic()
    with pytest.raises(ProviderSessionError, match="still active"):
        discard_unbound_provider_session(
            provider,
            session_id,
            preexisting_ids=set(),
            timeout=0.1,
        )
    assert time.monotonic() - started < 2.0


def test_reviewer_release_hanging_terminate_is_bounded(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T030101-030101"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    reviewer_id = provider.start_reviewer_session(
        {"loop_id": "review-whole-plan-01"},
        model="test-model",
    )
    _save_reviewer_loop(store, run_id, loop_id="review-whole-plan-01", session_id=reviewer_id)

    def hang_terminate(session_id: str, *, timeout: float = 2.0) -> None:
        threading.Event().wait(timeout=timeout)

    provider.terminate_session = hang_terminate  # type: ignore[method-assign]
    started = time.monotonic()
    result = end_reviewer_session_with_audit(
        lambda *_a, **_k: None,
        provider,
        phase="whole_plan_review",
        session_id=reviewer_id,
        store=store,
        run_id=run_id,
        binding_loop_id="review-whole-plan-01",
        loop_id="review-whole-plan-01",
    )
    assert time.monotonic() - started < 3.0
    assert result.ended is False


def test_primary_rotation_hanging_old_terminate_is_bounded(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T030102-030102"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    from top_down_planning.orchestrator.session_context import ensure_primary_session

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

    def hang_old(session_id: str, *, timeout: float = 2.0) -> None:
        if session_id == old_id:
            threading.Event().wait(timeout=timeout)
            return
        type(provider).terminate_session(provider, session_id, timeout=timeout)

    provider.terminate_session = hang_old  # type: ignore[method-assign]
    started = time.monotonic()
    with pytest.raises(ProviderRunError, match="teardown failed"):
        rotate_primary_session(
            store,
            run_id,
            provider,
            role="planner",
            phase="planning",
            old_provider_session_id=old_id,
            requested=_requested("planner"),
            manifest={"goal": "x"},
            append_event=lambda *_a, **_k: None,
        )
    assert time.monotonic() - started < 3.0


def test_replacement_old_session_hanging_terminate_is_bounded(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T030103-030103"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    from top_down_planning.orchestrator.session_context import ensure_primary_session

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

    def hang_old(session_id: str, *, timeout: float = 2.0) -> None:
        if session_id == old_id:
            threading.Event().wait(timeout=timeout)
            return
        type(provider).terminate_session(provider, session_id, timeout=timeout)

    provider.terminate_session = hang_old  # type: ignore[method-assign]
    started = time.monotonic()
    with patch(
        "top_down_planning.orchestrator.session_events.DEFAULT_PROVIDER_LIFECYCLE_TIMEOUT_SECONDS",
        0.1,
    ):
        with pytest.raises((ProviderRunError, ProviderSessionError, TimeoutError, TypeError)):
            replace_primary_session(
                store,
                run_id,
                provider,
                role="planner",
                phase="planning",
                old_provider_session_id=old_id,
                phase_action_id="action-replace-hang",
                append_event=lambda *_a, **_k: None,
                model="test-model",
                manifest={"goal": "x"},
            )
    assert time.monotonic() - started < 3.0


def test_reviewer_sync_repairs_missing_bound_event_and_capability(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T030201-030201"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    session_id = provider.start_reviewer_session({"loop_id": "review-whole-plan-01"})
    _save_reviewer_loop(store, run_id, loop_id="review-whole-plan-01", session_id=session_id)
    assert _lineage(store, run_id, SESSION_PROVIDER_ID_BOUND) == []
    resolved = sync_reviewer_loop_session_id(
        provider, store, run_id, "review-whole-plan-01", session_id
    )
    assert resolved == session_id
    bound = _lineage(store, run_id, SESSION_PROVIDER_ID_BOUND)
    assert len(bound) == 1
    caps = store.list_capabilities(run_id)
    assert any(cap.get("role") == "reviewer" for cap in caps)


def test_reviewer_sync_retries_after_event_staging_failure(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T030202-030202"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    session_id = provider.start_reviewer_session({"loop_id": "review-whole-plan-01"})
    _save_reviewer_loop(store, run_id, loop_id="review-whole-plan-01", session_id=None)
    real_commit = store.commit
    failed = {"once": False}

    def fail_bound_event(run_id: str, spec: CommitSpec):
        if (
            not failed["once"]
            and spec.events
            and any(event.get("type") == SESSION_PROVIDER_ID_BOUND for event in spec.events)
        ):
            failed["once"] = True
            raise PersistenceError("event staging")
        return real_commit(run_id, spec)

    with patch.object(store, "commit", fail_bound_event):
        with pytest.raises(PersistenceError, match="event staging"):
            sync_reviewer_loop_session_id(
                provider, store, run_id, "review-whole-plan-01", session_id
            )
    sync_reviewer_loop_session_id(
        provider, store, run_id, "review-whole-plan-01", session_id
    )
    bound = _lineage(store, run_id, SESSION_PROVIDER_ID_BOUND)
    assert len(bound) == 1
    assert bound[0]["provider_session_id"] == session_id


def test_reviewer_sync_retries_after_capability_rebind_failure(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T030203-030203"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    session_id = provider.start_reviewer_session({"loop_id": "review-whole-plan-01"})
    _save_reviewer_loop(store, run_id, loop_id="review-whole-plan-01", session_id=None)
    failed = {"once": False}

    def boom_then_ok(*args, **kwargs):
        if not failed["once"]:
            failed["once"] = True
            raise PersistenceError("capability rebind")
        from top_down_planning.orchestrator.capability import (
            rebind_reviewer_session_capability as real,
        )

        return real(*args, **kwargs)

    with patch(
        "top_down_planning.orchestrator.session_events.rebind_reviewer_session_capability",
        boom_then_ok,
    ):
        with pytest.raises(PersistenceError, match="capability rebind"):
            sync_reviewer_loop_session_id(
                provider, store, run_id, "review-whole-plan-01", session_id
            )
    sync_reviewer_loop_session_id(
        provider, store, run_id, "review-whole-plan-01", session_id
    )
    bound = _lineage(store, run_id, SESSION_PROVIDER_ID_BOUND)
    assert len(bound) == 1
    caps = store.list_capabilities(run_id)
    assert any(cap.get("role") == "reviewer" for cap in caps)


def test_unknown_publication_does_not_terminate_reviewer_session(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T030301-030301"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    session_id = provider.start_reviewer_session({"loop_id": "review-whole-plan-01"})
    _save_reviewer_loop(store, run_id, loop_id="review-whole-plan-01", session_id=session_id)

    def boom_load(run_id: str, loop_id: str):
        raise OSError("review unreadable")

    with patch.object(store, "load_review", boom_load):
        with pytest.raises(PersistenceError, match="publication state unknown"):
            discard_if_unpublished(
                provider,
                store,
                run_id,
                session_id,
                preexisting_ids=set(),
                role="reviewer",
                loop_id="review-whole-plan-01",
            )
    assert session_id in _active_ids(provider)


def test_malformed_review_payload_does_not_discard_candidate(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T030302-030302"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    session_id = provider.start_reviewer_session({"loop_id": "review-whole-plan-01"})
    _save_reviewer_loop(store, run_id, loop_id="review-whole-plan-01", session_id=session_id)

    def malformed(run_id: str, loop_id: str):
        return {"id": loop_id, "revision": 1}

    with patch.object(store, "load_review", malformed):
        with pytest.raises(PersistenceError, match="publication state unknown"):
            discard_if_unpublished(
                provider,
                store,
                run_id,
                session_id,
                preexisting_ids=set(),
                role="reviewer",
                loop_id="review-whole-plan-01",
            )
    assert session_id in _active_ids(provider)


def test_begin_reviewer_unknown_verify_does_not_terminate(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T030303-030303"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    _save_reviewer_loop(store, run_id, loop_id="review-whole-plan-01", session_id=None)
    real_commit = store.commit
    loads = {"n": 0}
    real_load = store.load_review

    def commit_then_fail(run_id: str, spec: CommitSpec):
        real_commit(run_id, spec)
        raise PersistenceError("post-commit verify")

    def load_then_unknown(run_id: str, loop_id: str):
        loads["n"] += 1
        if loads["n"] > 2:
            raise OSError("verify read")
        return real_load(run_id, loop_id)

    with patch.object(store, "commit", commit_then_fail), patch.object(
        store, "load_review", load_then_unknown
    ):
        with pytest.raises(PersistenceError):
            begin_reviewer_review(
                provider,
                store,
                run_id,
                loop_id="review-whole-plan-01",
                review_package={"loop_id": "review-whole-plan-01"},
                phase="whole_plan_review",
            )
    leftover = _active_ids(provider)
    assert leftover


def _assert_cleanup_note(exc: BaseException) -> None:
    notes = getattr(exc, "__notes__", [])
    assert any("cleanup:" in str(note) for note in notes)


def test_primary_provider_error_still_pauses_when_discard_fails(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T030401-030401"
    _create_run(store, run_id)
    provider = _scripted(_DiscardBoomStub())
    from top_down_planning.orchestrator.session_context import ensure_primary_session

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
    provider.protected_ids.add(old_id)
    with patch(
        "top_down_planning.orchestrator.session_recovery.validate_provider_session_binding",
        side_effect=ProviderSessionError("bad replacement bind", session_id="x"),
    ):
        with pytest.raises(SessionRecoveryPaused) as caught:
            replace_primary_session(
                store,
                run_id,
                provider,
                role="planner",
                phase="planning",
                old_provider_session_id=old_id,
                phase_action_id="action-replace-08a",
                append_event=lambda *_a, **_k: None,
                model="test-model",
                manifest={"goal": "x"},
            )
    _assert_cleanup_note(caught.value)
    run = store.load_run(run_id)
    assert run["status"] == "paused"
    assert run["stop"]["code"] == "provider_unavailable"
    failed = _lineage(store, run_id, SESSION_REPLACEMENT_FAILED)
    assert failed and failed[-1]["reason"] == "provider_unavailable"


def test_primary_persistence_error_still_fails_when_discard_fails(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T030402-030402"
    _create_run(store, run_id)
    provider = _scripted(_DiscardBoomStub())
    from top_down_planning.orchestrator.session_context import ensure_primary_session

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
    provider.protected_ids.add(old_id)
    real_commit = store.commit

    def fail_generation_write(run_id: str, spec: CommitSpec):
        if spec.events and any(
            event.get("type") == SESSION_REPLACEMENT_STARTED for event in spec.events
        ):
            raise PersistenceError("generation write")
        return real_commit(run_id, spec)

    with patch.object(store, "commit", fail_generation_write):
        with pytest.raises(PersistenceError, match="generation write") as caught:
            replace_primary_session(
                store,
                run_id,
                provider,
                role="planner",
                phase="planning",
                old_provider_session_id=old_id,
                phase_action_id="action-replace-08b",
                append_event=lambda *_a, **_k: None,
                model="test-model",
                manifest={"goal": "x"},
            )
    _assert_cleanup_note(caught.value)
    run = store.load_run(run_id)
    assert run["status"] == "failed"
    assert run["stop"]["code"] == "state_integrity_failure"
    failed = _lineage(store, run_id, SESSION_REPLACEMENT_FAILED)
    assert failed and failed[-1]["reason"] == "persistence_failure"


def test_primary_invariant_error_keeps_lineage_when_discard_fails(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T030403-030403"
    _create_run(store, run_id)
    provider = _scripted(_DiscardBoomStub())
    from top_down_planning.orchestrator.session_context import ensure_primary_session

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
    provider.protected_ids.add(old_id)

    def boom(*args, **kwargs):
        raise RuntimeError("invariant after started")

    with patch(
        "top_down_planning.orchestrator.session_recovery.emit_primary_session_started",
        boom,
    ):
        with pytest.raises(RuntimeError, match="invariant after started") as caught:
            replace_primary_session(
                store,
                run_id,
                provider,
                role="planner",
                phase="planning",
                old_provider_session_id=old_id,
                phase_action_id="action-replace-08c",
                append_event=lambda *_a, **_k: None,
                model="test-model",
                manifest={"goal": "x"},
            )
    _assert_cleanup_note(caught.value)
    failed = _lineage(store, run_id, SESSION_REPLACEMENT_FAILED)
    started = _lineage(store, run_id, SESSION_REPLACEMENT_STARTED)
    assert started
    assert failed and failed[-1]["generation"] == started[-1]["generation"]
    assert failed[-1]["reason"] == "orchestrator_invariant_failure"


def test_reviewer_provider_error_still_pauses_when_discard_fails(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T030404-030404"
    _create_run(store, run_id)
    provider = _scripted(_DiscardBoomStub())
    reviewer_id = provider.start_reviewer_session({"loop_id": "review-whole-plan-01"})
    _save_reviewer_loop(store, run_id, loop_id="review-whole-plan-01", session_id=reviewer_id)
    provider.protected_ids.add(reviewer_id)
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id=reviewer_id,
        target_revision=0,
        scope={"kind": "whole_plan"},
        revise_at="blocker",
    )
    with patch(
        "top_down_planning.orchestrator.session_recovery.validate_provider_session_binding",
        side_effect=ProviderSessionError("bad reviewer bind", session_id="x"),
    ):
        with pytest.raises(SessionRecoveryPaused) as caught:
            replace_reviewer_session(
                store,
                run_id,
                provider,
                loop=loop,
                phase="whole_plan_review",
                old_provider_session_id=reviewer_id,
                phase_action_id="action-replace-r08",
                append_event=lambda *_a, **_k: None,
                model="test-model",
                manifest={"loop_id": "review-whole-plan-01"},
            )
    _assert_cleanup_note(caught.value)
    run = store.load_run(run_id)
    assert run["status"] == "paused"
    assert run["stop"]["code"] == "provider_unavailable"


def test_primary_assert_after_generation_write_uses_new_identity(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T030501-030501"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    from top_down_planning.orchestrator.session_context import ensure_primary_session

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
    old_generation = get_primary_binding(store.load_run(run_id), "planner").generation
    with patch(
        "top_down_planning.orchestrator.session_recovery.assert_expected_run_revision",
        side_effect=PersistenceError("load after generation write"),
    ):
        with pytest.raises(PersistenceError, match="load after generation write"):
            replace_primary_session(
                store,
                run_id,
                provider,
                role="planner",
                phase="planning",
                old_provider_session_id=old_id,
                phase_action_id="action-replace-09",
                append_event=lambda *_a, **_k: None,
                model="test-model",
                manifest={"goal": "x"},
            )
    started = _lineage(store, run_id, SESSION_REPLACEMENT_STARTED)
    failed = _lineage(store, run_id, SESSION_REPLACEMENT_FAILED)
    assert started and failed
    assert started[-1]["generation"] == failed[-1]["generation"]
    assert failed[-1]["generation"] != old_generation
    assert failed[-1]["reason"] == "persistence_failure"


def test_primary_replacement_rejects_canonicalizing_to_old_id(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T030601-030601"
    _create_run(store, run_id)
    provider = _scripted(_PendingSameIdStub())
    from top_down_planning.orchestrator.session_context import ensure_primary_session

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
    pending = replace_primary_session(
        store,
        run_id,
        provider,
        role="planner",
        phase="planning",
        old_provider_session_id=old_id,
        phase_action_id="action-replace-10",
        append_event=lambda *_a, **_k: None,
        model="test-model",
        manifest={"goal": "x"},
    )
    assert pending == "cursor-pending-2"
    provider.aliases[pending] = old_id
    with pytest.raises(ProviderSessionError, match="canonicalizes to replaced id"):
        sync_persisted_session_id(provider, store, run_id, pending, role="planner")
    replaced = _lineage(store, run_id, SESSION_REPLACED)
    assert all(event.get("new_provider_session_id") != old_id for event in replaced)
    binding = get_primary_binding(store.load_run(run_id), "planner")
    assert binding is not None
    assert binding.provider_session_id != old_id


def test_reviewer_replacement_rejects_canonicalizing_to_old_id(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T030602-030602"
    _create_run(store, run_id)
    provider = _scripted(_PendingSameIdStub())
    old_id = provider.start_reviewer_session({"loop_id": "review-whole-plan-01"})
    _save_reviewer_loop(store, run_id, loop_id="review-whole-plan-01", session_id=old_id)
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id=old_id,
        target_revision=0,
        scope={"kind": "whole_plan"},
        revise_at="blocker",
    )
    pending = replace_reviewer_session(
        store,
        run_id,
        provider,
        loop=loop,
        phase="whole_plan_review",
        old_provider_session_id=old_id,
        phase_action_id="action-replace-r10",
        append_event=lambda *_a, **_k: None,
        model="test-model",
        manifest={"loop_id": "review-whole-plan-01"},
    )
    assert pending == "cursor-pending-2"
    provider.aliases[pending] = old_id
    with pytest.raises(ProviderSessionError, match="canonicalizes to replaced id"):
        sync_reviewer_loop_session_id(
            provider, store, run_id, "review-whole-plan-01", pending
        )
    replaced = _lineage(store, run_id, SESSION_REPLACED)
    assert all(event.get("new_provider_session_id") != old_id for event in replaced)
