"""Shared pytest helpers for core_tools tests."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from core_tools.provider.cursor import _TrackedTurnProc
from core_tools.provider.process_identity import ProcessIdentity


def tracked_turn_proc(
    session_id: str,
    role: str,
    pid: int,
    *,
    proc: subprocess.Popen | None = None,
    start_time: str = "100",
    run_id: str | None = None,
) -> _TrackedTurnProc:
    from core_tools.provider.process_cleanup import read_process_group_id
    from core_tools.provider.process_identity import (
        capture_process_group_identities,
        read_process_identity,
    )

    identity = ProcessIdentity(pid=pid, start_time=start_time, run_id=run_id)
    if proc is not None:
        live_identity = read_process_identity(proc.pid, run_id=run_id)
        if live_identity is not None:
            identity = live_identity
    pgid = read_process_group_id(pid) if proc is not None else None
    members: tuple[ProcessIdentity, ...] | None = None
    if proc is not None and identity is not None:
        captured = capture_process_group_identities(identity)
        if captured is not None:
            members = tuple(captured)
    return _TrackedTurnProc(
        session_id=session_id,
        role=role,
        proc=proc,
        identity=identity,
        pgid=pgid,
        member_identities=members,
    )


def spawn_sigterm_ignoring_leader_with_child(
    tmp_path: Path,
) -> tuple[subprocess.Popen[str], int]:
    """Start a leader that ignores SIGTERM and forks a sleeping child."""

    child_pid_file = tmp_path / "child.pid"
    script = (
        "import os, signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"child_pid_file = {str(child_pid_file)!r}\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        "with open(child_pid_file, 'w', encoding='utf-8') as handle:\n"
        "    handle.write(str(child))\n"
        "time.sleep(60)\n"
    )
    from core_tools.provider.session_janitor import janitor_command

    proc = subprocess.Popen(
        janitor_command([sys.executable, "-c", script]),
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        text=True,
    )
    for _ in range(40):
        if child_pid_file.exists():
            return proc, int(child_pid_file.read_text(encoding="utf-8").strip())
        time.sleep(0.05)
    reap_process_group(proc)
    raise AssertionError("child PID file was not written")


def reap_process_group(
    proc: subprocess.Popen[str],
    extra_pids: tuple[int, ...] = (),
) -> None:
    """SIGKILL the spawned session and any known descendants, then wait."""

    pgid: int | None = None
    try:
        if proc.pid:
            pgid = os.getpgid(proc.pid)
    except OSError:
        pgid = None
    if pgid is not None:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except OSError:
            pass
    for pid in extra_pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    if proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=5)
    except Exception:
        pass
    for pid in extra_pids:
        for _ in range(20):
            try:
                os.kill(pid, 0)
            except OSError:
                break
            time.sleep(0.05)


def _python_descendant_pids(root_pid: int) -> dict[int, str]:
    output = subprocess.check_output(
        ["ps", "-axww", "-o", "pid=,ppid=,command="],
        text=True,
    )
    by_parent: dict[int, list[int]] = {}
    commands: dict[int, str] = {}
    for line in output.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        pid = int(parts[0])
        ppid = int(parts[1])
        commands[pid] = parts[2]
        by_parent.setdefault(ppid, []).append(pid)
    found: dict[int, str] = {}
    stack = list(by_parent.get(root_pid, ()))
    while stack:
        pid = stack.pop()
        cmd = _process_command(pid) or commands.get(pid, "")
        if "python" in cmd.lower():
            found[pid] = cmd
        stack.extend(by_parent.get(pid, ()))
    return found


def _process_command(pid: int) -> str:
    proc_cmd = Path(f"/proc/{pid}/cmdline")
    if proc_cmd.exists():
        try:
            return proc_cmd.read_bytes().replace(b"\x00", b" ").decode("utf-8", "replace")
        except OSError:
            return ""
    return ""


def _is_pytest_infrastructure(cmd: str) -> bool:
    return "resource_tracker" in cmd.lower()


@pytest.fixture(scope="session", autouse=True)
def assert_no_leftover_python_descendants():
    parent = os.getpid()
    before = set(_python_descendant_pids(parent))
    yield
    leftover = {
        pid: cmd
        for pid, cmd in _python_descendant_pids(parent).items()
        if pid not in before and not _is_pytest_infrastructure(cmd)
    }
    assert leftover == {}, leftover
