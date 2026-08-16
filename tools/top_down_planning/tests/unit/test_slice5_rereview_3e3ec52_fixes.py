"""Slice 5 rereview 3e3ec52: spawn FD ownership and close budget."""

from __future__ import annotations

import os
import sys
import threading
import time
from unittest.mock import patch

import pytest

from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.orchestrator.provider_turns import (
    BoundaryWorker,
    pending_boundary_spawns,
)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX boundary worker")
def test_close_does_not_extend_cleanup_budget_with_remaining_startup() -> None:
    worker = BoundaryWorker()
    worker._spawn_deadline = time.monotonic() + 30.0
    worker._boot_thread = threading.Thread(target=lambda: time.sleep(0.4), daemon=True)
    worker._boot_thread.start()
    started = time.monotonic()
    with pytest.raises(ProviderRunError):
        worker.close(cleanup_timeout=0.05)
    elapsed = time.monotonic() - started
    worker._boot_thread.join(timeout=1.0)
    assert elapsed < 0.2


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX boundary worker")
def test_close_leaves_child_sock_open_while_boot_is_blocked() -> None:
    worker = BoundaryWorker()
    blocked = threading.Event()
    release = threading.Event()

    def hang(*_args, **_kwargs):
        blocked.set()
        release.wait(timeout=30)
        raise OSError("posix_spawn still blocked")

    try:
        with patch("os.posix_spawn", hang), patch(
            "core_tools.provider.process_cleanup.os.posix_spawn",
            hang,
        ):
            with pytest.raises(ProviderRunError):
                worker.start(deadline=time.monotonic() + 0.08, wait_ready=True)
            assert blocked.wait(timeout=1.0)
            child = worker._child_sock
            assert child is not None
            old_fd = child.fileno()
            try:
                worker.close(cleanup_timeout=0.05)
            except ProviderRunError:
                pass
            assert worker._child_sock is not None
            assert worker._child_sock.fileno() == old_fd
            extra_r, extra_w = os.pipe()
            try:
                assert extra_r != old_fd
                assert extra_w != old_fd
            finally:
                os.close(extra_r)
                os.close(extra_w)
            assert pending_boundary_spawns()
    finally:
        release.set()
        boot = worker._boot_thread
        if boot is not None:
            boot.join(timeout=1.0)
