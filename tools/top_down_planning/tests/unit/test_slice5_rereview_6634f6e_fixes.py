"""Slice 5 rereview 6634f6e: killable helper launch and pipe ownership."""

from __future__ import annotations

import os
import sys
import threading
import time
from unittest.mock import patch

import pytest

from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.orchestrator.provider_turns import (
    _CONSTRUCTOR_HELPER,
    owned_boundary_workers,
    unreaped_boundary_workers,
)


def _popen_threads() -> list[threading.Thread]:
    return [
        thread
        for thread in threading.enumerate()
        if thread.name == "tdp-boundary-popen" and thread.is_alive()
    ]


def _fd_count() -> int:
    for path in ("/dev/fd", "/proc/self/fd"):
        try:
            return len(os.listdir(path))
        except OSError:
            continue
    return 0


def test_constructor_helper_is_the_worker_not_a_supervisor() -> None:
    assert "subprocess.Popen" not in _CONSTRUCTOR_HELPER
    assert "_boundary_worker_loop" in _CONSTRUCTOR_HELPER


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX boundary worker")
def test_host_posix_spawn_never_returning_does_not_grow_owners() -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    blocked = threading.Event()
    calls = {"n": 0}
    real_spawn = os.posix_spawn

    def maybe_block(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            blocked.wait(timeout=30)
            raise OSError("posix_spawn still blocked")
        return real_spawn(*args, **kwargs)

    baseline_threads = len(_popen_threads())
    baseline_fds = _fd_count()
    try:
        with patch("os.posix_spawn", maybe_block), patch(
            "core_tools.provider.process_cleanup.os.posix_spawn",
            maybe_block,
        ):
            first = BoundaryWorker()
            try:
                first.start(deadline=time.monotonic() + 0.08, wait_ready=False)
            except ProviderRunError:
                pass
            try:
                first.close(cleanup_timeout=0.15)
            except ProviderRunError:
                pass
            assert len(_popen_threads()) <= baseline_threads + 1
            second = BoundaryWorker()
            second.start(deadline=time.monotonic() + 2.0, wait_ready=True)
            try:
                second.close(cleanup_timeout=1.0)
            except ProviderRunError:
                pass
            assert owned_boundary_workers() == ()
            assert unreaped_boundary_workers() == ()
            assert _fd_count() <= baseline_fds + 16
    finally:
        blocked.set()
        for thread in _popen_threads():
            thread.join(timeout=1.0)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX boundary worker")
def test_helper_launch_exception_does_not_leak_result_pipes() -> None:
    from top_down_planning.orchestrator.provider_turns import BoundaryWorker

    def boom(*_args, **_kwargs):
        raise OSError("posix_spawn failed")

    baseline_fds = _fd_count()
    with patch(
        "top_down_planning.orchestrator.provider_turns.posix_spawn_session_leader",
        boom,
    ):
        for _ in range(20):
            worker = BoundaryWorker()
            with pytest.raises(ProviderRunError):
                worker.start(deadline=time.monotonic() + 0.2, wait_ready=True)
            try:
                worker.close(cleanup_timeout=0.1)
            except ProviderRunError:
                pass
            assert owned_boundary_workers() == ()
            assert unreaped_boundary_workers() == ()
            assert _fd_count() <= baseline_fds + 8
    assert _fd_count() <= baseline_fds + 8
