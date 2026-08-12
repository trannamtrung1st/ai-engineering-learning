"""Process-instance identity helpers for safe PID-based termination."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum

from core_tools.provider.process_cleanup import is_pid_alive, terminate_pid_tree


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


def terminate_verified_process_identity(
    identity: ProcessIdentity,
) -> TerminateIdentityResult:
    """Terminate *identity* only when the live process still matches it."""

    if not is_pid_alive(identity.pid):
        return TerminateIdentityResult.ALREADY_GONE
    current = read_process_identity(
        identity.pid,
        run_id=identity.run_id,
        command=identity.command,
    )
    if not process_identities_match(identity, current):
        return TerminateIdentityResult.IDENTITY_MISMATCH
    if terminate_pid_tree(identity.pid):
        return TerminateIdentityResult.TERMINATED
    return TerminateIdentityResult.FAILED


__all__ = [
    "ProcessIdentity",
    "TerminateIdentityResult",
    "process_identities_match",
    "read_process_identity",
    "read_process_start_time",
    "terminate_verified_process_identity",
]
