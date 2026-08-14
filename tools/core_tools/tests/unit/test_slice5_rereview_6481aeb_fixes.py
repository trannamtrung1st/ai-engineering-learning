"""Slice 5 rereview 6481aeb: one lifecycle deadline and idle-stream ownership."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core_tools.provider.cursor import CursorProvider, _SubprocessStdoutIterator
from core_tools.provider.errors import (
    ProviderLifecycleTimeoutError,
    ProviderTurnError,
    ProviderTurnStalledError,
)
from core_tools.provider.process_cleanup import terminate_process_tree
from core_tools.provider.process_identity import terminate_verified_process_identity
from tests.conftest import reap_process_group, spawn_sigterm_ignoring_leader_with_child, tracked_turn_proc


def _idle_stream_survivors() -> list[threading.Thread]:
    return [
        thread
        for thread in threading.enumerate()
        if thread.name == "cursor-idle-stream" and thread.is_alive()
    ]


def _stalling_stdout_runner(first_line: str | None = None):
    script_lines = []
    if first_line is not None:
        script_lines.append(f"print({first_line!r}, flush=True)")
    script_lines.append("import time")
    script_lines.append("time.sleep(60)")
    script = "\n".join(script_lines)

    def runner(argv: list[str], cwd: Path):
        del argv
        return _SubprocessStdoutIterator([sys.executable, "-c", script], cwd)

    return runner


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_abort_turn_timeout_stays_within_caller_budget(tmp_path: Path) -> None:
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
    proc, _child_pid = spawn_sigterm_ignoring_leader_with_child(tmp_path)
    provider._tracked_turn_procs[proc.pid] = tracked_turn_proc(
        session_id,
        "planner",
        proc.pid,
        proc=proc,
    )
    timeout = 0.2
    started = time.monotonic()
    try:
        try:
            provider.abort_turn(session_id, timeout=timeout)
        except ProviderLifecycleTimeoutError:
            pass
        elapsed = time.monotonic() - started
        assert elapsed <= timeout + 0.35
    finally:
        reap_process_group(proc, extra_pids=(_child_pid,))


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_bound_popen_then_drain_share_remaining_budget(tmp_path: Path) -> None:
    proc, _child_pid = spawn_sigterm_ignoring_leader_with_child(tmp_path)
    timeout = 0.25

    def slow_popen(target, *, pgid=None, timeout=None):
        del target, pgid
        time.sleep(min(0.18, timeout or 0.0))
        return {"drain": "survivors"}

    started = time.monotonic()
    try:
        with patch(
            "core_tools.provider.process_identity._terminate_via_bound_popen",
            side_effect=slow_popen,
        ):
            terminate_verified_process_identity(
                None,
                proc=proc,
                timeout=timeout,
            )
        elapsed = time.monotonic() - started
        assert elapsed <= timeout + 0.35
    finally:
        reap_process_group(proc, extra_pids=(_child_pid,))


def test_windows_terminate_then_kill_shares_one_deadline() -> None:
    waits: list[float | None] = []
    proc = MagicMock()
    proc.poll.side_effect = [None, None, None, 1]

    def wait(*, timeout=None):
        waits.append(timeout)
        time.sleep(min(0.12, timeout or 0.0))
        raise subprocess.TimeoutExpired(cmd="proc", timeout=timeout)

    proc.wait.side_effect = wait
    proc.terminate.return_value = None
    proc.kill.return_value = None
    timeout = 0.3
    started = time.monotonic()
    with patch("core_tools.provider.process_cleanup.sys.platform", "win32"):
        terminate_process_tree(proc, timeout=timeout)
    elapsed = time.monotonic() - started
    assert elapsed <= timeout + 0.2
    assert len(waits) == 2
    assert waits[0] is not None and waits[1] is not None
    assert waits[0] <= timeout
    assert waits[1] < waits[0]
    assert waits[1] <= timeout - 0.05


@pytest.mark.skipif(sys.platform != "darwin", reason="Darwin ps inspection only")
def test_darwin_process_group_ps_uses_remaining_budget() -> None:
    seen_timeouts: list[float] = []

    def blocking_run(*args, **kwargs):
        timeout = kwargs.get("timeout")
        if timeout is not None:
            seen_timeouts.append(float(timeout))
            time.sleep(min(2.0, float(timeout)))
        raise subprocess.TimeoutExpired(cmd=args[0] if args else "ps", timeout=timeout)

    timeout = 0.2
    started = time.monotonic()
    with patch(
        "core_tools.provider.process_cleanup.subprocess.run",
        side_effect=blocking_run,
    ):
        from core_tools.provider.process_cleanup import list_process_group_pids

        list_process_group_pids(os.getpgrp(), timeout=timeout)
    elapsed = time.monotonic() - started
    assert elapsed <= timeout + 0.35
    assert seen_timeouts
    assert max(seen_timeouts) <= timeout + 0.05


@pytest.mark.skipif(sys.platform == "win32", reason="select on pipes")
def test_idle_watchdog_owns_subprocess_that_ignores_close(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    first = '{"type":"assistant","message":{"content":[{"type":"text","text":"start"}]}}'
    provider = CursorProvider(
        {
            "limits": {
                "provider": {
                    "turn_idle_timeout_seconds": 0.05,
                    "max_retries_per_call": 0,
                }
            }
        },
        workspace=tmp_path,
        runner=_stalling_stdout_runner(first),
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    with pytest.raises((ProviderTurnStalledError, ProviderTurnError)):
        list(provider.stream_events(session_id))
    assert _idle_stream_survivors() == []
