"""Process-instance identity helpers for safe PID-based termination."""

from __future__ import annotations

import errno
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from core_tools.provider.process_cleanup import (
    PidInspectState,
    ProcessGroupState,
    _read_linux_proc_stat,
    inspect_pid_liveness,
    is_pid_alive,
    list_process_group_pids,
    process_group_state,
    read_process_group_id,
    wait_process_group_gone,
)
from core_tools.provider.session_janitor import (
    DrainResult,
    JANITOR_PARENT_WAIT_SECONDS,
    JanitorStatusOwner,
    read_bound_janitor_status,
)


class TerminateIdentityResult(Enum):
    """Outcome of attempting to terminate a verified process identity."""

    TERMINATED = "terminated"
    ALREADY_GONE = "already_gone"
    IDENTITY_MISMATCH = "identity_mismatch"
    FAILED = "failed"


class IdentityInspectState(Enum):
    """Whether a captured identity still matches a live process instance."""

    LIVE_MATCH = "live_match"
    GONE = "gone"
    IDENTITY_MISMATCH = "identity_mismatch"
    UNVERIFIABLE = "unverifiable"


_MAX_DRAIN_ROUNDS = 10


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
    from core_tools.provider.session_janitor import _process_start_token

    return _process_start_token(pid)


def _read_linux_process_start_time(pid: int) -> str | None:
    result = _read_linux_proc_stat(pid)
    if result.stat is None:
        return None
    return result.stat.start_time


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


def process_identities_from_termination_record(
    record: dict[str, object],
) -> list[ProcessIdentity]:
    """Return leader and member identities preserved on a termination record."""

    identities: list[ProcessIdentity] = []
    seen: set[tuple[int, str]] = set()
    leader = process_identity_from_termination_record(record)
    if leader is not None:
        identities.append(leader)
        seen.add(_identity_token(leader))
    run_id = record.get("run_id")
    run_id_value = run_id if isinstance(run_id, str) else None
    raw_members = record.get("member_identities")
    if isinstance(raw_members, list):
        for token in raw_members:
            if not isinstance(token, str):
                continue
            identity = process_identity_from_token(token, run_id=run_id_value)
            if identity is None:
                continue
            token_key = _identity_token(identity)
            if token_key in seen:
                continue
            seen.add(token_key)
            identities.append(identity)
    return identities


def inspect_process_identity(identity: ProcessIdentity) -> IdentityInspectState:
    """Inspect whether *identity* still matches a live process instance."""

    pid_state = inspect_pid_liveness(identity.pid)
    if pid_state is PidInspectState.GONE:
        return IdentityInspectState.GONE
    if pid_state is PidInspectState.UNVERIFIABLE:
        return IdentityInspectState.UNVERIFIABLE
    current = read_process_identity(
        identity.pid,
        run_id=identity.run_id,
        command=identity.command,
    )
    if current is None:
        return IdentityInspectState.UNVERIFIABLE
    if process_identities_match(identity, current):
        return IdentityInspectState.LIVE_MATCH
    return IdentityInspectState.IDENTITY_MISMATCH


def process_identity_is_live(identity: ProcessIdentity) -> bool:
    """Return whether *identity* may still refer to a live process instance.

    Unverifiable inspections are treated as live so callers keep the tree.
    """

    return _identity_still_alive(identity)


def _pidfd_supported() -> bool:
    return (
        sys.platform == "linux"
        and hasattr(os, "pidfd_open")
        and hasattr(signal, "pidfd_send_signal")
    )


def _identity_token(identity: ProcessIdentity) -> tuple[int, str]:
    return (identity.pid, identity.start_time)


def _known_tokens(
    leader_identity: ProcessIdentity | None,
    known_identities: list[ProcessIdentity] | None,
) -> set[tuple[int, str]]:
    tokens: set[tuple[int, str]] = set()
    if leader_identity is not None:
        tokens.add(_identity_token(leader_identity))
    if known_identities:
        for identity in known_identities:
            tokens.add(_identity_token(identity))
    return tokens


def _identity_still_alive(identity: ProcessIdentity) -> bool:
    return inspect_process_identity(identity) in {
        IdentityInspectState.LIVE_MATCH,
        IdentityInspectState.UNVERIFIABLE,
    }


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


def _identity_needs_no_signal(state: IdentityInspectState) -> bool:
    return state in {
        IdentityInspectState.GONE,
        IdentityInspectState.IDENTITY_MISMATCH,
    }


def _signal_identity_via_pidfd(identity: ProcessIdentity, sig: int) -> bool:
    """Send *sig* through pidfd when *identity* still matches."""

    state = inspect_process_identity(identity)
    if _identity_needs_no_signal(state):
        return True
    if state is IdentityInspectState.UNVERIFIABLE:
        return False
    try:
        fd = os.pidfd_open(identity.pid, 0)
    except OSError:
        return False
    try:
        state = inspect_process_identity(identity)
        if _identity_needs_no_signal(state):
            return True
        if state is IdentityInspectState.UNVERIFIABLE:
            return False
        signal.pidfd_send_signal(fd, sig)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


def _signal_identity(identity: ProcessIdentity, sig: int) -> bool:
    state = inspect_process_identity(identity)
    if _identity_needs_no_signal(state):
        return True
    if state is IdentityInspectState.UNVERIFIABLE:
        return False
    if _pidfd_supported():
        return _signal_identity_via_pidfd(identity, sig)
    return False


def _group_still_ours(
    pgid: int,
    leader_identity: ProcessIdentity | None,
    known_tokens: set[tuple[int, str]],
) -> bool:
    if leader_identity is not None and _identity_still_alive(leader_identity):
        if read_process_group_id(leader_identity.pid) == pgid:
            return True
    for pid, start_time in known_tokens:
        anchor = ProcessIdentity(pid=pid, start_time=start_time)
        if _identity_still_alive(anchor):
            if read_process_group_id(anchor.pid) == pgid:
                return True
    return False


def _current_group_identities(
    pgid: int,
    *,
    run_id: str | None = None,
) -> list[ProcessIdentity] | None:
    pids = list_process_group_pids(pgid)
    if pids is None:
        return None
    identities: list[ProcessIdentity] = []
    for pid in pids:
        identity = read_process_identity(pid, run_id=run_id)
        if identity is None:
            return None
        identities.append(identity)
    return identities


def _select_owned_targets(
    current_identities: list[ProcessIdentity],
    known_tokens: set[tuple[int, str]],
    *,
    pgid: int,
    leader_identity: ProcessIdentity | None,
) -> list[ProcessIdentity] | None:
    live_current = [
        identity for identity in current_identities if _identity_still_alive(identity)
    ]
    if not live_current:
        return []

    if not _group_still_ours(pgid, leader_identity, known_tokens):
        return None

    targets: list[ProcessIdentity] = []
    for identity in live_current:
        token = _identity_token(identity)
        if token in known_tokens:
            targets.append(identity)
            continue
        known_tokens.add(token)
        targets.append(identity)
    return targets


def capture_process_group_identities(
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

    return _current_group_identities(pgid, run_id=leader.run_id)


def drain_owned_process_group(
    *,
    pgid: int | None,
    leader_identity: ProcessIdentity | None = None,
    known_identities: list[ProcessIdentity] | None = None,
) -> bool:
    """Terminate an owned process group using identity-safe signaling."""

    resolved_pgid = pgid
    if resolved_pgid is None and leader_identity is not None:
        if _identity_still_alive(leader_identity):
            resolved_pgid = read_process_group_id(leader_identity.pid)

    if resolved_pgid is None or resolved_pgid <= 0:
        if leader_identity is None:
            return False
        for sig in (signal.SIGTERM, signal.SIGKILL):
            if not _signal_identity(leader_identity, sig):
                return False
            if _wait_identities_dead([leader_identity], timeout=5):
                return True
        return not _identity_still_alive(leader_identity)

    known_tokens = _known_tokens(leader_identity, known_identities)
    run_id = leader_identity.run_id if leader_identity is not None else None

    for _round in range(_MAX_DRAIN_ROUNDS):
        state = process_group_state(resolved_pgid)
        if state is ProcessGroupState.UNVERIFIABLE:
            return False
        if state is ProcessGroupState.GONE:
            return True

        current = _current_group_identities(resolved_pgid, run_id=run_id)
        if current is None:
            return False

        targets = _select_owned_targets(
            current,
            known_tokens,
            pgid=resolved_pgid,
            leader_identity=leader_identity,
        )
        if targets is None:
            return False
        if not targets:
            state = process_group_state(resolved_pgid)
            if state is ProcessGroupState.GONE:
                return True
            if state is ProcessGroupState.UNVERIFIABLE:
                return False
            continue

        for identity in targets:
            if not _signal_identity(identity, signal.SIGTERM):
                return False
            try:
                os.waitpid(identity.pid, os.WNOHANG)
            except (ChildProcessError, OSError):
                pass

        if _wait_identities_dead(targets, timeout=5):
            if process_group_state(resolved_pgid) is ProcessGroupState.GONE:
                return True

        if process_group_state(resolved_pgid) is ProcessGroupState.GONE:
            return True

        survivors = [identity for identity in targets if _identity_still_alive(identity)]
        for identity in survivors:
            if not _signal_identity(identity, signal.SIGKILL):
                return False
            try:
                os.waitpid(identity.pid, os.WNOHANG)
            except (ChildProcessError, OSError):
                pass

        if _wait_identities_dead(survivors, timeout=5):
            if process_group_state(resolved_pgid) is ProcessGroupState.GONE:
                return True

    return process_group_state(resolved_pgid) is ProcessGroupState.GONE


def _request_janitor_stop(proc: subprocess.Popen[Any]) -> bool:
    try:
        stdin = proc.stdin
    except AttributeError:
        return False
    if stdin is None:
        return False
    try:
        try:
            stdin.write("STOP\n")
        except TypeError:
            stdin.write(b"STOP\n")
        stdin.flush()
        stdin.close()
    except (OSError, ValueError, BrokenPipeError, AttributeError):
        return False
    return True


def _fallback_status(drain: DrainResult) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "agent_code": -1,
        "drain": drain.value,
        "stop_requested": True,
    }
    if drain is not DrainResult.CLEAN:
        payload["cleanup_error"] = "status_timeout_group_fallback"
    return payload


def _fallback_kill_bound_janitor_group(
    proc: subprocess.Popen[Any],
    *,
    pgid: int | None = None,
    timeout: float = 0.5,
) -> dict[str, Any]:
    """SIGKILL the owned group while the bound leader is still unreaped."""

    deadline = time.monotonic() + max(0.0, timeout)

    def remaining() -> float:
        return max(0.0, deadline - time.monotonic())

    resolved = pgid
    if resolved is None:
        try:
            resolved = os.getpgid(proc.pid)
        except OSError:
            resolved = proc.pid
    if resolved is None or resolved <= 0:
        return _fallback_status(DrainResult.UNVERIFIABLE)
    try:
        os.killpg(int(resolved), signal.SIGKILL)
    except OSError as exc:
        if getattr(exc, "errno", None) != errno.ESRCH:
            return _fallback_status(DrainResult.UNVERIFIABLE)
        members = list_process_group_pids(int(resolved), timeout=remaining())
        if members is None:
            return _fallback_status(DrainResult.UNVERIFIABLE)
        if members:
            return _fallback_status(DrainResult.SURVIVORS)
        if is_pid_alive(proc.pid):
            return _fallback_status(DrainResult.UNVERIFIABLE)
        return _fallback_status(DrainResult.CLEAN)
    wait_process_group_gone(int(resolved), timeout=remaining())
    members = list_process_group_pids(int(resolved), timeout=remaining())
    if members is None:
        return _fallback_status(DrainResult.UNVERIFIABLE)
    if any(pid != proc.pid for pid in members):
        return _fallback_status(DrainResult.SURVIVORS)
    return _fallback_status(DrainResult.CLEAN)


def _terminate_via_bound_popen(
    proc: subprocess.Popen[Any],
    *,
    pgid: int | None = None,
) -> dict[str, Any] | None:
    owner = getattr(proc, "_core_tools_janitor_status_owner", None)
    fd = getattr(proc, "_core_tools_janitor_status_fd", None)
    cached = getattr(proc, "_core_tools_janitor_status", None)
    janitor_bound = (
        isinstance(owner, JanitorStatusOwner)
        or isinstance(fd, int)
        or isinstance(cached, dict)
    )
    if janitor_bound:
        _request_janitor_stop(proc)
        status = read_bound_janitor_status(proc, timeout=JANITOR_PARENT_WAIT_SECONDS)
        if isinstance(status, dict) and status.get("drain") == DrainResult.CLEAN.value:
            if isinstance(owner, JanitorStatusOwner) and not owner.reap_allowed:
                owner.mark_safe_fallback(status)
            try:
                proc.wait(timeout=JANITOR_PARENT_WAIT_SECONDS)
            except (OSError, subprocess.TimeoutExpired):
                return _fallback_status(DrainResult.UNVERIFIABLE)
            return status
        fallback = _fallback_kill_bound_janitor_group(proc, pgid=pgid)
        if isinstance(owner, JanitorStatusOwner):
            owner.mark_safe_fallback(fallback)
        setattr(proc, "_core_tools_janitor_status", fallback)
        if fallback.get("drain") != DrainResult.CLEAN.value:
            return fallback
        try:
            proc.wait(timeout=JANITOR_PARENT_WAIT_SECONDS)
        except (OSError, subprocess.TimeoutExpired):
            failed = _fallback_status(DrainResult.UNVERIFIABLE)
            if isinstance(owner, JanitorStatusOwner):
                owner.mark_safe_fallback(failed)
            setattr(proc, "_core_tools_janitor_status", failed)
            return failed
        return fallback
    if proc.poll() is not None:
        return cached if isinstance(cached, dict) else None
    status = None
    try:
        proc.terminate()
    except OSError:
        return status
    try:
        proc.wait(timeout=JANITOR_PARENT_WAIT_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except OSError:
            return status
        try:
            proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
    return status


def _terminate_bound_process(
    identity: ProcessIdentity | None,
    proc: subprocess.Popen[Any],
    *,
    pgid: int | None = None,
    member_identities: list[ProcessIdentity] | None = None,
) -> TerminateIdentityResult:
    if identity is not None and proc.poll() is None and proc.pid != identity.pid:
        return TerminateIdentityResult.IDENTITY_MISMATCH

    status = _terminate_via_bound_popen(proc, pgid=pgid)
    if isinstance(status, dict) and status.get("drain") == DrainResult.CLEAN.value:
        return TerminateIdentityResult.TERMINATED

    resolved_identity = identity
    if resolved_identity is None and proc.poll() is None:
        resolved_identity = read_process_identity(proc.pid)

    resolved_pgid = pgid
    if resolved_pgid is None and proc.poll() is None:
        resolved_pgid = read_process_group_id(proc.pid)

    members = list(member_identities) if member_identities is not None else None
    if members is None and resolved_identity is not None and proc.poll() is None:
        members = capture_process_group_identities(resolved_identity)

    if drain_owned_process_group(
        pgid=resolved_pgid,
        leader_identity=resolved_identity,
        known_identities=members,
    ):
        return TerminateIdentityResult.TERMINATED
    return TerminateIdentityResult.FAILED


def _terminate_linux_identity(identity: ProcessIdentity) -> TerminateIdentityResult:
    state = inspect_process_identity(identity)
    if state is IdentityInspectState.GONE:
        return TerminateIdentityResult.ALREADY_GONE
    if state is IdentityInspectState.IDENTITY_MISMATCH:
        return TerminateIdentityResult.IDENTITY_MISMATCH
    if state is IdentityInspectState.UNVERIFIABLE:
        return TerminateIdentityResult.FAILED

    captured = capture_process_group_identities(identity)
    if captured is None:
        return TerminateIdentityResult.FAILED

    pgid = read_process_group_id(identity.pid)
    if drain_owned_process_group(
        pgid=pgid,
        leader_identity=identity,
        known_identities=captured,
    ):
        return TerminateIdentityResult.TERMINATED
    return TerminateIdentityResult.FAILED


def terminate_verified_process_identity(
    identity: ProcessIdentity | None,
    *,
    proc: subprocess.Popen[Any] | None = None,
    pgid: int | None = None,
    member_identities: list[ProcessIdentity] | None = None,
) -> TerminateIdentityResult:
    """Terminate *identity* using a process-instance-safe primitive."""

    if proc is not None:
        return _terminate_bound_process(
            identity,
            proc,
            pgid=pgid,
            member_identities=member_identities,
        )

    if identity is None:
        return TerminateIdentityResult.FAILED

    state = inspect_process_identity(identity)
    if state is IdentityInspectState.UNVERIFIABLE:
        return TerminateIdentityResult.FAILED
    if state is IdentityInspectState.IDENTITY_MISMATCH:
        return TerminateIdentityResult.IDENTITY_MISMATCH
    if state is IdentityInspectState.GONE:
        pgid = read_process_group_id(identity.pid) if pgid is None else pgid
        if pgid is not None and member_identities:
            if drain_owned_process_group(
                pgid=pgid,
                leader_identity=identity,
                known_identities=member_identities,
            ):
                return TerminateIdentityResult.TERMINATED
            return TerminateIdentityResult.FAILED
        return TerminateIdentityResult.ALREADY_GONE

    if not _pidfd_supported():
        return TerminateIdentityResult.FAILED

    return _terminate_linux_identity(identity)


__all__ = [
    "IdentityInspectState",
    "ProcessIdentity",
    "TerminateIdentityResult",
    "capture_process_group_identities",
    "drain_owned_process_group",
    "inspect_process_identity",
    "process_identities_from_termination_record",
    "process_identities_match",
    "process_identity_from_termination_record",
    "process_identity_from_token",
    "process_identity_is_live",
    "process_identity_token",
    "read_process_identity",
    "read_process_start_time",
    "terminate_verified_process_identity",
]
