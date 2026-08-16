"""Slice 5 rereview 366c299: killable worker spawn, durable unreaped owner, queued-turn abort."""

from __future__ import annotations

import multiprocessing
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.cursor import CursorProvider
from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.orchestrator.provider_turns import (
    LiteralBoundarySignal,
    _drain_provider_turn,
    _invoke_boundary_bounded,
    unreaped_boundary_workers,
)


def _boundary_start_threads() -> list[threading.Thread]:
    return [
        thread
        for thread in threading.enumerate()
        if thread.name == "tdp-boundary-start" and thread.is_alive()
    ]


def test_never_returning_process_start_is_not_used() -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    entered = threading.Event()
    release = threading.Event()

    def never_popen(*args, **kwargs):
        del args, kwargs
        entered.set()
        release.wait(timeout=5.0)
        raise OSError("cancelled")

    worker = BoundaryWorker()
    try:
        with patch.object(BoundaryWorker, "_popen", staticmethod(never_popen)):
            with pytest.raises(ProviderRunError, match="exceeded timeout"):
                worker.start(deadline=time.monotonic() + 0.05)
        assert entered.wait(timeout=1.0)
        assert _boundary_start_threads() == []
        assert [
            proc
            for proc in multiprocessing.active_children()
            if "tdp-boundary" in (proc.name or "")
        ] == []
    finally:
        release.set()
        if worker._boot_thread is not None:
            worker._boot_thread.join(timeout=1.0)
        worker.close(cleanup_timeout=0.2)
        from top_down_planning.orchestrator.provider_turns import (
            reap_unreaped_boundary_workers,
        )

        try:
            reap_unreaped_boundary_workers(timeout=0.5)
        except ProviderRunError:
            pass


def test_oneshot_close_failure_keeps_reachable_owner() -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    def fail_close(self, **kwargs) -> None:
        del kwargs
        raise ProviderRunError("boundary worker failed to stop")

    with patch.object(BoundaryWorker, "close", fail_close):
        with pytest.raises(ProviderRunError, match="failed to stop"):
            _invoke_boundary_bounded(
                LiteralBoundarySignal(),
                threading.Event(),
                timeout=1.0,
            )
    owners = unreaped_boundary_workers()
    assert owners
    try:
        for worker in owners:
            BoundaryWorker.close(worker)
    finally:
        for worker in unreaped_boundary_workers():
            BoundaryWorker.close(worker)


def _cursor_provider(tmp_path: Path) -> CursorProvider:
    agent = tmp_path / "agent"
    agent.write_text("", encoding="utf-8")
    return CursorProvider(
        {"limits": {"provider": {"turn_idle_timeout_seconds": 2.0, "max_retries_per_call": 0}}},
        workspace=tmp_path,
        runner=lambda argv, cwd: iter(()),
        binary=str(agent),
        skip_probe=True,
    )


def _assert_queued_turn_cleared(provider: CursorProvider, session_id: str) -> None:
    session = provider._sessions[session_id]
    assert session.pending_argv is None
    assert session.turn_queued is False


def test_drain_startup_failure_clears_queued_cursor_turn(tmp_path: Path) -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    provider = _cursor_provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    session = provider._sessions[session_id]
    assert session.turn_queued is True
    assert session.pending_argv is not None

    def boom(self, *, deadline=None) -> None:
        del self, deadline
        raise ProviderRunError("boundary probe exceeded timeout")

    with patch.object(BoundaryWorker, "start", boom):
        with pytest.raises(ProviderRunError, match="exceeded timeout"):
            _drain_provider_turn(
                provider,
                session_id,
                allowed_signals=frozenset(),
                on_boundary=LiteralBoundarySignal(),
            )
    _assert_queued_turn_cleared(provider, session_id)


def test_drain_startup_failure_clears_resumed_primary_turn(tmp_path: Path) -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    provider = _cursor_provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    provider.abort_turn(session_id)
    provider.resume_primary_session(session_id, {"goal": "again"}, role="planner")
    session = provider._sessions[session_id]
    assert session.turn_queued is True

    def boom(self, *, deadline=None) -> None:
        del self, deadline
        raise ProviderRunError("boundary probe exceeded timeout")

    with patch.object(BoundaryWorker, "start", boom):
        with pytest.raises(ProviderRunError, match="exceeded timeout"):
            _drain_provider_turn(
                provider,
                session_id,
                allowed_signals=frozenset(),
                on_boundary=LiteralBoundarySignal(),
            )
    _assert_queued_turn_cleared(provider, session_id)


def test_drain_startup_failure_clears_reviewer_turn(tmp_path: Path) -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    provider = _cursor_provider(tmp_path)
    session_id = provider.start_reviewer_session({"loop_id": "review-01"})
    session = provider._sessions[session_id]
    assert session.turn_queued is True

    def boom(self, *, deadline=None) -> None:
        del self, deadline
        raise ProviderRunError("boundary probe exceeded timeout")

    with patch.object(BoundaryWorker, "start", boom):
        with pytest.raises(ProviderRunError, match="exceeded timeout"):
            _drain_provider_turn(
                provider,
                session_id,
                allowed_signals=frozenset(),
                on_boundary=LiteralBoundarySignal(),
            )
    _assert_queued_turn_cleared(provider, session_id)


def test_drain_close_failure_keeps_reachable_owner(tmp_path: Path) -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    provider = _cursor_provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})

    def fail_close(self, **kwargs) -> None:
        del kwargs
        raise ProviderRunError("boundary worker failed to stop")

    try:
        with patch.object(BoundaryWorker, "close", fail_close):
            with pytest.raises(BaseException) as caught:
                _drain_provider_turn(
                    provider,
                    session_id,
                    allowed_signals=frozenset(),
                    on_boundary=LiteralBoundarySignal(),
                )
        assert "failed to stop" in str(caught.value) or "failed to stop" in repr(
            getattr(caught.value, "__notes__", [])
        )
        owners = unreaped_boundary_workers()
        assert owners
    finally:
        for worker in unreaped_boundary_workers():
            BoundaryWorker.close(worker)
