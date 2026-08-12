"""Process-tree termination helpers for provider subprocess cleanup."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from enum import Enum
from typing import Any


class ProcessGroupState(Enum):
    """Whether a process group still has live members."""

    LIVE = "live"
    GONE = "gone"
    UNVERIFIABLE = "unverifiable"


def is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_process_group_id(pid: int) -> int | None:
    """Return the process group ID for *pid*, or ``None`` when unavailable."""

    if pid <= 0 or not is_pid_alive(pid):
        return None
    if sys.platform == "win32":
        return None
    try:
        return int(os.getpgid(pid))
    except OSError:
        return None


def list_process_group_pids(pgid: int) -> list[int] | None:
    """Return live PIDs in *pgid*, or ``None`` when membership cannot be verified."""

    if pgid <= 0:
        return []
    if sys.platform == "win32":
        return None
    if sys.platform == "darwin":
        return _list_darwin_process_group_pids(pgid)
    proc_root = "/proc"
    if not os.path.isdir(proc_root):
        return None
    members: list[int] = []
    for entry in os.listdir(proc_root):
        if not entry.isdigit():
            continue
        pid = int(entry)
        if not is_pid_alive(pid):
            continue
        member_pgid = read_process_group_id(pid)
        if member_pgid == pgid:
            members.append(pid)
    return members


def _list_darwin_process_group_pids(pgid: int) -> list[int] | None:
    try:
        result = subprocess.run(
            ["ps", "-g", str(pgid), "-o", "pid="],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return []
    members: list[int] = []
    for line in result.stdout.splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            pid = int(text)
        except ValueError:
            continue
        if is_pid_alive(pid):
            members.append(pid)
    return members


def process_group_state(pgid: int) -> ProcessGroupState:
    """Return whether *pgid* still has verifiably live members."""

    members = list_process_group_pids(pgid)
    if members is None:
        return ProcessGroupState.UNVERIFIABLE
    if members:
        return ProcessGroupState.LIVE
    return ProcessGroupState.GONE


def pgid_has_live_members(pgid: int) -> bool:
    """Return whether any live process still belongs to *pgid*.

    When membership cannot be verified, returns ``False``. Prefer
    :func:`process_group_state` for fail-closed cleanup decisions.
    """

    return process_group_state(pgid) == ProcessGroupState.LIVE


def wait_process_group_gone(pgid: int, *, timeout: float) -> ProcessGroupState:
    """Wait until *pgid* has no verifiably live members or *timeout* elapses."""

    deadline = timeout
    interval = 0.05
    while deadline > 0:
        state = process_group_state(pgid)
        if state is not ProcessGroupState.LIVE:
            return state
        import time

        time.sleep(min(interval, deadline))
        deadline -= interval
    return process_group_state(pgid)


def _kill_pids(pids: list[int], sig: int) -> None:
    for pid in pids:
        if not is_pid_alive(pid):
            continue
        try:
            os.kill(pid, sig)
        except OSError:
            continue


def terminate_pid_tree(pid: int) -> bool:
    """Terminate a process and any descendants started in its process group.

    Returns True when the PID and its owned group are confirmed dead.
    """

    if not is_pid_alive(pid):
        return True

    if sys.platform == "win32":
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return not is_pid_alive(pid)
        _wait_pid(pid, timeout=5)
        if is_pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                return not is_pid_alive(pid)
            _wait_pid(pid, timeout=5)
        return not is_pid_alive(pid)

    pgid = read_process_group_id(pid)
    if pgid is None:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return not is_pid_alive(pid)
        _wait_pid(pid, timeout=5)
        if is_pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                return not is_pid_alive(pid)
            _wait_pid(pid, timeout=5)
        return not is_pid_alive(pid)

    members_at_start = list_process_group_pids(pgid)
    if members_at_start is None:
        return False

    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return not is_pid_alive(pid)
    except PermissionError:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return not is_pid_alive(pid)

    _wait_pid(pid, timeout=5)

    state = wait_process_group_gone(pgid, timeout=5)
    if state is ProcessGroupState.UNVERIFIABLE:
        return False
    if state is ProcessGroupState.GONE and not is_pid_alive(pid):
        return True

    _kill_pids(members_at_start, signal.SIGKILL)
    _wait_pid(pid, timeout=5)
    state = wait_process_group_gone(pgid, timeout=5)
    return state is ProcessGroupState.GONE and not is_pid_alive(pid)


def _wait_pid(pid: int, *, timeout: float) -> bool:
    deadline = timeout
    interval = 0.05
    while deadline > 0 and is_pid_alive(pid):
        try:
            waited_pid, _status = os.waitpid(pid, os.WNOHANG)
            if waited_pid == pid:
                return True
        except ChildProcessError:
            return not is_pid_alive(pid)
        except OSError:
            break
        import time

        time.sleep(min(interval, deadline))
        deadline -= interval
    return not is_pid_alive(pid)


def terminate_process_tree(proc: subprocess.Popen[Any]) -> bool:
    """Terminate a subprocess tree and return True when the group is verified gone."""

    if proc.poll() is not None:
        return True

    if sys.platform == "win32":
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        return proc.poll() is not None

    pid = proc.pid
    pgid = read_process_group_id(pid)
    if pgid is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        return proc.poll() is not None and not is_pid_alive(pid)

    members_at_start = list_process_group_pids(pgid)
    if members_at_start is None:
        return False

    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        try:
            proc.terminate()
        except ProcessLookupError:
            return not is_pid_alive(pid)
    except PermissionError:
        proc.terminate()

    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass

    state = wait_process_group_gone(pgid, timeout=5)
    if state is ProcessGroupState.UNVERIFIABLE:
        return False
    if state is ProcessGroupState.GONE and (proc.poll() is not None or not is_pid_alive(pid)):
        return True

    _kill_pids(members_at_start, signal.SIGKILL)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass

    state = wait_process_group_gone(pgid, timeout=5)
    if state is not ProcessGroupState.GONE:
        return False
    return proc.poll() is not None or not is_pid_alive(pid)


__all__ = [
    "ProcessGroupState",
    "is_pid_alive",
    "list_process_group_pids",
    "pgid_has_live_members",
    "process_group_state",
    "read_process_group_id",
    "terminate_pid_tree",
    "terminate_process_tree",
    "wait_process_group_gone",
]
