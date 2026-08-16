"""Slice 5 rereview 4ef1c72: pending-to-owned transfer."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from top_down_planning.orchestrator.provider_turns import (
    BoundaryWorker,
    pending_boundary_spawns,
)


class _FakeHelper:
    def __init__(self, pid: int = 4242) -> None:
        self.pid = pid

    def poll(self):
        return None

    def kill(self) -> None:
        return None

    def wait(self, timeout=None):
        del timeout
        return -1


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX boundary worker")
def test_returned_helper_stays_pending_until_pid_is_recorded() -> None:
    worker = BoundaryWorker()
    helper = _FakeHelper()
    try:
        with patch(
            "top_down_planning.orchestrator.provider_turns.posix_spawn_session_leader",
            lambda *_a, **_k: helper,
        ), patch("select.select", return_value=([3], [], [])), patch(
            "os.read", return_value=b"OK\n"
        ), patch("os.close"), patch("os.set_inheritable"), patch(
            "os.pipe", return_value=(3, 4)
        ), patch("os.dup", lambda fd: fd):
            result = worker._popen_via_constructor_helper(7, env={}, deadline=None)
        assert result is helper
        assert worker in pending_boundary_spawns()
        worker._record_pid(helper)
        assert worker not in pending_boundary_spawns()
    finally:
        worker._clear_ownership(helper.pid)
