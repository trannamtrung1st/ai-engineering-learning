"""CursorProvider fail-closed session termination (S5-RR4-001)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.cursor import CursorProvider
from core_tools.provider.errors import ProviderSessionTerminationError, ProviderTurnError


def test_terminate_session_fails_when_tracked_pid_kill_fails(tmp_path: Path) -> None:
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
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=sys.platform != "win32",
    )
    provider._tracked_turn_procs[proc.pid] = (session_id, "planner")

    with patch(
        "core_tools.provider.cursor.terminate_pid_tree",
        return_value=False,
    ):
        with pytest.raises(ProviderSessionTerminationError) as exc_info:
            provider.terminate_session(session_id)

    assert proc.pid in exc_info.value.surviving_pids
    assert session_id in provider._sessions
    assert proc.pid in provider._tracked_turn_procs
    proc.kill()
    proc.wait(timeout=5)


def test_terminate_session_removes_session_only_after_confirmed_death(tmp_path: Path) -> None:
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
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=sys.platform != "win32",
    )
    provider._tracked_turn_procs[proc.pid] = (session_id, "planner")

    provider.terminate_session(session_id)

    assert session_id not in provider._sessions
    assert proc.pid not in provider._tracked_turn_procs
    assert proc.poll() is not None


def test_wrap_runner_kill_failure_leaves_pid_tracked(tmp_path: Path) -> None:
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
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=sys.platform != "win32",
    )
    provider._tracked_turn_procs[proc.pid] = (session_id, "planner")

    with patch(
        "core_tools.provider.cursor.terminate_pid_tree",
        return_value=False,
    ):
        records = provider._terminate_tracked_turn_procs_for_session(session_id)

    assert records == [
        {
            "pid": proc.pid,
            "role": "planner",
            "session_id": session_id,
            "reason": "termination_failed",
        }
    ]
    assert proc.pid in provider._tracked_turn_procs
    proc.kill()
    proc.wait(timeout=5)


def test_terminate_all_sessions_keeps_failed_session_registered(tmp_path: Path) -> None:
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
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=sys.platform != "win32",
    )
    provider._tracked_turn_procs[proc.pid] = (session_id, "planner")

    with patch(
        "core_tools.provider.cursor.terminate_pid_tree",
        return_value=False,
    ):
        records = provider.terminate_all_sessions()

    assert any(record.get("reason") == "termination_failed" for record in records)
    assert session_id in provider._sessions
    assert proc.pid in provider._tracked_turn_procs
    proc.kill()
    proc.wait(timeout=5)
