"""Process-tree termination helpers for provider subprocess cleanup."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core_tools.provider.process_identity import ProcessIdentity


_PROC_ROOT = "/proc"


@dataclass(frozen=True)
class LinuxProcStat:
    """Parsed fields from ``/proc/<pid>/stat``."""

    pid: int
    state: str
    pgid: int
    start_time: str


class ProcessGroupState(Enum):
    """Whether a process group still has live members."""

    LIVE = "live"
    GONE = "gone"
    UNVERIFIABLE = "unverifiable"


def _parse_linux_proc_stat_text(text: str, *, pid: int) -> LinuxProcStat | None:
    right_paren = text.rfind(")")
    if right_paren == -1:
        return None
    fields = text[right_paren + 2 :].split()
    if len(fields) < 20:
        return None
    state = fields[0]
    if not state:
        return None
    try:
        pgid = int(fields[2])
    except ValueError:
        return None
    return LinuxProcStat(
        pid=pid,
        state=state[0],
        pgid=pgid,
        start_time=fields[19],
    )


def _read_linux_proc_stat(pid: int) -> LinuxProcStat | None:
    if pid <= 0:
        return None
    path = os.path.join(_PROC_ROOT, str(pid), "stat")
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return None
    return _parse_linux_proc_stat_text(text, pid=pid)


def _linux_proc_available() -> bool:
    return sys.platform.startswith("linux") and os.path.isdir(_PROC_ROOT)


def _pid_is_zombie(pid: int) -> bool:
    if sys.platform == "win32":
        return False
    if _linux_proc_available():
        parsed = _read_linux_proc_stat(pid)
        if parsed is None:
            return False
        return parsed.state in {"Z", "X"}
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "state="],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    if result.returncode != 0:
        return False
    state = result.stdout.strip()
    return state.startswith("Z")


def is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if _linux_proc_available():
        parsed = _read_linux_proc_stat(pid)
        if parsed is None:
            return False
        return parsed.state not in {"Z", "X"}
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    if _pid_is_zombie(pid):
        return False
    return True


def read_process_group_id(pid: int) -> int | None:
    """Return the process group ID for *pid*, or ``None`` when unavailable."""

    if pid <= 0:
        return None
    if sys.platform == "win32":
        return None
    if _linux_proc_available():
        parsed = _read_linux_proc_stat(pid)
        if parsed is None or parsed.state in {"Z", "X"}:
            return None
        return parsed.pgid
    if not is_pid_alive(pid):
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
    if not _linux_proc_available():
        return None
    members: list[int] = []
    try:
        entries = os.listdir(_PROC_ROOT)
    except OSError:
        return None
    for entry in entries:
        if not entry.isdigit():
            continue
        parsed = _read_linux_proc_stat(int(entry))
        if parsed is None or parsed.state in {"Z", "X"}:
            continue
        if parsed.pgid == pgid:
            members.append(parsed.pid)
    members.sort()
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


def terminate_pid_tree(
    pid: int,
    *,
    pgid: int | None = None,
    leader_identity: ProcessIdentity | None = None,
    member_identities: list[ProcessIdentity] | None = None,
) -> bool:
    """Terminate a process tree using identity-safe group draining."""

    from core_tools.provider.process_identity import (
        capture_process_group_identities,
        drain_owned_process_group,
        read_process_identity,
    )

    if sys.platform == "win32":
        if not is_pid_alive(pid):
            return True
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

    identity = leader_identity
    if identity is None and is_pid_alive(pid):
        identity = read_process_identity(pid)

    resolved_pgid = pgid
    if resolved_pgid is None and is_pid_alive(pid):
        resolved_pgid = read_process_group_id(pid)

    members = member_identities
    if members is None and identity is not None and is_pid_alive(pid):
        captured = capture_process_group_identities(identity)
        members = captured

    return drain_owned_process_group(
        pgid=resolved_pgid,
        leader_identity=identity,
        known_identities=members,
    )


def terminate_process_tree(
    proc: subprocess.Popen[Any],
    *,
    pgid: int | None = None,
    leader_identity: ProcessIdentity | None = None,
    member_identities: list[ProcessIdentity] | None = None,
) -> bool:
    """Terminate a subprocess tree and return True when the group is verified gone."""

    from core_tools.provider.process_identity import (
        _terminate_via_bound_popen,
        capture_process_group_identities,
        drain_owned_process_group,
        read_process_identity,
    )

    if sys.platform == "win32":
        if proc.poll() is not None:
            return True
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        return proc.poll() is not None

    resolved_pgid = pgid
    if resolved_pgid is None and proc.poll() is None:
        resolved_pgid = read_process_group_id(proc.pid)

    identity = leader_identity
    if identity is None and proc.poll() is None:
        identity = read_process_identity(proc.pid)

    members = member_identities
    if members is None and identity is not None and proc.poll() is None:
        members = capture_process_group_identities(identity)

    _terminate_via_bound_popen(proc)

    cleaned = drain_owned_process_group(
        pgid=resolved_pgid,
        leader_identity=identity,
        known_identities=members,
    )
    if proc.poll() is None:
        try:
            proc.wait(timeout=0)
        except subprocess.TimeoutExpired:
            pass
    return cleaned


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
