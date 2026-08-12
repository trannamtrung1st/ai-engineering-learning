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
    terminate_pid_tree,
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


def _pidfd_supported() -> bool:
    return (
        sys.platform == "linux"
        and hasattr(os, "pidfd_open")
        and hasattr(os, "pidfd_send_signal")
    )


def _terminate_bound_process(
    identity: ProcessIdentity,
    proc: subprocess.Popen[Any],
) -> TerminateIdentityResult:
    if proc.poll() is not None:
        return TerminateIdentityResult.ALREADY_GONE
    if proc.pid != identity.pid:
        return TerminateIdentityResult.IDENTITY_MISMATCH
    if terminate_process_tree(proc):
        return TerminateIdentityResult.TERMINATED
    return TerminateIdentityResult.FAILED


def _wait_identity_dead(identity: ProcessIdentity, *, timeout: float) -> bool:
    deadline = timeout
    interval = 0.05
    while deadline > 0 and is_pid_alive(identity.pid):
        current = read_process_identity(
            identity.pid,
            run_id=identity.run_id,
            command=identity.command,
        )
        if not process_identities_match(identity, current):
            return True
        try:
            waited_pid, _status = os.waitpid(identity.pid, os.WNOHANG)
            if waited_pid == identity.pid:
                return True
        except ChildProcessError:
            return not is_pid_alive(identity.pid)
        except OSError:
            break
        import time

        time.sleep(min(interval, deadline))
        deadline -= interval
    return not is_pid_alive(identity.pid)


def _terminate_linux_pidfd(identity: ProcessIdentity) -> TerminateIdentityResult:
    try:
        fd = os.pidfd_open(identity.pid, 0)
    except OSError:
        return TerminateIdentityResult.FAILED
    try:
        current = read_process_identity(
            identity.pid,
            run_id=identity.run_id,
            command=identity.command,
        )
        if not process_identities_match(identity, current):
            return TerminateIdentityResult.IDENTITY_MISMATCH
        try:
            os.pidfd_send_signal(fd, signal.SIGTERM)
        except OSError:
            return TerminateIdentityResult.FAILED
        if _wait_identity_dead(identity, timeout=5):
            return TerminateIdentityResult.TERMINATED
        try:
            os.pidfd_send_signal(fd, signal.SIGKILL)
        except OSError:
            pass
        if not is_pid_alive(identity.pid):
            return TerminateIdentityResult.TERMINATED
        return TerminateIdentityResult.FAILED
    finally:
        os.close(fd)


def terminate_verified_process_identity(
    identity: ProcessIdentity,
    *,
    proc: subprocess.Popen[Any] | None = None,
) -> TerminateIdentityResult:
    """Terminate *identity* using a process-instance-safe primitive."""

    if proc is not None:
        return _terminate_bound_process(identity, proc)

    if not is_pid_alive(identity.pid):
        return TerminateIdentityResult.ALREADY_GONE

    if _pidfd_supported():
        return _terminate_linux_pidfd(identity)

    return TerminateIdentityResult.FAILED


__all__ = [
    "ProcessIdentity",
    "TerminateIdentityResult",
    "process_identities_match",
    "process_identity_token",
    "read_process_identity",
    "read_process_start_time",
    "terminate_verified_process_identity",
]
