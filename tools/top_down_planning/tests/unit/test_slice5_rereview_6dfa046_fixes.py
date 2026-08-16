"""Slice 5 rereview 6dfa046: bounded start, fair sweep, teardown independence."""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

import pytest

from core_tools.provider import StubProvider
from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.orchestrator.provider_teardown import teardown_provider_sessions
from top_down_planning.orchestrator.provider_turns import (
    BOUNDARY_WORKER_CLEANUP_SECONDS,
    _finalize_boundary_poll,
    reap_unreaped_boundary_workers,
    unreaped_boundary_workers,
)


def test_never_returning_popen_does_not_block_start_deadline() -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker
    import subprocess
    import sys

    def hang_ready(*args, **kwargs):
        del args
        return subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            pass_fds=kwargs.get("pass_fds", ()),
            close_fds=kwargs.get("close_fds", True),
            start_new_session=True,
        )

    worker = BoundaryWorker()
    started = time.monotonic()
    try:
        with patch.object(BoundaryWorker, "_popen", staticmethod(hang_ready)):
            with pytest.raises(ProviderRunError, match="exceeded timeout"):
                worker.start(deadline=time.monotonic() + 0.05)
        assert time.monotonic() - started < 0.25
        assert [
            item.name
            for item in threading.enumerate()
            if item.name == "tdp-boundary-popen"
        ] == []
    finally:
        worker.close(cleanup_timeout=0.2)
        try:
            reap_unreaped_boundary_workers(timeout=0.5)
        except ProviderRunError:
            pass


def test_late_popen_after_deadline_is_killed() -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker
    import subprocess
    import sys

    def hang_ready(*args, **kwargs):
        del args
        return subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            pass_fds=kwargs.get("pass_fds", ()),
            close_fds=kwargs.get("close_fds", True),
            start_new_session=True,
        )

    worker = BoundaryWorker()
    try:
        with patch.object(BoundaryWorker, "_popen", staticmethod(hang_ready)):
            with pytest.raises(ProviderRunError, match="exceeded timeout"):
                worker.start(deadline=time.monotonic() + 0.05)
        worker.close(cleanup_timeout=1.0)
        assert worker.proc is None or not BoundaryWorker._proc_alive(worker.proc)
        assert [
            item.name
            for item in threading.enumerate()
            if item.name == "tdp-boundary-popen"
        ] == []
    finally:
        worker.close(cleanup_timeout=1.0)
        try:
            reap_unreaped_boundary_workers(timeout=0.5)
        except ProviderRunError:
            pass


def test_sweep_failure_still_terminates_provider_sessions() -> None:
    terminated = {"n": 0}

    class Spy(StubProvider):
        def terminate_all_sessions(self):
            terminated["n"] += 1
            return super().terminate_all_sessions()

    provider = Spy()
    provider.script_turn([{"type": "done", "subtype": "success", "text": "ok"}])
    provider.start_primary_session("planner", {"goal": "x"})
    with patch(
        "top_down_planning.orchestrator.provider_turns.reap_unreaped_boundary_workers",
        side_effect=ProviderRunError("boundary worker failed to stop"),
    ):
        with pytest.raises(Exception):
            teardown_provider_sessions(
                provider,
                run_id="run-sweep-fail",
                phase=PLANNING,
                append_event=lambda *_a, **_k: None,
                emit_console=lambda _e: None,
            )
    assert terminated["n"] == 1
    assert provider.list_active_sessions() == []


def test_finalize_sweep_uses_remaining_cleanup_budget() -> None:
    from top_down_planning.orchestrator.provider_turns import (
        BoundaryWorker,
        LiteralBoundarySignal,
        _BoundaryPollState,
    )

    seen: list[float] = []
    clock = {"t": 10.0}

    def fake_monotonic() -> float:
        return clock["t"]

    worker = BoundaryWorker()
    worker.start()
    state = _BoundaryPollState(
        stop=threading.Event(),
        done=threading.Event(),
        worker=worker,
        on_boundary=LiteralBoundarySignal(),
    )

    def fail_close(self, **kwargs):
        seen.append(kwargs.get("cleanup_timeout", BOUNDARY_WORKER_CLEANUP_SECONDS))
        clock["t"] += 0.15
        raise ProviderRunError("boundary worker failed to stop")

    class _Provider:
        def abort_turn(self, session_id, *, timeout=2.0):
            del session_id, timeout

        def wait_turn_settled(self, session_id, *, timeout=30.0):
            del session_id, timeout

        def terminate_session(self, session_id, *, timeout=2.0):
            del session_id, timeout

        def canonical_session_id(self, session_id):
            return session_id

    try:
        with patch(
            "top_down_planning.orchestrator.provider_turns.time.monotonic",
            fake_monotonic,
        ), patch.object(BoundaryWorker, "close", fail_close), patch(
            "top_down_planning.orchestrator.provider_turns.reap_unreaped_boundary_workers",
            side_effect=lambda timeout=None: seen.append(timeout),
        ):
            with pytest.raises(ProviderRunError):
                _finalize_boundary_poll(state, _Provider(), "sess-1")
        assert seen
        assert seen[0] == pytest.approx(BOUNDARY_WORKER_CLEANUP_SECONDS, abs=0.05)
        if len(seen) > 1:
            assert seen[1] == pytest.approx(0.05, abs=0.05)
    finally:
        BoundaryWorker.close(worker)


def test_unreaped_sweep_does_not_starve_later_workers() -> None:
    from top_down_planning.orchestrator.provider_turns import (
        BoundaryWorker,
        _UNREAPED_BOUNDARY_WORKERS,
        _BOUNDARY_WORKER_LOCK,
    )

    reaped: list[str] = []

    class StubWorker:
        def __init__(self, name: str, stubborn: bool) -> None:
            self.name = name
            self.stubborn = stubborn
            self.proc = None

        def close(self, *, cleanup_timeout=None, **kwargs):
            del kwargs
            if self.stubborn:
                time.sleep(min(0.12, cleanup_timeout or 0.0))
                raise ProviderRunError("boundary worker failed to stop")
            reaped.append(self.name)
            with _BOUNDARY_WORKER_LOCK:
                _UNREAPED_BOUNDARY_WORKERS.pop(id(self), None)

    workers = [StubWorker("A", True), StubWorker("B", False), StubWorker("C", False)]
    with _BOUNDARY_WORKER_LOCK:
        for worker in workers:
            _UNREAPED_BOUNDARY_WORKERS[id(worker)] = worker  # type: ignore[assignment]
    try:
        with pytest.raises(ProviderRunError):
            reap_unreaped_boundary_workers(timeout=0.2)
        assert "B" in reaped
        assert "C" in reaped
    finally:
        with _BOUNDARY_WORKER_LOCK:
            for worker in workers:
                _UNREAPED_BOUNDARY_WORKERS.pop(id(worker), None)
