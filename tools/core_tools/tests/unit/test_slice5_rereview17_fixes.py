"""Slice 5 seventeenth re-review regressions (S5-RR17-001 through S5-RR17-005)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.cursor import CursorProvider, _TrackedTurnProc, default_process_runner
from core_tools.provider.process_cleanup import ProcessGroupState, is_pid_alive, terminate_process_tree
from core_tools.provider.process_identity import ProcessIdentity
from core_tools.provider.session_janitor import janitor_command


def _provider(tmp_path: Path) -> CursorProvider:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    return CursorProvider(
        {},
        workspace=tmp_path,
        runner=lambda argv, cwd: iter(()),
        binary=str(agent_path),
        skip_probe=True,
    )


def _wait_pid_file(path: Path, timeout: float = 2.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return int(text)
        time.sleep(0.05)
    raise AssertionError(f"pid file was not written: {path}")


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_janitor_keeps_anchor_until_sigterm_ignoring_descendant_is_gone(
    tmp_path: Path,
) -> None:
    child_pid_file = tmp_path / "child.pid"
    script = (
        "import os, signal, sys, time\n"
        f"child_pid_file = {str(child_pid_file)!r}\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        "with open(child_pid_file, 'w', encoding='utf-8') as handle:\n"
        "    handle.write(str(child))\n"
        "sys.stdout.write('agent-done\\n')\n"
        "sys.stdout.flush()\n"
        "os._exit(0)\n"
    )
    proc = subprocess.Popen(
        janitor_command([sys.executable, "-c", script]),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        text=True,
    )
    child_pid = None
    try:
        line = proc.stdout.readline() if proc.stdout is not None else ""
        assert "agent-done" in line
        child_pid = _wait_pid_file(child_pid_file)
        time.sleep(0.1)
        assert proc.poll() is None
        assert is_pid_alive(child_pid) is True
        proc.wait(timeout=15)
        assert is_pid_alive(child_pid) is False
        assert proc.returncode == 0
    finally:
        if child_pid is not None and is_pid_alive(child_pid):
            os.kill(child_pid, signal.SIGKILL)
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_provider_stream_does_not_hang_when_descendant_inherits_stdout(
    tmp_path: Path,
) -> None:
    child_pid_file = tmp_path / "child.pid"
    script = (
        "import os, signal, sys, time\n"
        f"child_pid_file = {str(child_pid_file)!r}\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        "with open(child_pid_file, 'w', encoding='utf-8') as handle:\n"
        "    handle.write(str(child))\n"
        "print('ok', flush=True)\n"
    )
    done = threading.Event()
    lines: list[str] = []
    error: list[BaseException] = []

    def consume() -> None:
        try:
            lines.extend(list(default_process_runner([sys.executable, "-c", script], tmp_path)))
        except BaseException as exc:
            error.append(exc)
        finally:
            done.set()

    thread = threading.Thread(target=consume)
    thread.start()
    finished = done.wait(timeout=15)
    child_pid = _wait_pid_file(child_pid_file)
    assert finished is True
    assert error == []
    assert "ok" in lines
    assert is_pid_alive(child_pid) is False


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_bound_stop_uses_control_pipe_not_killpg_after_reap(tmp_path: Path) -> None:
    script = "import time; time.sleep(60)\n"
    proc = subprocess.Popen(
        janitor_command([sys.executable, "-c", script]),
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        text=True,
    )
    try:
        with patch("core_tools.provider.process_identity.os.killpg") as killpg:
            assert terminate_process_tree(proc) is True
        killpg.assert_not_called()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_late_descendant_keeps_tracked_tree_unresolved(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    leader = ProcessIdentity(pid=4242, start_time="100")
    entry = _TrackedTurnProc(
        session_id=session_id,
        role="planner",
        proc=None,
        identity=leader,
        pgid=4242,
        member_identities=(leader,),
    )
    entry.group_observed_gone = False
    provider._tracked_turn_procs[4242] = entry

    with patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ):
        with patch(
            "core_tools.provider.cursor.process_group_state",
            return_value=ProcessGroupState.LIVE,
        ):
            assert provider._tracked_tree_is_live(
                provider._tracked_turn_procs[4242]
            ) is True
            assert session_id in {s["session_id"] for s in provider.list_active_sessions()}


def test_group_reuse_after_gone_is_not_owned(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    leader = ProcessIdentity(pid=4242, start_time="100")
    entry = _TrackedTurnProc(
        session_id=session_id,
        role="planner",
        proc=None,
        identity=leader,
        pgid=4242,
        member_identities=(leader,),
    )
    entry.group_observed_gone = True
    provider._tracked_turn_procs[4242] = entry

    with patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ):
        with patch(
            "core_tools.provider.cursor.process_group_state",
            return_value=ProcessGroupState.LIVE,
        ):
            assert provider._tracked_tree_is_live(
                provider._tracked_turn_procs[4242]
            ) is False


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_janitor_cleans_sigterm_ignoring_child_after_unexpected_agent_exit(
    tmp_path: Path,
) -> None:
    child_pid_file = tmp_path / "child.pid"
    agent_pid_file = tmp_path / "agent.pid"
    script = (
        "import os, signal, sys, time\n"
        f"child_pid_file = {str(child_pid_file)!r}\n"
        f"agent_pid_file = {str(agent_pid_file)!r}\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        "with open(child_pid_file, 'w', encoding='utf-8') as handle:\n"
        "    handle.write(str(child))\n"
        "with open(agent_pid_file, 'w', encoding='utf-8') as handle:\n"
        "    handle.write(str(os.getpid()))\n"
        "sys.stdout.write('agent-ready\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(60)\n"
    )
    proc = subprocess.Popen(
        janitor_command([sys.executable, "-c", script]),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        text=True,
    )
    child_pid = None
    try:
        line = proc.stdout.readline() if proc.stdout is not None else ""
        assert "agent-ready" in line
        child_pid = _wait_pid_file(child_pid_file)
        agent_pid = _wait_pid_file(agent_pid_file)
        os.kill(agent_pid, signal.SIGKILL)
        time.sleep(0.1)
        assert proc.poll() is None
        assert is_pid_alive(child_pid) is True
        proc.wait(timeout=15)
        assert is_pid_alive(child_pid) is False
    finally:
        if child_pid is not None and is_pid_alive(child_pid):
            os.kill(child_pid, signal.SIGKILL)
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


@pytest.mark.skipif(sys.platform != "darwin", reason="Darwin process-group contract")
def test_darwin_janitor_cleans_sigterm_ignoring_child(tmp_path: Path) -> None:
    test_janitor_keeps_anchor_until_sigterm_ignoring_descendant_is_gone(tmp_path)
