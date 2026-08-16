"""Slice 5 rereview c67af97: killable boundary spawn, sweep, teardown control."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.orchestrator.provider_teardown import teardown_provider_sessions
from top_down_planning.orchestrator.provider_turns import (
    LiteralBoundarySignal,
    _drain_provider_turn,
    owned_boundary_workers,
    reap_unreaped_boundary_workers,
    unreaped_boundary_workers,
)
from tests.unit.test_slice5_rereview_ee5de8e_fixes import _RecordingDrainProvider


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX boundary worker")
def test_wait_ready_true_and_false_share_daemon_popen_owner() -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    worker = BoundaryWorker()
    try:
        worker.start(deadline=time.monotonic() + 2.0, wait_ready=True)
        assert worker._boot_thread is not None
        assert worker._boot_thread.daemon is True
        worker.close(cleanup_timeout=1.0)
        worker = BoundaryWorker()
        worker.start(deadline=time.monotonic() + 2.0, wait_ready=False)
        boot = worker._boot_thread
        assert boot is not None
        assert boot.daemon is True
        boot.join(timeout=2.0)
    finally:
        worker.close(cleanup_timeout=1.0)
        try:
            reap_unreaped_boundary_workers(timeout=0.5)
        except ProviderRunError:
            pass
    assert owned_boundary_workers() == ()
    assert unreaped_boundary_workers() == ()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX boundary worker")
def test_never_returning_popen_host_exits_without_test_side_unblock() -> None:
    src = Path(__file__).resolve().parents[2] / "src"
    core_src = Path(__file__).resolve().parents[3] / "core_tools" / "src"
    script = r"""
import sys
import threading
import time
from unittest.mock import patch

from top_down_planning.orchestrator.provider_turns import BoundaryWorker

def hang(*args, **kwargs):
    del args, kwargs
    threading.Event().wait()
    raise AssertionError("Popen returned")

worker = BoundaryWorker()
with patch.object(BoundaryWorker, "_popen", staticmethod(hang)):
    worker.start(deadline=time.monotonic() + 0.15, wait_ready=False)
    try:
        worker.close(cleanup_timeout=0.2)
    except Exception:
        pass
sys.exit(0)
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(src), str(core_src), env.get("PYTHONPATH", "")]
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=2.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2.0)
        pytest.fail("sacrificial host did not exit while Popen stayed blocked")
    assert proc.returncode == 0, stderr or stdout


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX boundary worker")
def test_finite_late_popen_does_not_fail_completed_turn_cleanup() -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    real_popen = BoundaryWorker._popen

    def slow_popen(*args, **kwargs):
        time.sleep(0.35)
        return real_popen(*args, **kwargs)

    provider = _RecordingDrainProvider(yield_event={"type": "assistant", "text": "x"})
    with patch.object(BoundaryWorker, "_popen", staticmethod(slow_popen)), patch(
        "top_down_planning.orchestrator.provider_turns.BOUNDARY_WORKER_CLEANUP_SECONDS",
        0.2,
    ):
        _drain_provider_turn(
            provider,
            "sess-late-popen",
            allowed_signals=frozenset(),
            on_boundary=LiteralBoundarySignal("paused"),
        )
    assert provider.settled == ["sess-late-popen"]
    assert owned_boundary_workers() == ()
    assert unreaped_boundary_workers() == ()


def test_sweep_continues_after_ordinary_exception_then_aggregates() -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    first = BoundaryWorker()
    second = BoundaryWorker()
    first._mark_unreaped()
    second._mark_unreaped()
    seen: list[int] = []

    def boom(self, *, cleanup_timeout=None, deadline=None):
        del cleanup_timeout, deadline
        seen.append(id(self))
        raise RuntimeError(f"close failed {id(self)}")

    try:
        with patch.object(BoundaryWorker, "close", boom):
            with pytest.raises(ProviderRunError, match="failed to stop"):
                reap_unreaped_boundary_workers(timeout=0.4)
        assert id(first) in seen and id(second) in seen
    finally:
        first._clear_ownership(None)
        second._clear_ownership(None)


def test_teardown_reraises_keyboard_interrupt_after_best_effort_cleanup() -> None:
    from core_tools.provider import StubProvider

    provider = StubProvider()
    terminated = {"n": 0}

    def terminate_all_sessions():
        terminated["n"] += 1
        return []

    provider.terminate_all_sessions = terminate_all_sessions  # type: ignore[method-assign]
    with patch(
        "top_down_planning.orchestrator.provider_turns.reap_unreaped_boundary_workers",
        side_effect=KeyboardInterrupt,
    ):
        with pytest.raises(KeyboardInterrupt):
            teardown_provider_sessions(
                provider,
                append_event=lambda *_a, **_k: None,
                emit_console=lambda *_a, **_k: None,
                run_id="run-ki",
                phase=PLANNING,
            )
    assert terminated["n"] == 1


def test_teardown_does_not_wrap_keyboard_interrupt_as_teardown_error() -> None:
    from core_tools.provider import StubProvider

    provider = StubProvider()
    with patch(
        "top_down_planning.orchestrator.provider_turns.reap_unreaped_boundary_workers",
        side_effect=KeyboardInterrupt,
    ):
        with pytest.raises(KeyboardInterrupt):
            teardown_provider_sessions(
                provider,
                append_event=lambda *_a, **_k: None,
                emit_console=lambda *_a, **_k: None,
                run_id="run-ki-wrap",
                phase=PLANNING,
            )
