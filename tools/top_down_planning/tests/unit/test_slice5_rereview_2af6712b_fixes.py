"""Slice 5 rereview 2af6712b: turn terminal state, replacement lineage, bind atomicity."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.persistence import PersistenceError
from core_tools.provider.cursor import CursorProvider
from core_tools.provider.errors import ProviderSessionError, ProviderTurnError
from top_down_planning.domain.session_lineage import (
    SESSION_REPLACEMENT_FAILED,
    SESSION_REPLACEMENT_STARTED,
)
from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.orchestrator.provider_turns import (
    BOUNDARY_POLL_THREAD_NAME,
    PROVIDER_ABORT_THREAD_NAME,
    PROVIDER_EVENT_PUMP_NAME,
    PROVIDER_TERMINATE_THREAD_NAME,
    _drain_provider_turn,
    boundary_cancel_event,
)
from top_down_planning.orchestrator.reviewer_session import begin_reviewer_review
from top_down_planning.orchestrator.session_context import (
    ensure_primary_session,
    rotate_primary_session,
)
from top_down_planning.orchestrator.session_events import discard_unbound_provider_session
from top_down_planning.orchestrator.session_recovery import (
    replace_primary_session,
    replace_reviewer_session,
)
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.commit import CommitSpec
from top_down_planning.persistence.session_bindings import get_primary_binding
from tests.helpers import make_review_loop
from tests.unit.test_slice5_rereview_ee5de8e_fixes import (
    _ForcedIdStub,
    _RecordingDrainProvider,
    _active_ids,
    _create_run,
    _live_named,
    _requested,
    _save_reviewer_loop,
    _scripted,
)


def _helper_threads() -> list[threading.Thread]:
    names = {
        PROVIDER_ABORT_THREAD_NAME,
        PROVIDER_TERMINATE_THREAD_NAME,
        PROVIDER_EVENT_PUMP_NAME,
        BOUNDARY_POLL_THREAD_NAME,
        "cursor-idle-stream",
    }
    return [
        thread
        for thread in threading.enumerate()
        if thread.name in names and thread.is_alive()
    ]


def _lineage(store: FileRunStore, run_id: str, event_type: str) -> list[dict]:
    return [
        event
        for event in store.load_events(run_id)
        if event.get("type") == event_type
    ]


class _LateErrorProvider:
    def stream_events(self, session_id: str):
        yield {"type": "done", "text": "ok"}
        raise ProviderTurnError("late provider failure", session_id=session_id)

    def abort_turn(self, session_id: str, timeout: float | None = None) -> None:
        return

    def wait_turn_settled(self, session_id: str, *, timeout: float = 30.0) -> None:
        return

    def terminate_session(self, session_id: str, timeout: float | None = None) -> None:
        return

    def canonical_session_id(self, session_id: str) -> str:
        return session_id


class _DoneErrorThenEndProvider:
    def stream_events(self, session_id: str):
        yield {"type": "done", "text": "provider boom", "is_error": True}

    def abort_turn(self, session_id: str, timeout: float | None = None) -> None:
        return

    def wait_turn_settled(self, session_id: str, *, timeout: float = 30.0) -> None:
        return

    def terminate_session(self, session_id: str, timeout: float | None = None) -> None:
        return

    def canonical_session_id(self, session_id: str) -> str:
        return session_id


class _HangDiscardStub(_ForcedIdStub):
    def terminate_session(self, session_id: str, timeout: float | None = None) -> None:
        threading.Event().wait(timeout=timeout or 30)


def test_abort_and_terminate_both_blocked_are_bounded() -> None:
    for _ in range(6):
        provider = _RecordingDrainProvider(
            hang_abort=True,
            hang_terminate=True,
            unblock_on_abort=False,
            unblock_on_terminate=False,
        )
        with patch(
            "top_down_planning.orchestrator.provider_turns.ABORT_TURN_SECONDS",
            0.1,
        ), patch(
            "top_down_planning.orchestrator.provider_turns.BOUNDARY_POLL_JOIN_SECONDS",
            0.1,
        ):
            started = time.monotonic()
            try:
                _drain_provider_turn(
                    provider,
                    "sess-1",
                    allowed_signals=frozenset(),
                    on_boundary=lambda: "paused",
                )
            except Exception:
                pass
            assert time.monotonic() - started < 2.0
        assert _helper_threads() == []


def test_terminate_return_does_not_require_abort_to_unblock() -> None:
    provider = _RecordingDrainProvider(
        hang_abort=True,
        hang_terminate=False,
        unblock_on_abort=False,
        unblock_on_terminate=True,
    )
    with patch(
        "top_down_planning.orchestrator.provider_turns.ABORT_TURN_SECONDS",
        0.1,
    ), patch(
        "top_down_planning.orchestrator.provider_turns.BOUNDARY_POLL_JOIN_SECONDS",
        0.1,
    ):
        started = time.monotonic()
        try:
            _drain_provider_turn(
                provider,
                "sess-1",
                allowed_signals=frozenset(),
                on_boundary=lambda: "paused",
            )
        except Exception:
            pass
        assert time.monotonic() - started < 2.0
    assert _helper_threads() == []


def test_never_returning_boundary_callback_is_bounded() -> None:
    def on_boundary() -> str | None:
        cancel = boundary_cancel_event()
        if cancel is not None:
            cancel.wait()
        else:
            threading.Event().wait()
        return None

    provider = _RecordingDrainProvider()
    with patch(
        "top_down_planning.orchestrator.provider_turns.ABORT_TURN_SECONDS",
        0.1,
    ), patch(
        "top_down_planning.orchestrator.provider_turns.BOUNDARY_POLL_JOIN_SECONDS",
        0.1,
    ):
        started = time.monotonic()
        with pytest.raises(ProviderRunError, match="boundary probe"):
            _drain_provider_turn(
                provider,
                "sess-1",
                allowed_signals=frozenset(),
                on_boundary=on_boundary,
            )
        assert time.monotonic() - started < 2.0
    assert _helper_threads() == []


def test_done_then_late_provider_error_is_not_success() -> None:
    with pytest.raises(ProviderTurnError, match="late provider failure"):
        _drain_provider_turn(
            _LateErrorProvider(),
            "sess-1",
            allowed_signals=frozenset({"candidate_plan_ready"}),
        )


def test_done_error_is_not_hidden_by_store_boundary() -> None:
    with pytest.raises(ProviderRunError, match="provider boom"):
        _drain_provider_turn(
            _DoneErrorThenEndProvider(),
            "sess-1",
            allowed_signals=frozenset({"candidate_plan_ready"}),
            on_boundary=lambda: "candidate_plan_ready",
        )


def test_done_error_without_boundary_polling_still_fails() -> None:
    with pytest.raises(ProviderRunError, match="provider boom"):
        _drain_provider_turn(
            _DoneErrorThenEndProvider(),
            "sess-1",
            allowed_signals=frozenset({"candidate_plan_ready"}),
        )


def test_cursor_done_without_durable_id_is_not_success(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    lines = [
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "ok"}]},
            }
        ),
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": "ok",
            }
        ),
    ]

    def fake_runner(argv: list[str], cwd: Path):
        yield from lines

    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=fake_runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    with pytest.raises(ProviderTurnError, match="durable provider session id"):
        _drain_provider_turn(
            provider,
            session_id,
            allowed_signals=frozenset({"candidate_plan_ready"}),
        )


def test_cursor_done_then_cleanup_failure_is_not_success(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    lines = [
        json.dumps({"type": "system", "subtype": "init", "session_id": "cursor-d1"}),
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "session_id": "cursor-d1",
                "is_error": False,
                "result": "ok",
            }
        ),
    ]

    def fake_runner(argv: list[str], cwd: Path):
        yield from lines
        raise ProviderTurnError("Cursor CLI cleanup failed: survivors")

    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=fake_runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    with pytest.raises(ProviderTurnError, match="cleanup failed"):
        _drain_provider_turn(
            provider,
            session_id,
            allowed_signals=frozenset({"candidate_plan_ready"}),
        )


def test_primary_replacement_failure_after_started_keeps_new_generation(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T020401-020401"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    planner_id = ensure_primary_session(
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
    from top_down_planning.orchestrator import session_recovery

    real_started = session_recovery.emit_session_replacement_started

    def started_then_fail(*args, **kwargs):
        real_started(*args, **kwargs)
        raise PersistenceError("audit after replacement_started")

    with patch.object(
        session_recovery, "emit_session_replacement_started", started_then_fail
    ):
        with pytest.raises(PersistenceError, match="audit after replacement_started"):
            replace_primary_session(
                store,
                run_id,
                provider,
                role="planner",
                phase="planning",
                old_provider_session_id=planner_id,
                phase_action_id="action-replace-01",
                append_event=lambda *_a, **_k: None,
                model=None,
                manifest={"goal": "x"},
            )
    started = _lineage(store, run_id, SESSION_REPLACEMENT_STARTED)
    failed = _lineage(store, run_id, SESSION_REPLACEMENT_FAILED)
    assert len(started) == 1
    assert len(failed) == 1
    assert started[0]["session_instance_id"] == failed[0]["session_instance_id"]
    assert started[0]["generation"] == failed[0]["generation"]
    assert failed[0]["reason"] == "persistence_failure"
    run = store.load_run(run_id)
    assert run["status"] == "failed"
    assert run["stop"]["code"] == "state_integrity_failure"


def test_primary_replacement_does_not_map_cas_conflict_to_provider_unavailable(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T020402-020402"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    planner_id = ensure_primary_session(
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
    real_save = store.save_run

    def conflict(run_id: str, run: dict, expected_revision: int) -> None:
        raise PersistenceError("cas conflict")

    store.save_run = conflict  # type: ignore[method-assign]
    with pytest.raises(PersistenceError, match="cas conflict"):
        replace_primary_session(
            store,
            run_id,
            provider,
            role="planner",
            phase="planning",
            old_provider_session_id=planner_id,
            phase_action_id="action-replace-02",
            append_event=lambda *_a, **_k: None,
            model=None,
            manifest={"goal": "x"},
        )
    store.save_run = real_save  # type: ignore[method-assign]
    run = store.load_run(run_id)
    assert run["status"] == "failed"
    assert run["stop"]["code"] == "state_integrity_failure"
    failed = _lineage(store, run_id, SESSION_REPLACEMENT_FAILED)
    assert failed and failed[-1]["reason"] == "persistence_failure"


def test_binding_lineage_failure_does_not_discard_published_session(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T020403-020403"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    real_commit = store.commit

    def split_commit(run_id: str, spec: CommitSpec):
        if spec.run is not None and spec.events:
            store.save_run(run_id, spec.run, spec.run_expected_revision)
            raise PersistenceError("lineage write failed")
        return real_commit(run_id, spec)

    store.commit = split_commit  # type: ignore[method-assign]
    with pytest.raises(PersistenceError, match="lineage write failed"):
        ensure_primary_session(
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
    store.commit = real_commit  # type: ignore[method-assign]
    binding = get_primary_binding(store.load_run(run_id), "planner")
    assert binding is not None
    assert binding.provider_session_id in _active_ids(provider)


def test_reviewer_binding_lineage_failure_does_not_discard_published_session(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T020404-020404"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    _save_reviewer_loop(store, run_id, loop_id="review-whole-plan-01", session_id=None)
    real_commit = store.commit

    def split_commit(run_id: str, spec: CommitSpec):
        if spec.reviews and spec.events:
            from top_down_planning.persistence.review_commit import (
                save_review_with_expected_revision,
            )
            from top_down_planning.domain.reviews import ReviewLoop

            payload = spec.reviews[0]
            loop = ReviewLoop.from_dict(payload)
            expected = spec.review_expected_revisions[loop.id]
            save_review_with_expected_revision(
                store, run_id, loop, expected_revision=expected
            )
            raise PersistenceError("reviewer lineage write failed")
        return real_commit(run_id, spec)

    store.commit = split_commit  # type: ignore[method-assign]
    with pytest.raises(PersistenceError, match="reviewer lineage write failed"):
        begin_reviewer_review(
            provider,
            store,
            run_id,
            loop_id="review-whole-plan-01",
            review_package={"loop_id": "review-whole-plan-01"},
            phase="whole_plan_review",
        )
    store.commit = real_commit  # type: ignore[method-assign]
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id=None,
        target_revision=0,
        scope={"kind": "whole_plan"},
        revise_at="blocker",
    )
    stored = store.load_review(run_id, "review-whole-plan-01")
    bound = stored.get("reviewer_binding") or {}
    session_id = bound.get("provider_session_id")
    assert session_id
    assert session_id in _active_ids(provider)


def test_rotation_save_failure_discards_unpublished_replacement(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T020405-020405"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub(), n=16)
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
    real_save = store.save_run

    def boom(run_id: str, run: dict, expected_revision: int) -> None:
        raise PersistenceError("rotation save failed")

    store.save_run = boom  # type: ignore[method-assign]
    before_active = _active_ids(provider)
    with pytest.raises(PersistenceError, match="rotation save failed"):
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
    store.save_run = real_save  # type: ignore[method-assign]
    binding = get_primary_binding(store.load_run(run_id), "planner")
    assert binding is not None
    assert binding.provider_session_id == old_id
    leftover = _active_ids(provider) - before_active
    assert leftover == set()
    assert old_id not in _active_ids(provider)


def test_discard_unbound_surfaces_hanging_terminate() -> None:
    provider = _scripted(_HangDiscardStub())
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
    assert session_id in _active_ids(provider)


def test_reviewer_replacement_failure_after_started_keeps_new_generation(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T020406-020406"
    _create_run(store, run_id)
    provider = _scripted(_ForcedIdStub())
    reviewer_id = provider.start_reviewer_session({"loop_id": "review-whole-plan-01"})
    _save_reviewer_loop(
        store, run_id, loop_id="review-whole-plan-01", session_id=reviewer_id
    )
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id=reviewer_id,
        target_revision=0,
        scope={"kind": "whole_plan"},
        revise_at="blocker",
    )
    from top_down_planning.orchestrator import session_recovery

    real_started = session_recovery.emit_session_replacement_started

    def started_then_fail(*args, **kwargs):
        real_started(*args, **kwargs)
        raise PersistenceError("reviewer audit after started")

    with patch.object(
        session_recovery, "emit_session_replacement_started", started_then_fail
    ):
        with pytest.raises(PersistenceError, match="reviewer audit after started"):
            replace_reviewer_session(
                store,
                run_id,
                provider,
                loop=loop,
                phase="whole_plan_review",
                old_provider_session_id=reviewer_id,
                phase_action_id="action-replace-r1",
                append_event=lambda *_a, **_k: None,
                model=None,
                manifest={"loop_id": "review-whole-plan-01"},
            )
    started = _lineage(store, run_id, SESSION_REPLACEMENT_STARTED)
    failed = _lineage(store, run_id, SESSION_REPLACEMENT_FAILED)
    assert len(started) == 1
    assert len(failed) == 1
    assert started[0]["session_instance_id"] == failed[0]["session_instance_id"]
    assert started[0]["generation"] == failed[0]["generation"]
    assert failed[0]["reason"] == "persistence_failure"
