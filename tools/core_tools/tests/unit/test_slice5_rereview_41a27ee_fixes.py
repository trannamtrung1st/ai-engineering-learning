"""Slice 5 rereview 41a27ee: idle stdout deadline, remaining teardown budget, orphans."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.cursor import CursorProvider, _SubprocessStdoutIterator
from core_tools.provider.errors import ProviderTurnError, ProviderTurnStalledError
from core_tools.provider.process_identity import terminate_verified_process_identity
from tests.conftest import close_and_reap_iterator, reap_process_group, spawn_sigterm_ignoring_leader_with_child


def _idle_config() -> dict:
    return {
        "limits": {
            "provider": {
                "turn_idle_timeout_seconds": 0.08,
                "max_retries_per_call": 0,
            }
        }
    }


def _provider(tmp_path: Path, runner) -> CursorProvider:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    return CursorProvider(
        _idle_config(),
        workspace=tmp_path,
        runner=runner,
        binary=str(agent_path),
        skip_probe=True,
    )


def _script_runner(script: str):
    def runner(argv: list[str], cwd: Path):
        del argv
        return _SubprocessStdoutIterator([sys.executable, "-c", script], cwd)

    return runner


def _stream(provider: CursorProvider, session_id: str) -> list[str]:
    return list(provider.stream_events(session_id))


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX pipe idle watchdog")
def test_blank_line_then_silence_stalls_within_idle_deadline(tmp_path: Path) -> None:
    script = "print('', flush=True)\nimport time\ntime.sleep(60)\n"
    provider = _provider(tmp_path, _script_runner(script))
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    started = time.monotonic()
    with pytest.raises((ProviderTurnStalledError, ProviderTurnError)):
        _stream(provider, session_id)
    assert time.monotonic() - started <= 0.75
    assert provider._tracked_turn_procs == {}


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX pipe idle watchdog")
def test_two_lines_in_one_write_are_consumed_then_stall(tmp_path: Path) -> None:
    first = '{"type":"assistant","message":{"content":[{"type":"text","text":"one"}]}}'
    second = '{"type":"assistant","message":{"content":[{"type":"text","text":"two"}]}}'
    script = (
        "import sys\n"
        f"sys.stdout.write({first!r} + '\\n' + {second!r} + '\\n')\n"
        "sys.stdout.flush()\n"
        "import time\n"
        "time.sleep(60)\n"
    )
    provider = _provider(tmp_path, _script_runner(script))
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    started = time.monotonic()
    with pytest.raises((ProviderTurnStalledError, ProviderTurnError)):
        events = list(provider.stream_events(session_id))
        del events
    elapsed = time.monotonic() - started
    assert elapsed <= 0.75


def test_windows_silent_stdout_wait_readable_times_out(tmp_path: Path) -> None:
    script = "import time\ntime.sleep(60)\n"
    iterator = _SubprocessStdoutIterator([sys.executable, "-c", script], tmp_path)
    try:
        with patch("core_tools.provider.cursor.sys.platform", "win32"):
            with patch(
                "core_tools.provider.cursor._windows_pipe_has_data",
                return_value=False,
            ):
                started = time.monotonic()
                assert iterator.wait_readable(0.05) is False
                assert time.monotonic() - started <= 0.25
    finally:
        close_and_reap_iterator(iterator)


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_first_teardown_stage_leaves_remaining_budget_for_identity_refresh(
    tmp_path: Path,
) -> None:
    proc, child_pid = spawn_sigterm_ignoring_leader_with_child(tmp_path)
    timeout = 0.3

    def slow_popen(target, *, pgid=None, timeout=None):
        del target, pgid
        time.sleep(min(0.24, timeout or 0.0))
        return {"drain": "survivors"}

    started = time.monotonic()
    try:
        with patch(
            "core_tools.provider.process_identity._terminate_via_bound_popen",
            side_effect=slow_popen,
        ):
            terminate_verified_process_identity(None, proc=proc, timeout=timeout)
        elapsed = time.monotonic() - started
        assert elapsed <= timeout + 0.35
    finally:
        reap_process_group(proc, extra_pids=(child_pid,))
        try:
            os.kill(child_pid, 0)
            alive = True
        except OSError:
            alive = False
        assert alive is False
        assert proc.poll() is not None
