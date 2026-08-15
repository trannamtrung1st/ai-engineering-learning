"""Slice 5 rereview d30fdaa: startup ownership, poll finalizer, pickle-before-start."""

from __future__ import annotations

import multiprocessing
import threading
import time
from unittest.mock import patch

import pytest

from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.orchestrator.provider_turns import (
    BOUNDARY_WORKER_CLEANUP_SECONDS,
    LiteralBoundarySignal,
    _BoundaryPollState,
    _finalize_boundary_poll,
    _invoke_boundary_bounded,
)


def _boundary_start_threads() -> list[threading.Thread]:
    return [
        thread
        for thread in threading.enumerate()
        if thread.name == "tdp-boundary-start" and thread.is_alive()
    ]


def _boundary_children() -> list[multiprocessing.Process]:
    return [
        proc
        for proc in multiprocessing.active_children()
        if "tdp-boundary" in (proc.name or "")
    ]


def _wait_boundary_gone(*, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _boundary_start_threads() and not _boundary_children():
            return
        time.sleep(0.02)
    pytest.fail(
        f"leftover start threads={_boundary_start_threads()!r} "
        f"children={_boundary_children()!r}"
    )


class _HangStartProvider:
    def abort_turn(self, session_id: str, *, timeout: float = 2.0) -> None:
        del session_id, timeout

    def wait_turn_settled(self, session_id: str, *, timeout: float = 30.0) -> None:
        del session_id, timeout

    def terminate_session(self, session_id: str, *, timeout: float = 2.0) -> None:
        del session_id, timeout

    def canonical_session_id(self, session_id: str) -> str:
        return session_id


def test_late_process_start_after_timeout_is_killed_and_joined() -> None:
    release = threading.Event()
    real_start = multiprocessing.process.BaseProcess.start

    def delayed_start(self) -> None:
        release.wait(timeout=2.0)
        real_start(self)

    with patch("multiprocessing.process.BaseProcess.start", delayed_start):
        with pytest.raises(ProviderRunError, match="exceeded timeout|failed to stop"):
            _invoke_boundary_bounded(
                LiteralBoundarySignal(),
                threading.Event(),
                timeout=0.15,
            )
        release.set()
        _wait_boundary_gone()


def test_blocked_startup_retains_process_owner() -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    release = threading.Event()

    def blocked_start(self) -> None:
        del self
        release.wait(timeout=5.0)

    worker = BoundaryWorker()
    try:
        with patch("multiprocessing.process.BaseProcess.start", blocked_start):
            with pytest.raises(ProviderRunError):
                worker.start(deadline=time.monotonic() + 0.1)
            assert worker.proc is not None
            assert _boundary_start_threads()
    finally:
        release.set()
        worker.close(cleanup_timeout=1.0)
        _wait_boundary_gone()


def test_finalize_retains_worker_when_close_cannot_reap() -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    worker = BoundaryWorker()
    worker.start()
    state = _BoundaryPollState(
        stop=threading.Event(),
        done=threading.Event(),
        worker=worker,
        on_boundary=LiteralBoundarySignal(),
    )
    try:
        with patch.object(
            BoundaryWorker,
            "close",
            side_effect=ProviderRunError("boundary worker failed to stop"),
        ):
            with pytest.raises(ProviderRunError, match="failed to stop"):
                _finalize_boundary_poll(state, _HangStartProvider(), "sess-1")
        assert state.worker is worker
        assert worker.proc is not None
    finally:
        BoundaryWorker.close(worker)


def test_close_cleanup_timeout_is_one_absolute_deadline() -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    worker = BoundaryWorker()
    worker.start()
    proc = worker.proc
    assert proc is not None
    seen: list[float] = []
    clock = {"t": 100.0}

    def fake_monotonic() -> float:
        return clock["t"]

    def recording_join(timeout: float | None = None) -> None:
        if timeout is not None:
            seen.append(float(timeout))
            clock["t"] += max(0.0, float(timeout))

    with patch(
        "top_down_planning.orchestrator.provider_turns.time.monotonic",
        fake_monotonic,
    ), patch.object(type(proc), "is_alive", return_value=True), patch.object(
        type(proc), "join", side_effect=recording_join
    ), patch.object(type(proc), "kill", return_value=None):
        with pytest.raises(ProviderRunError, match="failed to stop"):
            worker.close(cleanup_timeout=0.2)
        assert worker.proc is proc
    assert seen
    assert sum(seen) <= 0.21
    worker.close()


def test_unserializable_callback_creates_no_worker() -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    _wait_boundary_gone(timeout=0.5)

    starts = {"n": 0}
    real_start = BoundaryWorker.start

    def counting_start(self, *, deadline: float | None = None) -> None:
        starts["n"] += 1
        return real_start(self, deadline=deadline)

    def nested() -> str | None:
        threading.Event().wait()
        return "paused"

    with patch.object(BoundaryWorker, "start", counting_start):
        with pytest.raises(ProviderRunError, match="serializable"):
            _invoke_boundary_bounded(nested, threading.Event(), timeout=0.4)
    assert starts["n"] == 0
    assert _boundary_children() == []


def test_invoke_docstring_separates_response_and_cleanup_budgets() -> None:
    doc = _invoke_boundary_bounded.__doc__ or ""
    assert "BOUNDARY_WORKER_CLEANUP_SECONDS" in doc
    assert "hard wall-clock" not in doc
    assert BOUNDARY_WORKER_CLEANUP_SECONDS == 0.2
