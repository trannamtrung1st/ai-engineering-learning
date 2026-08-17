"""Slice 5 rereview 27eaa0b: Cursor lifecycle timeout honors caller budget."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from core_tools.provider.cursor import CursorProvider
from core_tools.provider.errors import ProviderLifecycleTimeoutError
from tests.conftest import (
    reap_process_group,
    spawn_sigterm_ignoring_leader_with_child,
    tracked_turn_proc,
)


def test_abort_turn_timeout_tracks_caller_budget_not_fixed_drain_waits(
    tmp_path: Path,
) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=lambda argv, cwd: iter(()),
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    proc, child_pid = spawn_sigterm_ignoring_leader_with_child(tmp_path)
    provider._tracked_turn_procs[proc.pid] = tracked_turn_proc(
        session_id,
        "planner",
        proc.pid,
        proc=proc,
    )
    started = time.monotonic()
    try:
        with pytest.raises(ProviderLifecycleTimeoutError):
            provider.abort_turn(session_id, timeout=0.3)
        elapsed = time.monotonic() - started
        assert elapsed <= 0.3 + 0.35
        assert proc.pid in provider._tracked_turn_procs
    finally:
        reap_process_group(proc, extra_pids=(child_pid,))
