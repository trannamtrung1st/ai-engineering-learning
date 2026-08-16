"""Slice 5 rereview 084505: hung READY teardown, sweep transients, no helper thread."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from unittest.mock import patch

import pytest

from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.orchestrator.provider_turns import (
    reap_unreaped_boundary_workers,
    unreaped_boundary_workers,
)


def _hang_ready(*args, **kwargs):
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


def _popen_threads() -> list[str]:
    return [
        item.name
        for item in threading.enumerate()
        if item.name in {"tdp-boundary-popen", "tdp-boundary-start"}
    ]


def test_hung_ready_leaves_no_popen_helper_thread() -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    worker = BoundaryWorker()
    started = time.monotonic()
    try:
        with patch.object(BoundaryWorker, "_popen", staticmethod(_hang_ready)):
            with pytest.raises(ProviderRunError, match="exceeded timeout"):
                worker.start(deadline=time.monotonic() + 0.05)
        assert time.monotonic() - started < 0.25
        worker.close(cleanup_timeout=1.0)
        assert _popen_threads() == []
        assert worker not in unreaped_boundary_workers() or worker.proc is None
    finally:
        worker.close(cleanup_timeout=1.0)
        try:
            reap_unreaped_boundary_workers(timeout=0.5)
        except ProviderRunError:
            pass


def test_repeated_hung_ready_starts_do_not_grow_helper_threads() -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    before = len(threading.enumerate())
    for _ in range(20):
        worker = BoundaryWorker()
        try:
            with patch.object(BoundaryWorker, "_popen", staticmethod(_hang_ready)):
                with pytest.raises(ProviderRunError, match="exceeded timeout"):
                    worker.start(deadline=time.monotonic() + 0.05)
        finally:
            worker.close(cleanup_timeout=0.5)
    try:
        reap_unreaped_boundary_workers(timeout=1.0)
    except ProviderRunError:
        pass
    assert _popen_threads() == []
    assert len(threading.enumerate()) <= before + 3


def test_sweep_ignores_transient_close_error_when_registry_drains() -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    worker = BoundaryWorker()
    worker._mark_unreaped()
    calls = {"n": 0}
    real_close = BoundaryWorker.close

    def flaky_close(self, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("transient")
        return real_close(self, **kwargs)

    try:
        with patch.object(BoundaryWorker, "close", flaky_close):
            reap_unreaped_boundary_workers(timeout=1.0)
        assert worker not in unreaped_boundary_workers()
    finally:
        BoundaryWorker.close(worker, cleanup_timeout=0.2)
        try:
            reap_unreaped_boundary_workers(timeout=0.2)
        except ProviderRunError:
            pass
