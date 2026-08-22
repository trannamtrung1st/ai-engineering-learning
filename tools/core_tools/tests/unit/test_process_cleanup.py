"""Unit tests for provider subprocess cleanup."""

from __future__ import annotations

import os
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
    is_pid_reaped,
    process_group_state,
    terminate_pid_tree,
    terminate_process_tree,
)
from core_tools.provider.stub import StubProvider
from tests.conftest import (
    _ignore_leftover_python_descendant,
    _is_pytest_infrastructure,
    _python_descendant_pids,
    tracked_turn_proc,
    wait_published_pid,
)


def test_leftover_scan_ignores_pytest_and_multiprocessing_helpers() -> None:
    assert _is_pytest_infrastructure(
        "python -c from multiprocessing.resource_tracker import main"
    )
    assert _is_pytest_infrastructure("python -m multiprocessing.forkserver")
    assert _is_pytest_infrastructure("/usr/bin/python execnet gateway")
    assert _is_pytest_infrastructure(
        "python -c from multiprocessing.spawn import spawn_main; spawn_main()"
    )
    assert not _is_pytest_infrastructure("python -c import time; time.sleep(60)")


def test_leftover_scan_ignores_defunct_python_zombies() -> None:
    assert _ignore_leftover_python_descendant("[python] <defunct>")
    assert _ignore_leftover_python_descendant("python <defunct>")
    assert not _ignore_leftover_python_descendant(
        "python -c import time; time.sleep(60)"
    )


def test_leftover_scan_ignores_zombie_pid_with_live_looking_cmdline(monkeypatch) -> None:
    monkeypatch.setattr("tests.conftest._linux_stat_is_zombie", lambda pid: pid == 4242)
    assert _ignore_leftover_python_descendant(
        "python -c import time; time.sleep(60)",
        pid=4242,
    )


def test_leftover_scan_ignores_ps_zombie_state_without_proc(monkeypatch) -> None:
    monkeypatch.setattr("tests.conftest._linux_stat_is_zombie", lambda _pid: False)
    assert _ignore_leftover_python_descendant(
        "python -c import time; time.sleep(60)",
        pid=4242,
        ps_state="Z",
    )
    assert _ignore_leftover_python_descendant(
        "python -c import time; time.sleep(60)",
        pid=4242,
        ps_state="Z+",
    )
    assert not _ignore_leftover_python_descendant(
        "python -c import time; time.sleep(60)",
        pid=4242,
        ps_state="S",
    )


def test_python_descendant_scan_omits_linux_zombies(monkeypatch) -> None:
    parent = 1000
    zombie = 2000
    monkeypatch.setattr(
        "tests.conftest.subprocess.check_output",
        lambda *_args, **_kwargs: (
            f"{zombie} {parent} S python -c import time; time.sleep(60)\n"
        ),
    )
    monkeypatch.setattr(
        "tests.conftest._process_command",
        lambda _pid: "python -c import time; time.sleep(60)",
    )
    monkeypatch.setattr("tests.conftest._linux_stat_is_zombie", lambda pid: pid == zombie)
    assert _python_descendant_pids(parent) == {}


def test_python_descendant_scan_omits_darwin_zombies_without_proc_stat(
    monkeypatch,
) -> None:
    parent = 1000
    zombie = 2000
    monkeypatch.setattr(
        "tests.conftest.subprocess.check_output",
        lambda *_args, **_kwargs: (
            f"{zombie} {parent} Z+ python -c import time; time.sleep(60)\n"
        ),
    )
    monkeypatch.setattr(
        "tests.conftest._process_command",
        lambda _pid: "python -c import time; time.sleep(60)",
    )
    monkeypatch.setattr("tests.conftest._linux_stat_is_zombie", lambda _pid: False)
    assert _python_descendant_pids(parent) == {}


def test_python_descendant_scan_keeps_live_python_child(monkeypatch) -> None:
    parent = 1000
    child = 2001
    command = "python -c import time; time.sleep(60)"
    monkeypatch.setattr(
        "tests.conftest.subprocess.check_output",
        lambda *_args, **_kwargs: f"{child} {parent} S {command}\n",
    )
    monkeypatch.setattr("tests.conftest._process_command", lambda _pid: command)
    monkeypatch.setattr("tests.conftest._linux_stat_is_zombie", lambda _pid: False)
    assert _python_descendant_pids(parent) == {child: command}


def test_wait_published_pid_ignores_empty_file_until_integer(tmp_path: Path) -> None:
    path = tmp_path / "child.pid"
    path.write_text("", encoding="utf-8")
    assert wait_published_pid(path, attempts=1) is None
    path.write_text("4242\n", encoding="utf-8")
    assert wait_published_pid(path, attempts=1) == 4242


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_process_group_state_unverifiable_without_proc(monkeypatch) -> None:
    import os

    monkeypatch.setattr(sys, "platform", "linux", raising=False)
    monkeypatch.setattr(os.path, "isdir", lambda path: False)
    assert process_group_state(4242) is ProcessGroupState.UNVERIFIABLE


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_terminate_process_tree_fails_closed_when_group_unverifiable(
    monkeypatch,
) -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        monkeypatch.setattr(sys, "platform", "linux", raising=False)
        monkeypatch.setattr(os.path, "isdir", lambda path: False)
        assert terminate_process_tree(proc) is False
        # Bound Popen may still terminate the leader; PGID occupants must not be signaled.
    finally:
        proc.kill()
        proc.wait(timeout=5)


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
        cleaned = terminate_pid_tree(proc.pid)
        assert cleaned is True
        assert not is_pid_alive(proc.pid)
        assert is_pid_reaped(proc.pid)
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
