"""Slice 5 rereview 992f5a0: killable spawn, pickle-before-drain, sweep control exceptions."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from unittest.mock import patch

import pytest

from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.orchestrator.provider_turns import (
    LiteralBoundarySignal,
    _drain_provider_turn,
    owned_boundary_workers,
    reap_unreaped_boundary_workers,
    unreaped_boundary_workers,
)
from tests.unit.test_slice5_rereview_ee5de8e_fixes import _RecordingDrainProvider


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX boundary worker")
def test_wait_ready_false_returns_before_slow_popen() -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    created: list[subprocess.Popen] = []
    real_popen = BoundaryWorker._popen

    def slow_popen(*args, **kwargs):
        time.sleep(0.2)
        proc = real_popen(*args, **kwargs)
        created.append(proc)
        return proc

    worker = BoundaryWorker()
    started = time.monotonic()
    try:
        with patch.object(BoundaryWorker, "_popen", staticmethod(slow_popen)):
            worker.start(deadline=time.monotonic() + 0.05, wait_ready=False)
            assert time.monotonic() - started < 0.12
            boot = worker._boot_thread
            if boot is not None:
                boot.join(timeout=1.0)
        assert worker.proc is None
        for proc in created:
            assert proc.poll() is not None
    finally:
        worker.close(cleanup_timeout=1.0)
        try:
            reap_unreaped_boundary_workers(timeout=0.5)
        except ProviderRunError:
            pass


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX boundary worker")
def test_never_returning_popen_does_not_block_drain_controller() -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    unblock = threading.Event()

    def hang_popen(*args, **kwargs):
        del args, kwargs
        unblock.wait(timeout=60)
        raise AssertionError("Popen returned")

    provider = _RecordingDrainProvider(
        yield_event={"type": "assistant", "text": "x"},
    )
    started = time.monotonic()
    try:
        with patch.object(BoundaryWorker, "_popen", staticmethod(hang_popen)), patch(
            "top_down_planning.orchestrator.provider_turns.BOUNDARY_POLL_JOIN_SECONDS",
            0.2,
        ):
            with pytest.raises(ProviderRunError, match="exceeded timeout|failed to stop"):
                _drain_provider_turn(
                    provider,
                    "sess-hang-popen",
                    allowed_signals=frozenset(),
                    on_boundary=LiteralBoundarySignal("paused"),
                )
        assert time.monotonic() - started < 1.5
        assert provider.settled == ["sess-hang-popen"]
    finally:
        unblock.set()
        provider.released.set()
        try:
            reap_unreaped_boundary_workers(timeout=0.5)
        except ProviderRunError:
            pass


def test_unserializable_drain_callback_starts_no_worker() -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    starts = {"n": 0}
    real_start = BoundaryWorker.start

    def counting_start(self, *, deadline=None, wait_ready=True, **kwargs):
        starts["n"] += 1
        return real_start(self, deadline=deadline, wait_ready=wait_ready, **kwargs)

    def nested() -> str | None:
        threading.Event().wait()
        return "paused"

    provider = _RecordingDrainProvider(yield_event={"type": "assistant", "text": "x"})
    with patch.object(BoundaryWorker, "start", counting_start):
        with pytest.raises(ProviderRunError, match="serializable"):
            _drain_provider_turn(
                provider,
                "sess-unpickle",
                allowed_signals=frozenset(),
                on_boundary=nested,
            )
    assert starts["n"] == 0
    assert owned_boundary_workers() == ()
    assert provider.settled == ["sess-unpickle"]


def test_sweep_propagates_keyboard_interrupt() -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    worker = BoundaryWorker()
    worker._mark_unreaped()

    def exploding_close(self, **kwargs):
        del self, kwargs
        raise KeyboardInterrupt()

    try:
        with patch.object(BoundaryWorker, "close", exploding_close):
            with pytest.raises(KeyboardInterrupt):
                reap_unreaped_boundary_workers(timeout=0.2)
        assert worker in unreaped_boundary_workers()
    finally:
        BoundaryWorker.close(worker, cleanup_timeout=0.2)
        try:
            reap_unreaped_boundary_workers(timeout=0.2)
        except ProviderRunError:
            pass
