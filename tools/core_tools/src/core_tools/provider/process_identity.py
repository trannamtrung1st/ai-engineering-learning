"""Process-instance identity helpers for safe PID-based termination."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Any

from core_tools.provider.process_cleanup import (
    is_pid_alive,
    list_process_group_pids,
    read_process_group_id,
    terminate_process_tree,
)


class TerminateIdentityResult(Enum):
    """Outcome of attempting to terminate a verified process identity."""

    TERMINATED = "terminated"
    ALREADY_GONE = "already_gone"
    IDENTITY_MISMATCH = "identity_mismatch"
    FAILED = "failed"


@dataclass(frozen=True)
class ProcessIdentity:
    """Stable identity for a live OS process instance."""

    pid: int
    start_time: str
    run_id: str | None = None
    command: str | None = None


def read_process_start_time(pid: int) -> str | None:
    """Return a platform-specific process start-time token for *pid*."""

    if pid <= 0 or not is_pid_alive(pid):
        return None
    if sys.platform == "win32":
        return None
    if os.path.isdir("/proc"):
        return _read_linux_process_start_time(pid)
    return _read_darwin_process_start_time(pid)


def _read_linux_process_start_time(pid: int) -> str | None:
    path = f"/proc/{pid}/stat"
    try:
        with open(path, encoding="utf-8") as handle:
            stat = handle.read()
    except OSError:
        return None
    right_paren = stat.rfind(")")
    if right_paren == -1:
        return None
    fields = stat[right_paren + 2 :].split()
    if len(fields) < 20:
        return None
    return fields[19]


def _read_darwin_process_start_time(pid: int) -> str | None:
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "lstart="],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    start = result.stdout.strip()
    return start or None


def read_process_identity(
    pid: int,
    *,
    run_id: str | None = None,
    command: str | None = None,
) -> ProcessIdentity | None:
    """Capture the current identity for *pid*, or ``None`` when unverifiable."""

    start_time = read_process_start_time(pid)
    if start_time is None:
        return None
    return ProcessIdentity(
        pid=pid,
        start_time=start_time,
        run_id=run_id,
        command=command,
    )


def process_identities_match(
    expected: ProcessIdentity,
    current: ProcessIdentity | None,
) -> bool:
    """Return whether *current* refers to the same process instance as *expected*."""

    if current is None:
        return False
    return expected.pid == current.pid and expected.start_time == current.start_time


def process_identity_token(identity: ProcessIdentity) -> str:
    """Return a stable token for *identity*."""

    return f"{identity.pid}:{identity.start_time}"


def process_identity_from_token(
    token: str,
    *,
    run_id: str | None = None,
) -> ProcessIdentity | None:
    """Parse a ``pid:start_time`` token into a :class:`ProcessIdentity`."""

    if ":" not in token:
        return None
    pid_text, start_time = token.split(":", 1)
    if not start_time:
        return None
    try:
        pid = int(pid_text)
    except ValueError:
        return None
    return ProcessIdentity(pid=pid, start_time=start_time, run_id=run_id)


def process_identity_from_termination_record(
    record: dict[str, object],
) -> ProcessIdentity | None:
    """Reconstruct the original provider identity from a termination record."""

    pid = record.get("pid")
    start_time = record.get("start_time")
    run_id = record.get("run_id")
    run_id_value = run_id if isinstance(run_id, str) else None
    if isinstance(pid, int) and isinstance(start_time, str) and start_time:
        return ProcessIdentity(
            pid=pid,
            start_time=start_time,
            run_id=run_id_value,
        )
    token = record.get("process_identity")
    if isinstance(token, str):
        identity = process_identity_from_token(token, run_id=run_id_value)
        if identity is not None:
            return identity
    return None


def _pidfd_supported() -> bool:
    return (
        sys.platform == "linux"
        and hasattr(os, "pidfd_open")
        and hasattr(signal, "pidfd_send_signal")
    )


def _terminate_bound_process(
    identity: ProcessIdentity | None,
    proc: subprocess.Popen[Any],
) -> TerminateIdentityResult:
    if proc.poll() is not None:
        return TerminateIdentityResult.ALREADY_GONE
    if identity is not None and proc.pid != identity.pid:
        return TerminateIdentityResult.IDENTITY_MISMATCH
    if terminate_process_tree(proc):
        return TerminateIdentityResult.TERMINATED
    return TerminateIdentityResult.FAILED


def _capture_process_group_identities(
    leader: ProcessIdentity,
) -> list[ProcessIdentity] | None:
    """Capture verifiable identities for all members of *leader*'s process group."""

    current = read_process_identity(
        leader.pid,
        run_id=leader.run_id,
        command=leader.command,
    )
    if not process_identities_match(leader, current):
        return None

    pgid = read_process_group_id(leader.pid)
    if pgid is None:
        return [leader]

    pids = list_process_group_pids(pgid)
    if pids is None:
        return None

    identities: list[ProcessIdentity] = []
    for pid in pids:
        identity = read_process_identity(
            pid,
            run_id=leader.run_id,
            command=leader.command,
        )
        if identity is None:
            return None
        identities.append(identity)
    return identities


def _identity_still_alive(identity: ProcessIdentity) -> bool:
    if not is_pid_alive(identity.pid):
        return False
    current = read_process_identity(
        identity.pid,
        run_id=identity.run_id,
        command=identity.command,
    )
    return process_identities_match(identity, current)


def _any_identities_still_alive(identities: list[ProcessIdentity]) -> bool:
    return any(_identity_still_alive(identity) for identity in identities)


def _wait_identities_dead(
    identities: list[ProcessIdentity],
    *,
    timeout: float,
) -> bool:
    deadline = timeout
    interval = 0.05
    while deadline > 0:
        if not _any_identities_still_alive(identities):
            return True
        import time

        time.sleep(min(interval, deadline))
        deadline -= interval
    return not _any_identities_still_alive(identities)


def _signal_identity_via_pidfd(identity: ProcessIdentity, sig: int) -> bool:
    """Send *sig* through pidfd when *identity* still matches."""

    if not _identity_still_alive(identity):
        return True
    try:
        fd = os.pidfd_open(identity.pid, 0)
    except OSError:
        return False
    try:
        if not _identity_still_alive(identity):
            return True
        signal.pidfd_send_signal(fd, sig)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


def _terminate_linux_identity(identity: ProcessIdentity) -> TerminateIdentityResult:
    current = read_process_identity(
        identity.pid,
        run_id=identity.run_id,
        command=identity.command,
    )
    if not process_identities_match(identity, current):
        return TerminateIdentityResult.IDENTITY_MISMATCH

    captured = _capture_process_group_identities(identity)
    if captured is None:
        return TerminateIdentityResult.FAILED

    for member in captured:
        if not _signal_identity_via_pidfd(member, signal.SIGTERM):
            return TerminateIdentityResult.FAILED

    if _wait_identities_dead(captured, timeout=5):
        return TerminateIdentityResult.TERMINATED

    for member in captured:
        if not _signal_identity_via_pidfd(member, signal.SIGKILL):
            return TerminateIdentityResult.FAILED

    if _wait_identities_dead(captured, timeout=5):
        return TerminateIdentityResult.TERMINATED
    return TerminateIdentityResult.FAILED


def terminate_verified_process_identity(
    identity: ProcessIdentity | None,
    *,
    proc: subprocess.Popen[Any] | None = None,
) -> TerminateIdentityResult:
    """Terminate *identity* using a process-instance-safe primitive."""

    if proc is not None:
        return _terminate_bound_process(identity, proc)

    if identity is None:
        return TerminateIdentityResult.FAILED

    if not is_pid_alive(identity.pid):
        return TerminateIdentityResult.ALREADY_GONE

    if _pidfd_supported():
        return _terminate_linux_identity(identity)

    return TerminateIdentityResult.FAILED


__all__ = [
    "ProcessIdentity",
    "TerminateIdentityResult",
    "process_identities_match",
    "process_identity_from_termination_record",
    "process_identity_from_token",
    "process_identity_token",
    "read_process_identity",
    "read_process_start_time",
    "terminate_verified_process_identity",
]
