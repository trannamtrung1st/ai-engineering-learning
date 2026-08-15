"""Process-tree termination helpers for provider subprocess cleanup."""

from __future__ import annotations

import errno
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from core_tools.provider.errors import ProviderUnsupportedPlatformError

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


class PidInspectState(Enum):
    """Whether a PID could be inspected as live, gone, or unverifiable."""

    LIVE = "live"
    GONE = "gone"
    UNVERIFIABLE = "unverifiable"


@dataclass(frozen=True)
class PidInspectResult:
    """Inspection outcome for a single PID."""

    state: PidInspectState
    stat: LinuxProcStat | None = None


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


def _read_linux_proc_stat(pid: int) -> PidInspectResult:
    if pid <= 0:
        return PidInspectResult(PidInspectState.GONE)
    path = os.path.join(_PROC_ROOT, str(pid), "stat")
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except FileNotFoundError:
        return PidInspectResult(PidInspectState.GONE)
    except PermissionError:
        return PidInspectResult(PidInspectState.UNVERIFIABLE)
    except OSError as exc:
        if exc.errno in {errno.ENOENT, errno.ESRCH}:
            return PidInspectResult(PidInspectState.GONE)
        return PidInspectResult(PidInspectState.UNVERIFIABLE)
    parsed = _parse_linux_proc_stat_text(text, pid=pid)
    if parsed is None:
        return PidInspectResult(PidInspectState.UNVERIFIABLE)
    if parsed.state in {"Z", "X"}:
        return PidInspectResult(PidInspectState.GONE, parsed)
    return PidInspectResult(PidInspectState.LIVE, parsed)


def _linux_proc_available() -> bool:
    return sys.platform.startswith("linux") and os.path.isdir(_PROC_ROOT)


def _pid_is_zombie(pid: int, *, timeout: float | None = None) -> bool:
    if sys.platform == "win32":
        return False
    if _linux_proc_available():
        result = _read_linux_proc_stat(pid)
        if result.stat is None:
            return False
        return result.stat.state in {"Z", "X"}
    budget = _DARWIN_PS_TIMEOUT_SECONDS if timeout is None else timeout
    if budget <= 0:
        return False
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "state="],
            capture_output=True,
            text=True,
            check=False,
            timeout=budget,
        )
    except OSError:
        return False
    if result.returncode != 0:
        return False
    state = result.stdout.strip()
    return state.startswith("Z")


def inspect_pid_liveness(
    pid: int,
    *,
    timeout: float | None = None,
) -> PidInspectState:
    """Return whether *pid* is live, gone, or unverifiable."""

    if pid <= 0:
        return PidInspectState.GONE
    if _linux_proc_available():
        return _read_linux_proc_stat(pid).state
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return PidInspectState.GONE
    except PermissionError:
        return PidInspectState.UNVERIFIABLE
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return PidInspectState.GONE
        return PidInspectState.UNVERIFIABLE
    try:
        zombie = _pid_is_zombie(pid, timeout=timeout)
    except subprocess.TimeoutExpired:
        return PidInspectState.UNVERIFIABLE
    if zombie:
        return PidInspectState.GONE
    return PidInspectState.LIVE


def is_pid_alive(pid: int, *, timeout: float | None = None) -> bool:
    return inspect_pid_liveness(pid, timeout=timeout) is not PidInspectState.GONE


def read_process_group_id(pid: int, *, timeout: float | None = None) -> int | None:
    """Return the process group ID for *pid*, or ``None`` when unavailable."""

    if pid <= 0:
        return None
    if sys.platform == "win32":
        return None
    if _linux_proc_available():
        result = _read_linux_proc_stat(pid)
        if result.state is not PidInspectState.LIVE or result.stat is None:
            return None
        return result.stat.pgid
    if not is_pid_alive(pid, timeout=timeout):
        return None
    try:
        return int(os.getpgid(pid))
    except OSError:
        return None


_DARWIN_PS_TIMEOUT_SECONDS = 2.0


def list_process_group_pids(
    pgid: int,
    *,
    timeout: float | None = None,
) -> list[int] | None:
    """Return live PIDs in *pgid*, or ``None`` when membership cannot be verified."""

    if pgid <= 0:
        return []
    if sys.platform == "win32":
        return None
    if sys.platform == "darwin":
        budget = _DARWIN_PS_TIMEOUT_SECONDS if timeout is None else timeout
        return _list_darwin_process_group_pids(pgid, timeout=budget)
    if not _linux_proc_available():
        return None
    members: list[int] = []
    deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
    if deadline is not None and time.monotonic() >= deadline:
        return None
    try:
        entries = os.listdir(_PROC_ROOT)
    except OSError:
        return None
    if deadline is not None and time.monotonic() >= deadline:
        return None
    for entry in entries:
        if deadline is not None and time.monotonic() >= deadline:
            return None
        if not entry.isdigit():
            continue
        result = _read_linux_proc_stat(int(entry))
        if deadline is not None and time.monotonic() >= deadline:
            return None
        if result.state is PidInspectState.UNVERIFIABLE:
            try:
                member_pgid = os.getpgid(int(entry))
            except OSError:
                return None
            if member_pgid == pgid:
                return None
            continue
        if result.state is PidInspectState.GONE or result.stat is None:
            continue
        if result.stat.pgid == pgid:
            members.append(result.stat.pid)
    members.sort()
    return members


def _list_darwin_process_group_pids(
    pgid: int,
    *,
    timeout: float,
) -> list[int] | None:
    if timeout <= 0:
        return None
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,pgid=,state="],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    members: list[int] = []
    for line in result.stdout.splitlines():
        text = line.strip()
        if not text:
            continue
        parts = text.split()
        if len(parts) < 3:
            return None
        try:
            pid = int(parts[0])
            member_pgid = int(parts[1])
        except ValueError:
            return None
        state = parts[2]
        if member_pgid != pgid:
            continue
        if not state or state[0] in {"Z", "X"}:
            continue
        members.append(pid)
    return members


def process_group_state(
    pgid: int,
    *,
    timeout: float | None = None,
) -> ProcessGroupState:
    """Return whether *pgid* still has verifiably live members."""

    members = list_process_group_pids(pgid, timeout=timeout)
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

    end = time.monotonic() + max(0.0, timeout)
    interval = 0.05
    last = ProcessGroupState.UNVERIFIABLE
    while True:
        remaining = end - time.monotonic()
        if remaining <= 0:
            return process_group_state(pgid, timeout=0.0)
        last = process_group_state(pgid, timeout=remaining)
        if last is not ProcessGroupState.LIVE:
            return last
        remaining = end - time.monotonic()
        if remaining <= 0:
            return last
        time.sleep(min(interval, remaining))


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
    timeout: float | None = None,
) -> bool:
    """Terminate a subprocess tree and return True when the group is verified gone."""

    from core_tools.provider.process_identity import (
        _terminate_via_bound_popen,
        capture_process_group_identities,
        drain_owned_process_group,
        read_process_identity,
    )

    wait_s = 5.0 if timeout is None else max(0.0, timeout)
    deadline = None if timeout is None else time.monotonic() + wait_s

    def remaining() -> float | None:
        if deadline is None:
            return None
        return max(0.0, deadline - time.monotonic())

    if sys.platform == "win32":
        raise ProviderUnsupportedPlatformError(
            "process-tree termination is POSIX-only; Windows Cursor process "
            "trees are not supported"
        )

    resolved_pgid = pgid
    if resolved_pgid is None and proc.poll() is None:
        resolved_pgid = read_process_group_id(proc.pid, timeout=remaining())

    identity = leader_identity
    if identity is None and proc.poll() is None:
        identity = read_process_identity(proc.pid, timeout=remaining())

    members = member_identities
    if members is None and identity is not None and proc.poll() is None:
        members = capture_process_group_identities(identity, timeout=remaining())

    status = _terminate_via_bound_popen(proc, pgid=resolved_pgid, timeout=remaining())
    if isinstance(status, dict) and status.get("drain") == "clean":
        return True

    if resolved_pgid is None:
        resolved_pgid = proc.pid

    cleaned = drain_owned_process_group(
        pgid=resolved_pgid,
        leader_identity=identity,
        known_identities=members,
        timeout=remaining(),
    )
    if cleaned:
        from core_tools.provider.session_janitor import complete_bound_secondary_clean

        payload = {
            "agent_code": 0,
            "drain": "clean",
            "stop_requested": True,
        }
        return complete_bound_secondary_clean(proc, payload)
    if proc.poll() is not None and process_group_state(
        proc.pid, timeout=remaining()
    ) is ProcessGroupState.GONE:
        return True
    return False


__all__ = [
    "LinuxProcStat",
    "PidInspectResult",
    "PidInspectState",
    "ProcessGroupState",
    "inspect_pid_liveness",
    "is_pid_alive",
    "list_process_group_pids",
    "pgid_has_live_members",
    "process_group_state",
    "read_process_group_id",
    "terminate_pid_tree",
    "terminate_process_tree",
    "wait_process_group_gone",
]
