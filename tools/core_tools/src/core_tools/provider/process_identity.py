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
    ZOMBIE = "zombie"


class GroupLineageState(Enum):
    """Whether current PGID members still belong to the tracked run."""

    OWNED = "owned"
    FOREIGN = "foreign"
    UNRESOLVED = "unresolved"
    GONE = "gone"


_RUN_ID_ENV_VAR = "TDP_RUN_ID"


_MAX_DRAIN_ROUNDS = 10
_DEFAULT_WAIT_SECONDS = 5.0


def _deadline_from_timeout(timeout: float | None) -> float | None:
    if timeout is None:
        return None
    return time.monotonic() + max(0.0, timeout)


def _remaining_seconds(deadline: float | None, *, default: float = _DEFAULT_WAIT_SECONDS) -> float:
    if deadline is None:
        return default
    return max(0.0, deadline - time.monotonic())


def _remaining_fn(timeout: float | None):
    deadline = _deadline_from_timeout(timeout)

    def remaining() -> float | None:
        if deadline is None:
            return None
        return _remaining_seconds(deadline, default=0.0)

    return remaining


PROVIDER_OWNER_ENV_VAR = "TDP_PROVIDER_OWNER_ID"


@dataclass(frozen=True)
class ProcessIdentity:
    """Stable identity for a live OS process instance."""

    pid: int
    start_time: str
    run_id: str | None = None
    command: str | None = None
    owner_id: str | None = None


def read_process_start_time(pid: int, *, timeout: float | None = None) -> str | None:
    """Return a platform-specific process start-time token for *pid*."""

    from core_tools.provider.session_janitor import CleanupDeadline, _process_start_token

    deadline = None if timeout is None else CleanupDeadline.after(timeout)
    remaining = None if deadline is None else deadline.remaining()
    if pid <= 0 or not is_pid_alive(pid, timeout=remaining):
        return None
    if sys.platform == "win32":
        return None
    if os.path.isdir("/proc"):
        return _read_linux_process_start_time(pid)
    return _process_start_token(pid, deadline=deadline)


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
    timeout: float | None = None,
) -> ProcessIdentity | None:
    """Capture the current identity for *pid*, or ``None`` when unverifiable."""

    start_time = read_process_start_time(pid, timeout=timeout)
    if start_time is None:
        return None
    return ProcessIdentity(
        pid=pid,
        start_time=start_time,
        run_id=run_id,
        command=command,
        owner_id=None,
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
    owner = record.get("provider_owner_id")
    owner_value = owner if isinstance(owner, str) else None
    if isinstance(pid, int) and isinstance(start_time, str) and start_time:
        return ProcessIdentity(
            pid=pid,
            start_time=start_time,
            run_id=run_id_value,
            owner_id=owner_value,
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


def inspect_process_identity(
    identity: ProcessIdentity,
    *,
    timeout: float | None = None,
) -> IdentityInspectState:
    """Inspect whether *identity* still matches a live process instance."""

    remaining = _remaining_fn(timeout)
    pid_state = inspect_pid_liveness(identity.pid, timeout=remaining())
    if pid_state is PidInspectState.GONE:
        return IdentityInspectState.GONE
    if pid_state is PidInspectState.ZOMBIE:
        return IdentityInspectState.ZOMBIE
    if pid_state is PidInspectState.UNVERIFIABLE:
        return IdentityInspectState.UNVERIFIABLE
    current = read_process_identity(
        identity.pid,
        run_id=identity.run_id,
        command=identity.command,
        timeout=remaining(),
    )
    if current is None:
        return IdentityInspectState.UNVERIFIABLE
    if process_identities_match(identity, current):
        return IdentityInspectState.LIVE_MATCH
    return IdentityInspectState.IDENTITY_MISMATCH


def process_identity_is_live(
    identity: ProcessIdentity,
    *,
    timeout: float | None = None,
) -> bool:
    """Return whether *identity* may still refer to a live process instance.

    Unverifiable inspections are treated as live so callers keep the tree.
    """

    return _identity_still_alive(identity, timeout=timeout)


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


def _identity_still_alive(
    identity: ProcessIdentity,
    *,
    timeout: float | None = None,
) -> bool:
    return inspect_process_identity(identity, timeout=timeout) in {
        IdentityInspectState.LIVE_MATCH,
        IdentityInspectState.UNVERIFIABLE,
    }


def _any_identities_still_alive(
    identities: list[ProcessIdentity],
    *,
    timeout: float | None = None,
) -> bool:
    remaining = _remaining_fn(timeout)
    return any(
        _identity_still_alive(identity, timeout=remaining()) for identity in identities
    )


def _identity_still_present(
    identity: ProcessIdentity,
    *,
    timeout: float | None = None,
) -> bool:
    return inspect_process_identity(identity, timeout=timeout) in {
        IdentityInspectState.LIVE_MATCH,
        IdentityInspectState.UNVERIFIABLE,
        IdentityInspectState.ZOMBIE,
    }


def _reap_identity(identity: ProcessIdentity) -> None:
    from core_tools.provider.process_cleanup import reap_owned_pid

    reap_owned_pid(identity.pid, timeout=0.0)


def _wait_identities_dead(
    identities: list[ProcessIdentity],
    *,
    timeout: float,
) -> bool:
    deadline = time.monotonic() + max(0.0, timeout)

    def remaining() -> float:
        return max(0.0, deadline - time.monotonic())

    if remaining() <= 0:
        for identity in identities:
            _reap_identity(identity)
        return not any(
            _identity_still_present(identity, timeout=0.0) for identity in identities
        )
    interval = 0.05
    while remaining() > 0:
        for identity in identities:
            _reap_identity(identity)
        if not any(
            _identity_still_present(identity, timeout=remaining())
            for identity in identities
        ):
            return True
        time.sleep(min(interval, remaining()))
    for identity in identities:
        _reap_identity(identity)
    return not any(
        _identity_still_present(identity, timeout=0.0) for identity in identities
    )


def _identity_needs_no_signal(state: IdentityInspectState) -> bool:
    return state in {
        IdentityInspectState.GONE,
        IdentityInspectState.IDENTITY_MISMATCH,
        IdentityInspectState.ZOMBIE,
    }


def _signal_identity_via_pidfd(
    identity: ProcessIdentity,
    sig: int,
    *,
    timeout: float | None = None,
) -> bool:
    """Send *sig* through pidfd when *identity* still matches."""

    remaining = _remaining_fn(timeout)
    state = inspect_process_identity(identity, timeout=remaining())
    if _identity_needs_no_signal(state):
        return True
    if state is IdentityInspectState.UNVERIFIABLE:
        return False
    try:
        fd = os.pidfd_open(identity.pid, 0)
    except OSError:
        return False
    try:
        state = inspect_process_identity(identity, timeout=remaining())
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


def _signal_identity(
    identity: ProcessIdentity,
    sig: int,
    *,
    timeout: float | None = None,
) -> bool:
    remaining = _remaining_fn(timeout)
    state = inspect_process_identity(identity, timeout=remaining())
    if _identity_needs_no_signal(state):
        return True
    if state is IdentityInspectState.UNVERIFIABLE:
        return False
    if _pidfd_supported():
        return _signal_identity_via_pidfd(identity, sig, timeout=remaining())
    return False


def _group_still_ours(
    pgid: int,
    leader_identity: ProcessIdentity | None,
    known_tokens: set[tuple[int, str]],
    *,
    timeout: float | None = None,
) -> bool:
    remaining = _remaining_fn(timeout)
    if leader_identity is not None and _identity_still_alive(
        leader_identity, timeout=remaining()
    ):
        if read_process_group_id(leader_identity.pid, timeout=remaining()) == pgid:
            return True
    for pid, start_time in known_tokens:
        anchor = ProcessIdentity(pid=pid, start_time=start_time)
        if _identity_still_alive(anchor, timeout=remaining()):
            if read_process_group_id(anchor.pid, timeout=remaining()) == pgid:
                return True
    return False


def _tdp_env_from_linux(pid: int) -> dict[str, str]:
    environ_path = f"/proc/{pid}/environ"
    try:
        with open(environ_path, "rb") as handle:
            payload = handle.read()
    except OSError:
        return {}
    env: dict[str, str] = {}
    for part in payload.split(b"\0"):
        if b"=" not in part:
            continue
        key, value = part.split(b"=", 1)
        try:
            decoded_key = key.decode("ascii")
        except UnicodeDecodeError:
            continue
        if not decoded_key.startswith("TDP_"):
            continue
        env[decoded_key] = value.decode("utf-8", "replace")
    return env


def _tdp_env_from_ps(pid: int, *, timeout: float | None = None) -> dict[str, str]:
    budget = 0.2 if timeout is None else max(0.0, timeout)
    if budget <= 0:
        return {}
    try:
        result = subprocess.run(
            ["ps", "eww", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
            timeout=budget,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if result.returncode != 0:
        return {}
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return {}
    env: dict[str, str] = {}
    for token in lines[-1].split():
        if "=" not in token:
            continue
        key, _, value = token.partition("=")
        if key.startswith("TDP_"):
            env[key] = value
    return env


def _tdp_env_for_pid(pid: int, *, timeout: float | None = None) -> dict[str, str]:
    if pid <= 0:
        return {}
    if timeout is not None and timeout <= 0:
        return {}
    if os.path.isdir("/proc"):
        return _tdp_env_from_linux(pid)
    return _tdp_env_from_ps(pid, timeout=timeout)


def read_process_run_id(pid: int, *, timeout: float | None = None) -> str | None:
    """Return ``TDP_RUN_ID`` from *pid*'s environment, or ``None`` if unknown."""

    value = _tdp_env_for_pid(pid, timeout=timeout).get(_RUN_ID_ENV_VAR)
    return value or None


def read_process_owner_id(pid: int, *, timeout: float | None = None) -> str | None:
    """Return ``TDP_PROVIDER_OWNER_ID`` from *pid*'s environment, if present."""

    value = _tdp_env_for_pid(pid, timeout=timeout).get(PROVIDER_OWNER_ENV_VAR)
    return value or None


def current_process_group_lineage(
    pgid: int,
    *,
    expected_run_id: str | None,
    expected_owner_id: str | None = None,
    timeout: float | None = None,
) -> GroupLineageState:
    """Classify current PGID members against owner/run lineage tokens."""

    remaining = _remaining_fn(timeout)
    leftover = remaining()
    if leftover is not None and leftover <= 0:
        return GroupLineageState.UNRESOLVED
    group_state = process_group_state(pgid, timeout=leftover)
    if group_state is ProcessGroupState.GONE:
        return GroupLineageState.GONE
    if group_state is ProcessGroupState.UNVERIFIABLE:
        return GroupLineageState.UNRESOLVED
    leftover = remaining()
    current = _current_group_identities(pgid, run_id=None, timeout=leftover)
    if current is None or not current:
        return GroupLineageState.UNRESOLVED
    owners: list[str | None] = []
    run_ids: list[str | None] = []
    for identity in current:
        leftover = remaining()
        if leftover is not None and leftover <= 0:
            return GroupLineageState.UNRESOLVED
        owner = identity.owner_id
        run_id = identity.run_id
        if owner is None or run_id is None:
            env = _tdp_env_for_pid(identity.pid, timeout=leftover)
            if owner is None:
                owner = env.get(PROVIDER_OWNER_ENV_VAR) or None
            if run_id is None:
                run_id = env.get(_RUN_ID_ENV_VAR) or None
        owners.append(owner)
        run_ids.append(run_id)
    if expected_owner_id:
        if any(owner == expected_owner_id for owner in owners):
            return GroupLineageState.OWNED
        if all(owner is not None and owner != expected_owner_id for owner in owners):
            return GroupLineageState.FOREIGN
        return GroupLineageState.UNRESOLVED
    if not expected_run_id:
        return GroupLineageState.UNRESOLVED
    if any(run_id == expected_run_id for run_id in run_ids):
        return GroupLineageState.OWNED
    if all(run_id is not None and run_id != expected_run_id for run_id in run_ids):
        return GroupLineageState.FOREIGN
    return GroupLineageState.UNRESOLVED


def _current_group_identities(
    pgid: int,
    *,
    run_id: str | None = None,
    timeout: float | None = None,
) -> list[ProcessIdentity] | None:
    deadline = _deadline_from_timeout(timeout)

    def remaining() -> float | None:
        if deadline is None:
            return None
        return _remaining_seconds(deadline, default=0.0)

    pids = list_process_group_pids(pgid, timeout=remaining())
    if pids is None:
        return None
    identities: list[ProcessIdentity] = []
    from core_tools.provider.process_cleanup import (
        PidInspectState,
        inspect_pid_liveness,
    )

    for pid in pids:
        identity = read_process_identity(pid, run_id=run_id, timeout=remaining())
        if identity is None:
            state = inspect_pid_liveness(pid, timeout=remaining())
            if state in {PidInspectState.ZOMBIE, PidInspectState.GONE}:
                continue
            return None
        identities.append(identity)
    return identities


def _select_owned_targets(
    current_identities: list[ProcessIdentity],
    known_tokens: set[tuple[int, str]],
    *,
    pgid: int,
    leader_identity: ProcessIdentity | None,
    timeout: float | None = None,
) -> list[ProcessIdentity] | None:
    remaining = _remaining_fn(timeout)
    live_current = [
        identity
        for identity in current_identities
        if _identity_still_alive(identity, timeout=remaining())
    ]
    zombie_current = [
        identity
        for identity in current_identities
        if inspect_process_identity(identity, timeout=remaining())
        is IdentityInspectState.ZOMBIE
    ]
    if not live_current:
        return list(zombie_current)

    if not _group_still_ours(pgid, leader_identity, known_tokens, timeout=remaining()):
        return None

    targets: list[ProcessIdentity] = []
    for identity in live_current:
        token = _identity_token(identity)
        if token in known_tokens:
            targets.append(identity)
            continue
        known_tokens.add(token)
        targets.append(identity)
    targets.extend(zombie_current)
    return targets


def capture_process_group_identities(
    leader: ProcessIdentity,
    *,
    timeout: float | None = None,
) -> list[ProcessIdentity] | None:
    """Capture verifiable identities for all members of *leader*'s process group."""

    deadline = _deadline_from_timeout(timeout)

    def remaining() -> float | None:
        if deadline is None:
            return None
        return _remaining_seconds(deadline, default=0.0)

    current = read_process_identity(
        leader.pid,
        run_id=leader.run_id,
        command=leader.command,
        timeout=remaining(),
    )
    if not process_identities_match(leader, current):
        return None

    pgid = read_process_group_id(leader.pid, timeout=remaining())
    if pgid is None:
        return [leader]

    return _current_group_identities(pgid, run_id=leader.run_id, timeout=remaining())


def drain_owned_process_group(
    *,
    pgid: int | None,
    leader_identity: ProcessIdentity | None = None,
    known_identities: list[ProcessIdentity] | None = None,
    timeout: float | None = None,
) -> bool:
    """Terminate an owned process group using identity-safe signaling."""

    deadline = _deadline_from_timeout(timeout)

    def wait_budget() -> float:
        return _remaining_seconds(deadline)

    resolved_pgid = pgid
    if resolved_pgid is None and leader_identity is not None:
        if _identity_still_alive(leader_identity, timeout=wait_budget()):
            resolved_pgid = read_process_group_id(
                leader_identity.pid, timeout=wait_budget()
            )

    if resolved_pgid is None or resolved_pgid <= 0:
        if leader_identity is None:
            return False
        for sig in (signal.SIGTERM, signal.SIGKILL):
            if wait_budget() <= 0:
                return not _identity_still_alive(leader_identity, timeout=wait_budget())
            if not _signal_identity(leader_identity, sig, timeout=wait_budget()):
                return False
            if _wait_identities_dead([leader_identity], timeout=wait_budget()):
                return True
        return not _identity_still_alive(leader_identity, timeout=wait_budget())

    known_tokens = _known_tokens(leader_identity, known_identities)
    run_id = leader_identity.run_id if leader_identity is not None else None
    known_list: list[ProcessIdentity] = []
    if leader_identity is not None:
        known_list.append(leader_identity)
    if known_identities:
        known_list.extend(known_identities)

    for _round in range(_MAX_DRAIN_ROUNDS):
        if wait_budget() <= 0:
            return process_group_state(resolved_pgid, timeout=0.0) is ProcessGroupState.GONE
        for identity in known_list:
            _reap_identity(identity)
        state = process_group_state(resolved_pgid, timeout=wait_budget())
        if state is ProcessGroupState.UNVERIFIABLE:
            return False
        if state is ProcessGroupState.GONE:
            return True

        current = _current_group_identities(
            resolved_pgid, run_id=run_id, timeout=wait_budget()
        )
        if current is None:
            return False

        targets = _select_owned_targets(
            current,
            known_tokens,
            pgid=resolved_pgid,
            leader_identity=leader_identity,
            timeout=wait_budget(),
        )
        if targets is None:
            return False
        if not targets:
            for identity in current:
                _reap_identity(identity)
            state = process_group_state(resolved_pgid, timeout=wait_budget())
            if state is ProcessGroupState.GONE:
                return True
            if state is ProcessGroupState.UNVERIFIABLE:
                return False
            continue

        for identity in targets:
            if not _signal_identity(identity, signal.SIGTERM, timeout=wait_budget()):
                return False
            try:
                os.waitpid(identity.pid, os.WNOHANG)
            except (ChildProcessError, OSError):
                pass

        if _wait_identities_dead(targets, timeout=wait_budget()):
            if process_group_state(resolved_pgid, timeout=wait_budget()) is ProcessGroupState.GONE:
                return True

        if process_group_state(resolved_pgid, timeout=wait_budget()) is ProcessGroupState.GONE:
            return True

        if wait_budget() <= 0:
            return process_group_state(resolved_pgid, timeout=wait_budget()) is ProcessGroupState.GONE

        survivors = [
            identity
            for identity in targets
            if _identity_still_alive(identity, timeout=wait_budget())
        ]
        for identity in survivors:
            if not _signal_identity(identity, signal.SIGKILL, timeout=wait_budget()):
                return False
            try:
                os.waitpid(identity.pid, os.WNOHANG)
            except (ChildProcessError, OSError):
                pass

        if _wait_identities_dead(survivors, timeout=wait_budget()):
            if process_group_state(resolved_pgid, timeout=wait_budget()) is ProcessGroupState.GONE:
                return True

    return process_group_state(resolved_pgid, timeout=wait_budget()) is ProcessGroupState.GONE


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


def _fallback_clean_if_output_handed_off(*, output_handed_off: bool) -> dict[str, Any]:
    if output_handed_off:
        return _fallback_status(DrainResult.CLEAN)
    return _fallback_status(DrainResult.UNVERIFIABLE)


def _fallback_kill_bound_janitor_group(
    proc: subprocess.Popen[Any],
    *,
    pgid: int | None = None,
    timeout: float = 0.5,
    output_handed_off: bool = False,
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
            return _fallback_status(DrainResult.UNVERIFIABLE)
    if resolved is None or resolved <= 0:
        return _fallback_status(DrainResult.UNVERIFIABLE)
    raw_poll = getattr(proc, "_core_tools_raw_poll", proc.poll)
    try:
        leader_exited = raw_poll() is not None if callable(raw_poll) else True
    except Exception:
        leader_exited = True
    if leader_exited:
        members = list_process_group_pids(int(resolved), timeout=remaining())
        if members is None:
            return _fallback_status(DrainResult.UNVERIFIABLE)
        if any(pid != proc.pid for pid in members):
            return _fallback_status(DrainResult.UNVERIFIABLE)
        if is_pid_alive(proc.pid, timeout=remaining()):
            return _fallback_status(DrainResult.UNVERIFIABLE)
        return _fallback_clean_if_output_handed_off(
            output_handed_off=output_handed_off
        )
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
        if is_pid_alive(proc.pid, timeout=remaining()):
            return _fallback_status(DrainResult.UNVERIFIABLE)
        return _fallback_clean_if_output_handed_off(
            output_handed_off=output_handed_off
        )
    wait_process_group_gone(int(resolved), timeout=remaining())
    members = list_process_group_pids(int(resolved), timeout=remaining())
    if members is None:
        return _fallback_status(DrainResult.UNVERIFIABLE)
    if any(pid != proc.pid for pid in members):
        return _fallback_status(DrainResult.SURVIVORS)
    return _fallback_clean_if_output_handed_off(output_handed_off=output_handed_off)


def _terminate_via_bound_popen(
    proc: subprocess.Popen[Any],
    *,
    pgid: int | None = None,
    timeout: float | None = None,
) -> dict[str, Any] | None:
    deadline = _deadline_from_timeout(
        JANITOR_PARENT_WAIT_SECONDS if timeout is None else timeout
    )

    def wait_budget() -> float:
        return _remaining_seconds(deadline, default=JANITOR_PARENT_WAIT_SECONDS)

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
        status = read_bound_janitor_status(proc, timeout=wait_budget())
        if isinstance(status, dict) and status.get("drain") == DrainResult.CLEAN.value:
            if isinstance(owner, JanitorStatusOwner) and not owner.reap_allowed:
                owner.mark_safe_fallback(status)
            try:
                proc.wait(timeout=wait_budget())
            except (OSError, subprocess.TimeoutExpired):
                return _fallback_status(DrainResult.UNVERIFIABLE)
            return status
        fallback = _fallback_kill_bound_janitor_group(
            proc, pgid=pgid, timeout=wait_budget()
        )
        if isinstance(owner, JanitorStatusOwner):
            owner.mark_safe_fallback(fallback)
        setattr(proc, "_core_tools_janitor_status", fallback)
        if fallback.get("drain") != DrainResult.CLEAN.value:
            return fallback
        try:
            proc.wait(timeout=wait_budget())
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
        proc.wait(timeout=wait_budget())
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except OSError:
            return status
        try:
            proc.wait(timeout=wait_budget())
        except (OSError, subprocess.TimeoutExpired):
            pass
    return status


def _terminate_bound_process(
    identity: ProcessIdentity | None,
    proc: subprocess.Popen[Any],
    *,
    pgid: int | None = None,
    member_identities: list[ProcessIdentity] | None = None,
    timeout: float | None = None,
) -> TerminateIdentityResult:
    if identity is not None and proc.poll() is None and proc.pid != identity.pid:
        return TerminateIdentityResult.IDENTITY_MISMATCH

    deadline = _deadline_from_timeout(timeout)
    popen_budget = None if deadline is None else _remaining_seconds(deadline, default=0.0)
    status = _terminate_via_bound_popen(proc, pgid=pgid, timeout=popen_budget)
    if isinstance(status, dict) and status.get("drain") == DrainResult.CLEAN.value:
        return TerminateIdentityResult.TERMINATED

    resolved_identity = identity
    if resolved_identity is None and proc.poll() is None:
        resolved_identity = read_process_identity(
            proc.pid,
            timeout=None if deadline is None else _remaining_seconds(deadline, default=0.0),
        )

    resolved_pgid = pgid
    if resolved_pgid is None and proc.poll() is None:
        resolved_pgid = read_process_group_id(
            proc.pid,
            timeout=None if deadline is None else _remaining_seconds(deadline, default=0.0),
        )

    members = list(member_identities) if member_identities is not None else None
    if members is None and resolved_identity is not None and proc.poll() is None:
        members = capture_process_group_identities(
            resolved_identity,
            timeout=None if deadline is None else _remaining_seconds(deadline, default=0.0),
        )

    drain_budget = None if deadline is None else _remaining_seconds(deadline, default=0.0)
    drained = drain_owned_process_group(
        pgid=resolved_pgid,
        leader_identity=resolved_identity,
        known_identities=members,
        timeout=drain_budget,
    )
    if isinstance(status, dict):
        owner = getattr(proc, "_core_tools_janitor_status_owner", None)
        if isinstance(owner, JanitorStatusOwner):
            owner.finalize_status_ownership()
        raw_wait = getattr(proc, "_core_tools_raw_wait", proc.wait)
        if callable(raw_wait):
            try:
                raw_wait(timeout=0)
            except (OSError, subprocess.TimeoutExpired):
                pass
        return TerminateIdentityResult.FAILED
    if drained:
        from core_tools.provider.session_janitor import complete_bound_secondary_clean

        cleaned = {
            "agent_code": 0,
            "drain": DrainResult.CLEAN.value,
            "stop_requested": True,
        }
        if complete_bound_secondary_clean(proc, cleaned):
            return TerminateIdentityResult.TERMINATED
        return TerminateIdentityResult.FAILED
    return TerminateIdentityResult.FAILED


def _terminate_linux_identity(
    identity: ProcessIdentity,
    *,
    timeout: float | None = None,
) -> TerminateIdentityResult:
    deadline = _deadline_from_timeout(timeout)

    def remaining() -> float | None:
        if deadline is None:
            return None
        return _remaining_seconds(deadline, default=0.0)

    state = inspect_process_identity(identity, timeout=remaining())
    if state is IdentityInspectState.GONE:
        return TerminateIdentityResult.ALREADY_GONE
    if state is IdentityInspectState.IDENTITY_MISMATCH:
        return TerminateIdentityResult.IDENTITY_MISMATCH
    if state is IdentityInspectState.UNVERIFIABLE:
        return TerminateIdentityResult.FAILED

    captured = capture_process_group_identities(identity, timeout=remaining())
    if captured is None:
        return TerminateIdentityResult.FAILED

    pgid = read_process_group_id(identity.pid, timeout=remaining())
    if drain_owned_process_group(
        pgid=pgid,
        leader_identity=identity,
        known_identities=captured,
        timeout=remaining(),
    ):
        return TerminateIdentityResult.TERMINATED
    return TerminateIdentityResult.FAILED


def terminate_verified_process_identity(
    identity: ProcessIdentity | None,
    *,
    proc: subprocess.Popen[Any] | None = None,
    pgid: int | None = None,
    member_identities: list[ProcessIdentity] | None = None,
    timeout: float | None = None,
) -> TerminateIdentityResult:
    """Terminate *identity* using a process-instance-safe primitive."""

    if proc is not None:
        return _terminate_bound_process(
            identity,
            proc,
            pgid=pgid,
            member_identities=member_identities,
            timeout=timeout,
        )

    if identity is None:
        return TerminateIdentityResult.FAILED

    remaining = _remaining_fn(timeout)
    state = inspect_process_identity(identity, timeout=remaining())
    if state is IdentityInspectState.UNVERIFIABLE:
        return TerminateIdentityResult.FAILED
    if state is IdentityInspectState.IDENTITY_MISMATCH:
        return TerminateIdentityResult.IDENTITY_MISMATCH
    if state is IdentityInspectState.GONE:
        pgid = (
            read_process_group_id(identity.pid, timeout=remaining())
            if pgid is None
            else pgid
        )
        if pgid is not None and member_identities:
            if drain_owned_process_group(
                pgid=pgid,
                leader_identity=identity,
                known_identities=member_identities,
                timeout=remaining(),
            ):
                return TerminateIdentityResult.TERMINATED
            return TerminateIdentityResult.FAILED
        return TerminateIdentityResult.ALREADY_GONE

    if not _pidfd_supported():
        return TerminateIdentityResult.FAILED

    return _terminate_linux_identity(identity, timeout=remaining())


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
