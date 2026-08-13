"""Unit tests for provider subprocess cleanup."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.cursor import CursorProvider, default_process_runner
from core_tools.provider.process_cleanup import (
    ProcessGroupState,
    is_pid_alive,
    process_group_state,
    terminate_pid_tree,
    terminate_process_tree,
)
from core_tools.provider.stub import StubProvider
from tests.conftest import spawn_sigterm_ignoring_leader_with_child, tracked_turn_proc


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_terminate_process_tree_kills_child_process(tmp_path: Path) -> None:
    proc, child_pid = spawn_sigterm_ignoring_leader_with_child(tmp_path)
    try:
        cleaned = terminate_process_tree(proc)
        from core_tools.provider.process_identity import _pidfd_supported

        child_alive = is_pid_alive(child_pid)
        if _pidfd_supported():
            assert cleaned is True
            assert not child_alive
        else:
            assert not (cleaned is True and child_alive)
    finally:
        if is_pid_alive(child_pid):
            os.kill(child_pid, signal.SIGKILL)
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_process_group_state_unverifiable_without_proc(monkeypatch) -> None:
    import os

    monkeypatch.setattr(sys, "platform", "linux", raising=False)
    monkeypatch.setattr(os.path, "isdir", lambda path: False)
    assert process_group_state(4242) is ProcessGroupState.UNVERIFIABLE


def test_cursor_provider_terminate_all_sessions_kills_tracked_turn(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=lambda argv, cwd: iter(()),
        binary=str(agent_path),
        skip_probe=True,
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=sys.platform != "win32",
    )
    provider._tracked_turn_procs[proc.pid] = tracked_turn_proc("cursor-session-1", "planner", proc.pid, proc=proc)

    terminated = provider.terminate_all_sessions()

    assert proc.poll() is not None
    assert not provider._tracked_turn_procs
    assert any(record.get("pid") == proc.pid for record in terminated)


def test_stub_provider_list_active_sessions() -> None:
    provider = StubProvider()
    provider.script_turn([{"type": "done", "subtype": "success", "text": "ok"}])
    session_id = provider.start_primary_session("planner", {"goal": "x"})

    active = provider.list_active_sessions()

    assert active == [
        {
            "session_id": session_id,
            "role": "planner",
            "kind": "primary",
            "model": "auto",
        },
    ]


def test_stub_provider_terminate_all_sessions_clears_sessions() -> None:
    provider = StubProvider()
    provider.script_turn([{"type": "done", "subtype": "success", "text": "ok"}])
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    assert provider.get_session_reference(session_id)["session_id"] == session_id

    provider.terminate_all_sessions()

    with pytest.raises(Exception):
        provider.get_session_reference(session_id)


def test_terminate_pid_tree_returns_true_when_process_dies() -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=sys.platform != "win32",
    )
    try:
        from core_tools.provider.process_identity import _pidfd_supported

        cleaned = terminate_pid_tree(proc.pid)
        if _pidfd_supported():
            assert cleaned is True
            assert not is_pid_alive(proc.pid)
        else:
            assert cleaned is False
    finally:
        if is_pid_alive(proc.pid):
            proc.kill()
            proc.wait(timeout=5)


def test_terminate_pid_tree_returns_false_when_kill_fails() -> None:
    with patch(
        "core_tools.provider.process_cleanup.is_pid_alive",
        side_effect=[True, True, True, True],
    ):
        with patch(
            "core_tools.provider.process_cleanup._wait_pid",
            return_value=False,
        ):
            assert terminate_pid_tree(424242) is False


def test_default_process_runner_drains_large_stderr_without_deadlock(tmp_path: Path) -> None:
    script = tmp_path / "chatty_stderr.py"
    script.write_text(
        "import json, sys\n"
        "sys.stderr.write('x' * 100_000)\n"
        "sys.stderr.flush()\n"
        'print(json.dumps({"type": "assistant", "text": "ok"}))\n'
        'print(json.dumps({"type": "result", "subtype": "success", "text": "ok", "is_error": False}))\n',
        encoding="utf-8",
    )
    argv = [sys.executable, str(script)]
    lines = list(default_process_runner(argv, tmp_path))
    assert lines
