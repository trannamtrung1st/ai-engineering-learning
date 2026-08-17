"""Session-leader janitor that owns a process group until the agent tree is gone.

The janitor is spawned with ``start_new_session=True`` so its PID is the PGID.
It proxies agent stdio so descendants cannot hold Cursor's external pipes, and it
does not drop the ownership anchor until the owned group is emptied or SIGKILL'd
while this process is still the live session leader.
"""

from __future__ import annotations

import ctypes
import errno
import json
import os
import select
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

_TERM_DRAIN_SECONDS = 5.0
_KILL_DRAIN_SECONDS = 5.0
_POLL_INTERVAL = 0.05
_AGENT_WAIT_SECONDS = 2.0
_TAIL_DRAIN_SECONDS = 0.2
_PROXY_JOIN_SECONDS = 1.0
_PS_TIMEOUT_SECONDS = 2.0
_PARENT_WAIT_MARGIN_SECONDS = 3.0
_ESCALATE_HANDOFF_SECONDS = 2.0

JANITOR_CLEANUP_BUDGET_SECONDS = (
    2 * _PROXY_JOIN_SECONDS
    + _TERM_DRAIN_SECONDS
    + _KILL_DRAIN_SECONDS
    + 2 * _AGENT_WAIT_SECONDS
    + _TAIL_DRAIN_SECONDS
    + 2 * _PS_TIMEOUT_SECONDS
    + _ESCALATE_HANDOFF_SECONDS
)
JANITOR_PARENT_WAIT_SECONDS = JANITOR_CLEANUP_BUDGET_SECONDS + _PARENT_WAIT_MARGIN_SECONDS


@dataclass(frozen=True)
class CleanupDeadline:
    """Absolute monotonic deadline for janitor tree cleanup."""

    end: float
    clock: Callable[[], float] = time.monotonic

    @classmethod
    def after(
        cls,
        seconds: float,
        *,
        clock: Callable[[], float] | None = None,
    ) -> CleanupDeadline:
        tick = time.monotonic if clock is None else clock
        return cls(tick() + max(0.0, seconds), clock=tick)

    def remaining(self) -> float:
        return max(0.0, self.end - self.clock())


class DrainResult(Enum):
    CLEAN = "clean"
    UNVERIFIABLE = "unverifiable"
    SURVIVORS = "survivors"


def drain_result_if_proxies_live(
    drain: DrainResult,
    *,
    proxies_done: bool,
) -> DrainResult:
    """CLEAN requires stdout and stderr proxy threads to have finished."""

    if drain is DrainResult.CLEAN and not proxies_done:
        return DrainResult.SURVIVORS
    return drain


class ControlEvent(Enum):
    TIMEOUT = "timeout"
    STOP = "stop"
    EOF = "eof"
    ERROR = "error"


def janitor_command(
    agent_argv: list[str],
    *,
    status_fd: int | None = None,
    started_fd: int | None = None,
    ready_timeout: float | None = None,
) -> list[str]:
    """Return argv that runs *agent_argv* under this session-leader janitor."""

    command = [sys.executable, "-u", str(Path(__file__).resolve())]
    if status_fd is not None:
        command.extend(["--status-fd", str(status_fd)])
    if started_fd is not None:
        command.extend(["--started-fd", str(started_fd)])
    if ready_timeout is not None:
        command.extend(["--ready-timeout", f"{max(0.0, ready_timeout):.6f}"])
    command.append("--")
    command.extend(agent_argv)
    return command


def decode_janitor_status(raw: bytes | str | None) -> dict[str, Any] | None:
    """Parse a janitor status record from a side-channel payload."""

    if not raw:
        return None
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace")
    else:
        text = raw
    line = ""
    for candidate in reversed(text.splitlines()):
        stripped = candidate.strip()
        if stripped:
            line = stripped
            break
    if not line:
        return None
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    drain = payload.get("drain")
    if drain not in {item.value for item in DrainResult}:
        return None
    return payload


class JanitorOwnerState(Enum):
    PENDING = "pending"
    TERMINAL = "terminal"
    EOF_WITHOUT_STATUS = "eof_without_status"
    TIMED_OUT = "timed_out"
    CLOSED = "closed"
    SAFE_FALLBACK_COMPLETE = "safe_fallback_complete"
    FALLBACK_SURVIVORS = "fallback_survivors"
    FALLBACK_UNVERIFIABLE = "fallback_unverifiable"


def _status_drain_is_clean(status: dict[str, Any] | None) -> bool:
    return isinstance(status, dict) and status.get("drain") == DrainResult.CLEAN.value


class JanitorStatusOwner:
    """Single-reader barrier for a bound janitor public-status FD."""

    def __init__(self, fd: int) -> None:
        self._lock = threading.Lock()
        self._done = threading.Condition(self._lock)
        self._fd: int | None = fd
        self._status: dict[str, Any] | None = None
        self._state = JanitorOwnerState.PENDING
        self._reader_active = False
        self._closed = False

    @property
    def reap_allowed(self) -> bool:
        return _status_drain_is_clean(self._status) and self._state in {
            JanitorOwnerState.TERMINAL,
            JanitorOwnerState.SAFE_FALLBACK_COMPLETE,
        }

    def mark_safe_fallback(self, status: dict[str, Any]) -> None:
        with self._lock:
            if self.reap_allowed and _status_drain_is_clean(status):
                self._done.notify_all()
                return
            self._status = status
            if _status_drain_is_clean(status):
                self._state = JanitorOwnerState.SAFE_FALLBACK_COMPLETE
            elif status.get("drain") == DrainResult.SURVIVORS.value:
                self._state = JanitorOwnerState.FALLBACK_SURVIVORS
            else:
                self._state = JanitorOwnerState.FALLBACK_UNVERIFIABLE
            self._done.notify_all()

    def close(self) -> None:
        with self._lock:
            already = self._closed
            self._closed = True
            if self._state is JanitorOwnerState.PENDING:
                self._state = JanitorOwnerState.CLOSED
            fd = None
            if not already and not self._reader_active:
                fd = self._fd
                self._fd = None
            self._done.notify_all()
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

    def finalize_status_ownership(self) -> None:
        """Release the barrier and close the retained FD after CLEAN is recorded."""

        deadline = time.monotonic() + JANITOR_PARENT_WAIT_SECONDS
        while True:
            with self._lock:
                if not self._reader_active:
                    break
                remaining = max(0.0, deadline - time.monotonic())
                if remaining <= 0:
                    break
                self._done.wait(timeout=remaining)
            if time.monotonic() >= deadline:
                break
        self.close()

    def bind(self, proc: Any) -> None:
        """Attach lifecycle guards so poll/wait cannot reap before terminal status."""

        if getattr(proc, "_core_tools_janitor_bound", False):
            return
        raw_poll = getattr(proc, "poll", None)
        raw_wait = getattr(proc, "wait", None)
        if not callable(raw_poll) or not callable(raw_wait):
            return
        owner = self

        def poll(*args: object, **kwargs: object) -> int | None:
            if not owner.reap_allowed:
                return None
            return raw_poll(*args, **kwargs)

        def wait(timeout: float | None = None) -> int:
            budget = JANITOR_PARENT_WAIT_SECONDS if timeout is None else max(0.0, timeout)
            deadline = time.monotonic() + budget
            owner.read(timeout=max(0.0, deadline - time.monotonic()))
            if not owner.reap_allowed:
                raise subprocess.TimeoutExpired(
                    getattr(proc, "args", None),
                    timeout if timeout is not None else budget,
                )
            remaining = max(0.0, deadline - time.monotonic())
            return raw_wait(timeout=remaining)

        proc.poll = poll
        proc.wait = wait
        proc._core_tools_janitor_bound = True
        proc._core_tools_raw_poll = raw_poll
        proc._core_tools_raw_wait = raw_wait

    def read(self, *, timeout: float) -> dict[str, Any] | None:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            with self._lock:
                if self.reap_allowed:
                    return self._status
                remaining = max(0.0, deadline - time.monotonic())
                if self._reader_active:
                    if remaining <= 0:
                        return None
                    self._done.wait(timeout=remaining)
                    continue
                fd = self._fd
                if fd is None:
                    return self._status if self.reap_allowed else None
                self._fd = None
                self._reader_active = True
            outcome, status = _read_status_fd(
                fd,
                timeout=max(0.0, deadline - time.monotonic()),
            )
            close_fd = False
            with self._lock:
                self._reader_active = False
                if outcome == "timeout":
                    if self.reap_allowed:
                        close_fd = True
                        result = self._status
                    else:
                        self._state = JanitorOwnerState.TIMED_OUT
                        if self._closed:
                            close_fd = True
                        else:
                            self._fd = fd
                        result = None
                elif outcome == "terminal" and status is not None:
                    close_fd = True
                    if self._state is not JanitorOwnerState.SAFE_FALLBACK_COMPLETE:
                        self._status = status
                        self._state = JanitorOwnerState.TERMINAL
                    result = self._status
                else:
                    close_fd = True
                    if self._state not in {
                        JanitorOwnerState.TERMINAL,
                        JanitorOwnerState.SAFE_FALLBACK_COMPLETE,
                    }:
                        self._state = JanitorOwnerState.EOF_WITHOUT_STATUS
                    result = self._status
                self._done.notify_all()
            if close_fd:
                try:
                    os.close(fd)
                except OSError:
                    pass
            return result


def _read_status_fd(fd: int, *, timeout: float) -> tuple[str, dict[str, Any] | None]:
    chunks: list[bytes] = []
    try:
        ready, _, _ = select.select([fd], [], [], max(0.0, timeout))
        if not ready:
            return "timeout", None
        while True:
            data = os.read(fd, 4096)
            if not data:
                break
            chunks.append(data)
            if b"\n" in data:
                break
    except OSError:
        return "eof", None
    if not chunks:
        return "eof", None
    decoded = decode_janitor_status(b"".join(chunks))
    if decoded is None:
        return "eof", None
    return "terminal", decoded


def _consume_status_fd(fd: int, *, timeout: float) -> dict[str, Any] | None:
    outcome, status = _read_status_fd(fd, timeout=timeout)
    try:
        os.close(fd)
    except OSError:
        pass
    return status if outcome == "terminal" else None


_STATUS_BIND_LOCK = threading.Lock()


def complete_bound_secondary_clean(
    proc: Any,
    payload: dict[str, Any] | None = None,
) -> bool:
    """Record CLEAN, reap the bound Popen, then finalize status ownership."""

    cleaned = payload or {
        "agent_code": 0,
        "drain": DrainResult.CLEAN.value,
        "stop_requested": True,
    }
    owner = getattr(proc, "_core_tools_janitor_status_owner", None)
    if isinstance(owner, JanitorStatusOwner):
        current = owner._status
        if not (
            isinstance(current, dict)
            and current.get("drain") == DrainResult.CLEAN.value
        ):
            owner.finalize_status_ownership()
            return False
        owner.mark_safe_fallback(cleaned)
    else:
        marker = getattr(owner, "mark_safe_fallback", None)
        if callable(marker):
            marker(cleaned)
    setattr(proc, "_core_tools_janitor_status", cleaned)
    try:
        proc.wait(timeout=JANITOR_PARENT_WAIT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        return False
    if isinstance(owner, JanitorStatusOwner):
        owner.finalize_status_ownership()
    else:
        closer = getattr(owner, "close", None)
        if callable(closer):
            closer()
    return True


def read_bound_janitor_status(
    proc: Any,
    *,
    timeout: float,
) -> dict[str, Any] | None:
    """Read public janitor status from a bound Popen without reaping it first."""

    cached = getattr(proc, "_core_tools_janitor_status", None)
    if isinstance(cached, dict):
        return cached
    with _STATUS_BIND_LOCK:
        cached = getattr(proc, "_core_tools_janitor_status", None)
        if isinstance(cached, dict):
            return cached
        owner = getattr(proc, "_core_tools_janitor_status_owner", None)
        if owner is None:
            fd = getattr(proc, "_core_tools_janitor_status_fd", None)
            if isinstance(fd, int):
                owner = JanitorStatusOwner(fd)
                owner.bind(proc)
                setattr(proc, "_core_tools_janitor_status_owner", owner)
                setattr(proc, "_core_tools_janitor_status_fd", None)
        elif owner is not None:
            owner.bind(proc)
    if owner is not None:
        status = owner.read(timeout=timeout)
        setattr(proc, "_core_tools_janitor_status", status)
        return status
    return cached if isinstance(cached, dict) else None


def _deadline_expired(deadline: CleanupDeadline | None) -> bool:
    return deadline is not None and deadline.remaining() <= 0


def _linux_peer_pids(
    pgid: int,
    me: int,
    deadline: CleanupDeadline | None = None,
    exclude: set[int] | frozenset[int] | None = None,
) -> list[int] | None:
    if _deadline_expired(deadline):
        return None
    skipped = set(exclude or ())
    skipped.add(me)
    proc_root = "/proc"
    try:
        entries = os.listdir(proc_root)
    except OSError:
        return None
    peers: list[int] = []
    for entry in entries:
        if _deadline_expired(deadline):
            return None
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid in skipped:
            continue
        try:
            with open(os.path.join(proc_root, entry, "stat"), encoding="utf-8") as handle:
                if _deadline_expired(deadline):
                    return None
                text = handle.read()
        except OSError:
            if _deadline_expired(deadline):
                return None
            try:
                member_pgid = os.getpgid(pid)
            except OSError as exc:
                if getattr(exc, "errno", None) == errno.ESRCH:
                    continue
                return None
            if member_pgid == pgid:
                return None
            continue
        close = text.rfind(")")
        if close == -1:
            return None
        fields = text[close + 2 :].split()
        if len(fields) < 4:
            return None
        try:
            member_pgid = int(fields[2])
        except ValueError:
            return None
        if member_pgid == pgid:
            peers.append(pid)
    return _confirmed_peers(peers, pgid, me, deadline=deadline, exclude=skipped)


def _scan_timeout(deadline: CleanupDeadline | None) -> float:
    if deadline is None:
        return _PS_TIMEOUT_SECONDS
    remaining = deadline.remaining()
    if remaining <= 0:
        return 0.0
    return min(_PS_TIMEOUT_SECONDS, remaining)


def _ps_peer_pids(
    pgid: int,
    me: int,
    deadline: CleanupDeadline | None = None,
    exclude: set[int] | frozenset[int] | None = None,
) -> list[int] | None:
    timeout = _scan_timeout(deadline)
    if timeout <= 0:
        return None
    skipped = set(exclude or ())
    skipped.add(me)
    try:
        completed = subprocess.run(
            ["ps", "-axo", "pid=,pgid="],
            check=False,
            capture_output=True,
            text=True,
            start_new_session=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    peers: list[int] = []
    for line in completed.stdout.splitlines():
        if _deadline_expired(deadline):
            return None
        parts = line.split()
        if not parts:
            continue
        if len(parts) < 2:
            return None
        try:
            pid = int(parts[0])
            member_pgid = int(parts[1])
        except ValueError:
            return None
        if pid in skipped:
            continue
        if member_pgid == pgid:
            peers.append(pid)
    return _confirmed_peers(peers, pgid, me, deadline=deadline, exclude=skipped)


def _confirmed_peers(
    candidates: list[int],
    pgid: int,
    me: int,
    deadline: CleanupDeadline | None = None,
    exclude: set[int] | frozenset[int] | None = None,
) -> list[int] | None:
    skipped = set(exclude or ())
    skipped.add(me)
    peers: list[int] = []
    for pid in candidates:
        if _deadline_expired(deadline):
            return None
        if pid in skipped:
            continue
        try:
            member_pgid = os.getpgid(pid)
        except OSError as exc:
            if getattr(exc, "errno", None) == errno.ESRCH:
                continue
            return None
        if member_pgid != pgid:
            continue
        peers.append(pid)
    return peers


def _peer_pids(
    deadline: CleanupDeadline | None = None,
    *,
    pgid: int | None = None,
    me: int | None = None,
    exclude: set[int] | frozenset[int] | None = None,
) -> list[int] | None:
    """Return same-group peers excluding this process, or None if listing failed."""

    if _deadline_expired(deadline):
        return None
    self_pid = os.getpid() if me is None else me
    group = os.getpgrp() if pgid is None else pgid
    skipped = set(exclude or ())
    skipped.add(self_pid)
    if sys.platform.startswith("linux") and os.path.isdir("/proc"):
        return _linux_peer_pids(group, self_pid, deadline=deadline, exclude=skipped)
    return _ps_peer_pids(group, self_pid, deadline=deadline, exclude=skipped)


def _process_start_token(
    pid: int,
    deadline: CleanupDeadline | None = None,
) -> str | None:
    """Return a process-instance start token, or None when it cannot be read."""

    if pid <= 0 or _deadline_expired(deadline):
        return None
    if os.path.isdir("/proc"):
        return _linux_process_start_token(pid, deadline=deadline)
    if sys.platform == "darwin":
        return _darwin_process_start_token(pid, deadline=deadline)
    return None


def _linux_process_start_token(
    pid: int,
    deadline: CleanupDeadline | None = None,
) -> str | None:
    if _deadline_expired(deadline):
        return None
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as handle:
            if _deadline_expired(deadline):
                return None
            text = handle.read()
    except OSError:
        return None
    close = text.rfind(")")
    if close == -1:
        return None
    fields = text[close + 2 :].split()
    if len(fields) < 20:
        return None
    token = fields[19]
    if _deadline_expired(deadline):
        return None
    return token


_PROC_PIDTBSDINFO = 3
_MAXCOMLEN = 16


class _ProcBsdInfo(ctypes.Structure):
    _fields_ = [
        ("pbi_flags", ctypes.c_uint32),
        ("pbi_status", ctypes.c_uint32),
        ("pbi_xstatus", ctypes.c_uint32),
        ("pbi_pid", ctypes.c_uint32),
        ("pbi_ppid", ctypes.c_uint32),
        ("pbi_uid", ctypes.c_uint32),
        ("pbi_gid", ctypes.c_uint32),
        ("pbi_ruid", ctypes.c_uint32),
        ("pbi_rgid", ctypes.c_uint32),
        ("pbi_svuid", ctypes.c_uint32),
        ("pbi_svgid", ctypes.c_uint32),
        ("rfu_1", ctypes.c_uint32),
        ("pbi_comm", ctypes.c_char * _MAXCOMLEN),
        ("pbi_name", ctypes.c_char * (2 * _MAXCOMLEN)),
        ("pbi_nfiles", ctypes.c_uint32),
        ("pbi_pgid", ctypes.c_uint32),
        ("pbi_pjobc", ctypes.c_uint32),
        ("e_tdev", ctypes.c_uint32),
        ("e_tpgid", ctypes.c_uint32),
        ("pbi_nice", ctypes.c_int32),
        ("pbi_start_tvsec", ctypes.c_uint64),
        ("pbi_start_tvusec", ctypes.c_uint64),
    ]


def _darwin_process_start_token(
    pid: int,
    deadline: CleanupDeadline | None = None,
) -> str | None:
    if _deadline_expired(deadline) or pid <= 0:
        return None
    info = _ProcBsdInfo()
    try:
        lib = ctypes.CDLL("/usr/lib/libproc.dylib")
        nbytes = lib.proc_pidinfo(
            int(pid),
            _PROC_PIDTBSDINFO,
            ctypes.c_uint64(0),
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
    except OSError:
        return None
    if nbytes != ctypes.sizeof(info):
        return None
    if int(info.pbi_pid) != int(pid):
        return None
    if _deadline_expired(deadline):
        return None
    return f"{int(info.pbi_start_tvsec)}.{int(info.pbi_start_tvusec):06d}"


def _leader_still_owns_group(
    pgid: int,
    leader_pid: int | None,
    leader_start: str | None,
    deadline: CleanupDeadline | None = None,
) -> bool:
    """Return True when *leader_pid* still anchors *pgid* as the same process."""

    if leader_pid is None or not leader_start or _deadline_expired(deadline):
        return False
    # A process-group leader's PID must equal its PGID.
    if leader_pid != pgid:
        return False
    try:
        if os.getpgid(leader_pid) != pgid:
            return False
        if os.getsid(leader_pid) != leader_pid:
            return False
    except OSError:
        return False
    current = _process_start_token(leader_pid, deadline=deadline)
    if current is None or current != leader_start:
        return False
    if _deadline_expired(deadline):
        return False
    return True


def _record_group_signal(
    *,
    target_pgid: int,
    sig: int,
    reason: str,
    authorized: bool,
) -> None:
    record = {
        "sender_pid": os.getpid(),
        "sender_pgid": os.getpgrp(),
        "target_pgid": target_pgid,
        "signal": int(sig),
        "reason": reason,
        "authorized": authorized,
        "run_id": os.environ.get("TDP_RUN_ID"),
        "provider_owner_id": os.environ.get("TDP_PROVIDER_OWNER_ID"),
    }
    try:
        record["sender_sid"] = os.getsid(os.getpid())
    except OSError:
        record["sender_sid"] = None
    log_path = os.environ.get("TDP_GROUP_SIGNAL_LOG")
    if log_path:
        try:
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, separators=(",", ":")) + "\n")
        except OSError:
            pass


def _signal_group(sig: int) -> None:
    try:
        me = os.getpid()
        pgid = os.getpgrp()
        if me != pgid:
            _record_group_signal(
                target_pgid=pgid, sig=sig, reason="not_session_leader", authorized=False
            )
            return
        try:
            if os.getpgid(me) != pgid:
                _record_group_signal(
                    target_pgid=pgid,
                    sig=sig,
                    reason="pgid_mismatch",
                    authorized=False,
                )
                return
        except OSError:
            return
        try:
            if os.getpgid(os.getppid()) == pgid:
                _record_group_signal(
                    target_pgid=pgid,
                    sig=sig,
                    reason="parent_process_group",
                    authorized=False,
                )
                return
        except OSError:
            pass
        _record_group_signal(
            target_pgid=pgid, sig=sig, reason="session_leader_group", authorized=True
        )
        os.killpg(pgid, sig)
    except OSError:
        pass


def _kill_agent(agent: subprocess.Popen[Any]) -> None:
    if agent.poll() is None:
        try:
            agent.kill()
        except OSError:
            pass


def _reap_zombie_children() -> None:
    if not hasattr(os, "waitpid"):
        return
    while True:
        try:
            pid, _status = os.waitpid(-1, os.WNOHANG)
        except (ChildProcessError, OSError):
            return
        if pid == 0:
            return


def _close_inherited_stdout() -> None:
    """Let the parent observe stdout EOF while group cleanup continues."""

    try:
        sys.stdout.flush()
    except Exception:
        pass
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
    except OSError:
        return
    try:
        os.dup2(devnull, 1)
    finally:
        if devnull != 1:
            try:
                os.close(devnull)
            except OSError:
                pass


def _close_inherited_stdio_write_ends() -> None:
    """Close inherited stdout/stderr write ends after stream proxies finish."""

    _close_inherited_stdout()
    try:
        sys.stderr.flush()
    except Exception:
        pass
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
    except OSError:
        return
    try:
        os.dup2(devnull, 2)
    finally:
        if devnull != 2:
            try:
                os.close(devnull)
            except OSError:
                pass


def _wait_peers_gone(
    deadline: CleanupDeadline,
    *,
    budget: float,
    pgid: int | None = None,
    me: int | None = None,
    exclude: set[int] | frozenset[int] | None = None,
) -> DrainResult:
    now = deadline.clock
    phase_end = now() + min(max(0.0, budget), deadline.remaining())
    last: DrainResult = DrainResult.SURVIVORS
    while now() < phase_end and deadline.remaining() > 0:
        _reap_zombie_children()
        peers = _peer_pids(deadline, pgid=pgid, me=me, exclude=exclude)
        if peers is None:
            return DrainResult.UNVERIFIABLE
        if not peers:
            return DrainResult.CLEAN
        last = DrainResult.SURVIVORS
        pause = min(_POLL_INTERVAL, deadline.remaining())
        if pause > 0 and deadline.clock is time.monotonic:
            time.sleep(pause)
    peers = _peer_pids(deadline, pgid=pgid, me=me, exclude=exclude)
    if peers is None:
        return DrainResult.UNVERIFIABLE
    if not peers:
        return DrainResult.CLEAN
    return last


def _drain_group(
    agent: subprocess.Popen[Any],
    deadline: CleanupDeadline | None = None,
) -> DrainResult:
    if deadline is None:
        deadline = CleanupDeadline.after(JANITOR_CLEANUP_BUDGET_SECONDS)
    previous_term = signal.getsignal(signal.SIGTERM)
    previous_int = signal.getsignal(signal.SIGINT)
    try:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        _signal_group(signal.SIGTERM)
        _reap_zombie_children()
        result = _wait_peers_gone(deadline, budget=_TERM_DRAIN_SECONDS)
        if result is DrainResult.CLEAN:
            return result
        _kill_agent(agent)
        _reap_zombie_children()
        return _wait_peers_gone(deadline, budget=_KILL_DRAIN_SECONDS)
    finally:
        try:
            signal.signal(signal.SIGTERM, previous_term)
        except (OSError, ValueError):
            pass
        try:
            signal.signal(signal.SIGINT, previous_int)
        except (OSError, ValueError):
            pass


def _poll_control(timeout: float) -> ControlEvent:
    try:
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
    except (OSError, ValueError):
        return ControlEvent.ERROR
    if not ready:
        return ControlEvent.TIMEOUT
    try:
        line = sys.stdin.readline()
    except OSError:
        return ControlEvent.ERROR
    if line == "":
        return ControlEvent.EOF
    if line.strip() == "STOP":
        return ControlEvent.STOP
    return ControlEvent.TIMEOUT


def _copy_available(src_fd: int, dst: object, timeout: float) -> None:
    write = getattr(dst, "write", None)
    flush = getattr(dst, "flush", None)
    if write is None:
        return
    try:
        os.set_blocking(src_fd, False)
    except OSError:
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = max(0.0, deadline - time.monotonic())
        try:
            ready, _, _ = select.select([src_fd], [], [], remaining)
        except (OSError, ValueError):
            break
        if not ready:
            break
        try:
            chunk = os.read(src_fd, 8192)
        except OSError:
            break
        if not chunk:
            break
        write(chunk)
        if flush is not None:
            flush()


def _proxy_stream(
    src: object,
    dst: object,
    stop: threading.Event,
    on_eof: Callable[[], None] | None = None,
    on_ready: Callable[[], None] | None = None,
) -> None:
    fileno = getattr(src, "fileno", None)
    if fileno is None:
        return
    try:
        src_fd = fileno()
    except OSError:
        return
    write = getattr(dst, "write", None)
    flush = getattr(dst, "flush", None)
    if write is None:
        return
    try:
        os.set_blocking(src_fd, False)
    except OSError:
        return
    if on_ready is not None:
        on_ready()
    while not stop.is_set():
        try:
            ready, _, _ = select.select([src_fd], [], [], _POLL_INTERVAL)
        except (OSError, ValueError):
            break
        if not ready:
            continue
        try:
            chunk = os.read(src_fd, 8192)
        except OSError:
            break
        if not chunk:
            break
        try:
            write(chunk)
            if flush is not None:
                flush()
        except OSError:
            break
    _copy_available(src_fd, dst, _TAIL_DRAIN_SECONDS)
    if on_eof is not None:
        on_eof()


def _parse_argv(argv: list[str]) -> tuple[int | None, list[str], dict[str, Any]]:
    args = list(argv)
    status_fd: int | None = None
    started_fd: int | None = None
    escalate_pgid: int | None = None
    handshake_fd: int | None = None
    go_fd: int | None = None
    result_fd: int | None = None
    leader_pid: int | None = None
    leader_start: str | None = None
    agent_code = 0
    stop_requested = False
    cleanup_budget: float | None = None
    ready_timeout: float | None = None
    while len(args) >= 2 and args[0].startswith("--") and args[0] != "--":
        flag = args[0]
        raw_value = args[1]
        args = args[2:]
        try:
            if flag == "--status-fd":
                status_fd = int(raw_value)
            elif flag == "--started-fd":
                started_fd = int(raw_value)
            elif flag == "--escalate-pgid":
                escalate_pgid = int(raw_value)
            elif flag == "--handshake-fd":
                handshake_fd = int(raw_value)
            elif flag == "--go-fd":
                go_fd = int(raw_value)
            elif flag == "--result-fd":
                result_fd = int(raw_value)
            elif flag == "--leader-pid":
                leader_pid = int(raw_value)
            elif flag == "--leader-start":
                leader_start = raw_value
            elif flag == "--agent-code":
                agent_code = int(raw_value)
            elif flag == "--stop-requested":
                stop_requested = raw_value in {"1", "true", "True"}
            elif flag == "--cleanup-budget":
                cleanup_budget = float(raw_value)
            elif flag == "--ready-timeout":
                ready_timeout = float(raw_value)
            else:
                args = [flag, raw_value, *args]
                break
        except ValueError:
            continue
    if args[:1] == ["--"]:
        args = args[1:]
    extra = {
        "escalate_pgid": escalate_pgid,
        "started_fd": started_fd,
        "handshake_fd": handshake_fd,
        "go_fd": go_fd,
        "result_fd": result_fd,
        "leader_pid": leader_pid,
        "leader_start": leader_start,
        "agent_code": agent_code,
        "stop_requested": stop_requested,
        "cleanup_budget": cleanup_budget,
        "ready_timeout": ready_timeout,
    }
    return status_fd, args, extra


def _write_status(status_fd: int | None, payload: Mapping[str, Any]) -> None:
    if status_fd is None:
        return
    try:
        os.write(status_fd, json.dumps(dict(payload)).encode("utf-8") + b"\n")
    except OSError:
        pass


def _wait_agent(
    agent: subprocess.Popen[Any],
    deadline: CleanupDeadline | None = None,
) -> int | None:
    timeout = _AGENT_WAIT_SECONDS
    if deadline is not None:
        timeout = min(timeout, deadline.remaining())
    if timeout <= 0:
        return agent.poll()
    try:
        return agent.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        if agent.poll() is None:
            try:
                agent.kill()
            except OSError:
                pass
            remaining = _AGENT_WAIT_SECONDS
            if deadline is not None:
                remaining = min(remaining, deadline.remaining())
            if remaining <= 0:
                return agent.poll()
            try:
                return agent.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                return agent.poll()
        return agent.poll()


def _abandon_group_if_unresolved(drain: DrainResult) -> None:
    if drain is DrainResult.CLEAN:
        return
    _signal_group(signal.SIGKILL)


def _close_agent_streams(agent: subprocess.Popen[Any]) -> None:
    for stream in (agent.stdout, agent.stderr):
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass


def _write_result(result_fd: int | None, payload: Mapping[str, Any]) -> None:
    _write_status(result_fd, payload)


def _close_fd(fd: int | None) -> None:
    if fd is None:
        return
    try:
        os.close(fd)
    except OSError:
        pass


def _reap_verifier(proc: subprocess.Popen[Any] | None, *, timeout: float = 0.0) -> None:
    if proc is None:
        return
    if proc.poll() is None:
        try:
            pgid = os.getpgid(proc.pid)
        except OSError:
            pgid = None
        if pgid == proc.pid:
            parent_pgid = None
            try:
                parent_pgid = os.getpgid(os.getppid())
            except OSError:
                pass
            if parent_pgid != pgid:
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except OSError:
                    pass
        try:
            proc.kill()
        except OSError:
            pass
    leftover = max(0.0, timeout)
    deadline = time.monotonic() + leftover
    waitpid = getattr(os, "waitpid", None)
    pid = getattr(proc, "pid", None)
    while waitpid is not None and pid:
        try:
            waited, _status = waitpid(pid, os.WNOHANG)
        except (ChildProcessError, OSError):
            break
        if waited:
            break
        remaining = max(0.0, deadline - time.monotonic())
        if remaining <= 0:
            break
        time.sleep(min(0.01, remaining))
    remaining = max(0.0, deadline - time.monotonic())
    if remaining <= 0:
        try:
            proc.poll()
        except OSError:
            pass
        return
    try:
        proc.wait(timeout=remaining)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _await_go(go_fd: int | None, timeout: float) -> tuple[bool, float | None]:
    if go_fd is None:
        return False, None
    try:
        ready, _, _ = select.select([go_fd], [], [], max(0.0, timeout))
        if not ready:
            return False, None
        data = os.read(go_fd, 32)
    except OSError:
        return False, None
    if not data.startswith(b"GO"):
        return False, None
    parts = data.split()
    if len(parts) < 2:
        return True, None
    try:
        return True, max(0.0, float(parts[1]))
    except ValueError:
        return True, None


def _hold_ownership_anchor(deadline: CleanupDeadline) -> None:
    remaining = deadline.remaining()
    if remaining > 0:
        time.sleep(remaining)
    while True:
        time.sleep(1.0)


def _escalation_command(
    *,
    pgid: int,
    status_fd: int | None,
    handshake_fd: int,
    go_fd: int,
    result_fd: int,
    agent_code: int,
    stop_requested: bool,
    leader_pid: int,
    leader_start: str | None = None,
    cleanup_budget: float | None = None,
) -> list[str]:
    command = [sys.executable, "-u", str(Path(__file__).resolve())]
    if status_fd is not None:
        command.extend(["--status-fd", str(status_fd)])
    command.extend(
        [
            "--escalate-pgid",
            str(pgid),
            "--handshake-fd",
            str(handshake_fd),
            "--go-fd",
            str(go_fd),
            "--result-fd",
            str(result_fd),
            "--agent-code",
            str(agent_code),
            "--stop-requested",
            "1" if stop_requested else "0",
            "--leader-pid",
            str(leader_pid),
            "--leader-start",
            leader_start or "",
            "--cleanup-budget",
            f"{max(0.0, cleanup_budget if cleanup_budget is not None else 0.0):.6f}",
        ]
    )
    return command


def _handoff_group_escalation(
    *,
    pgid: int,
    status_fd: int | None,
    agent_code: int,
    stop_requested: bool,
    deadline: CleanupDeadline,
    leader_pid: int | None = None,
) -> DrainResult | None:
    handshake_r, handshake_w = os.pipe()
    go_r, go_w = os.pipe()
    result_r, result_w = os.pipe()
    if leader_pid is None:
        leader_pid = os.getpid()
    command = _escalation_command(
        pgid=pgid,
        status_fd=status_fd,
        handshake_fd=handshake_w,
        go_fd=go_r,
        result_fd=result_w,
        agent_code=agent_code,
        stop_requested=stop_requested,
        leader_pid=leader_pid,
        leader_start=_process_start_token(leader_pid, deadline=deadline),
        cleanup_budget=max(0.0, deadline.remaining()),
    )
    pass_fds = [handshake_w, go_r, result_w]
    if status_fd is not None:
        pass_fds.append(status_fd)
    proc: subprocess.Popen[Any] | None = None
    try:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
            pass_fds=tuple(pass_fds),
        )
    except OSError:
        _close_fd(handshake_r)
        _close_fd(handshake_w)
        _close_fd(go_r)
        _close_fd(go_w)
        _close_fd(result_r)
        _close_fd(result_w)
        return None
    _close_fd(handshake_w)
    _close_fd(go_r)
    _close_fd(result_w)
    timeout = min(_ESCALATE_HANDOFF_SECONDS, max(0.0, deadline.remaining()))
    try:
        ready, _, _ = select.select([handshake_r], [], [], timeout)
        if not ready:
            _close_fd(go_w)
            _close_fd(handshake_r)
            _close_fd(result_r)
            _reap_verifier(proc, timeout=max(0.0, deadline.remaining()))
            return None
        data = os.read(handshake_r, 16)
    except OSError:
        _close_fd(go_w)
        _close_fd(handshake_r)
        _close_fd(result_r)
        _reap_verifier(proc, timeout=max(0.0, deadline.remaining()))
        return None
    _close_fd(handshake_r)
    if not data.startswith(b"READY"):
        _close_fd(go_w)
        _close_fd(result_r)
        _reap_verifier(proc, timeout=max(0.0, deadline.remaining()))
        return None
    try:
        os.write(go_w, f"GO {max(0.0, deadline.remaining()):.6f}\n".encode())
    except OSError:
        _close_fd(go_w)
        _close_fd(result_r)
        _reap_verifier(proc, timeout=max(0.0, deadline.remaining()))
        return None
    _close_fd(go_w)
    result_timeout = max(0.0, deadline.remaining())
    try:
        ready, _, _ = select.select([result_r], [], [], result_timeout)
        payload = b""
        if ready:
            payload = os.read(result_r, 4096)
    except OSError:
        payload = b""
    _close_fd(result_r)
    if not payload:
        _reap_verifier(proc, timeout=max(0.0, deadline.remaining()))
        return None
    try:
        decoded = json.loads(payload.splitlines()[-1].decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, IndexError):
        _reap_verifier(proc, timeout=max(0.0, deadline.remaining()))
        return None
    if decoded.get("ok") is not True:
        _reap_verifier(proc, timeout=max(0.0, deadline.remaining()))
        drain = decoded.get("drain")
        if drain in {item.value for item in DrainResult}:
            return DrainResult(drain)
        return DrainResult.UNVERIFIABLE
    drain = decoded.get("drain")
    _reap_verifier(proc, timeout=max(0.0, deadline.remaining()))
    if drain in {item.value for item in DrainResult}:
        return DrainResult(drain)
    return DrainResult.UNVERIFIABLE


def _run_escalation(
    *,
    pgid: int,
    status_fd: int | None,
    handshake_fd: int | None,
    agent_code: int,
    stop_requested: bool,
    go_fd: int | None = None,
    result_fd: int | None = None,
    leader_pid: int | None = None,
    leader_start: str | None = None,
    go_timeout: float | None = None,
    cleanup_budget: float | None = None,
) -> int:
    if handshake_fd is not None:
        try:
            os.write(handshake_fd, b"READY\n")
        except OSError:
            _close_fd(handshake_fd)
            _close_fd(go_fd)
            _close_fd(result_fd)
            return 0
        _close_fd(handshake_fd)
    timeout = _ESCALATE_HANDOFF_SECONDS if go_timeout is None else go_timeout
    go_ok, go_remaining = _await_go(go_fd, timeout)
    if not go_ok:
        _close_fd(go_fd)
        _close_fd(result_fd)
        return 0
    _close_fd(go_fd)
    if go_remaining is not None:
        cleanup_budget = go_remaining

    def publish_failure(cleanup_error: str, *, error: str) -> int:
        payload = {
            "agent_code": agent_code,
            "drain": DrainResult.UNVERIFIABLE.value,
            "stop_requested": stop_requested,
            "cleanup_error": cleanup_error,
        }
        _write_status(status_fd, payload)
        _write_result(
            result_fd,
            {
                "ok": False,
                "error": error,
                "drain": DrainResult.UNVERIFIABLE.value,
            },
        )
        _close_fd(result_fd)
        return 1

    if cleanup_budget is not None and cleanup_budget <= 0:
        _close_fd(result_fd)
        return 0
    auth_budget = _PS_TIMEOUT_SECONDS
    drain_budget = _KILL_DRAIN_SECONDS
    if cleanup_budget is not None:
        auth_budget = min(auth_budget, max(0.0, cleanup_budget))
        drain_budget = min(drain_budget, max(0.0, cleanup_budget))
    auth_deadline = CleanupDeadline.after(auth_budget)
    if not _leader_still_owns_group(
        pgid,
        leader_pid,
        leader_start,
        deadline=auth_deadline,
    ):
        return publish_failure("leader_identity_lost", error="leader_identity_lost")
    if _deadline_expired(auth_deadline):
        return publish_failure("leader_identity_lost", error="leader_identity_lost")
    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError as exc:
        error = "eperm" if getattr(exc, "errno", None) == errno.EPERM else "oserror"
        return publish_failure("verifier_signal_failed", error=error)
    exclude = {leader_pid} if leader_pid is not None else None
    deadline = CleanupDeadline.after(drain_budget)
    drain = _wait_peers_gone(
        deadline,
        budget=drain_budget,
        pgid=pgid,
        exclude=exclude,
    )
    _write_status(
        status_fd,
        {
            "agent_code": agent_code,
            "drain": drain.value,
            "stop_requested": stop_requested,
        },
    )
    _write_result(result_fd, {"ok": True, "drain": drain.value})
    _close_fd(result_fd)
    return 0 if drain is DrainResult.CLEAN else 1


def main(
    argv: list[str] | None = None,
    *,
    status_fd: int | None = None,
) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    parsed_fd, command, extra = _parse_argv(raw)
    if status_fd is None:
        status_fd = parsed_fd
    if extra["escalate_pgid"] is not None:
        return _run_escalation(
            pgid=int(extra["escalate_pgid"]),
            status_fd=status_fd,
            handshake_fd=extra["handshake_fd"],
            go_fd=extra["go_fd"],
            result_fd=extra["result_fd"],
            agent_code=int(extra["agent_code"]),
            stop_requested=bool(extra["stop_requested"]),
            leader_pid=extra["leader_pid"],
            leader_start=extra.get("leader_start"),
            cleanup_budget=extra.get("cleanup_budget"),
        )
    if not command:
        return 2

    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    agent = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        close_fds=True,
    )
    drain_lock = threading.Lock()
    drained: DrainResult | None = None
    stop_requested = False
    stop_copy = threading.Event()
    cleanup_deadline: CleanupDeadline | None = None
    stdout_ready = threading.Event()

    def drain_once() -> DrainResult:
        nonlocal drained
        active = cleanup_deadline or CleanupDeadline.after(JANITOR_CLEANUP_BUDGET_SECONDS)
        with drain_lock:
            if drained is not None:
                return drained
            drained = _drain_group(agent, active)
            return drained

    def request_agent_stop() -> None:
        nonlocal stop_requested
        stop_requested = True
        if agent.poll() is None:
            try:
                agent.terminate()
            except OSError:
                pass

    def on_signal(_signum: int, _frame: object) -> None:
        request_agent_stop()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    stdout_dst = getattr(sys.stdout, "buffer", sys.stdout)
    stderr_dst = getattr(sys.stderr, "buffer", sys.stderr)
    stdout_thread = threading.Thread(
        target=_proxy_stream,
        args=(agent.stdout, stdout_dst, stop_copy),
        kwargs={
            "on_eof": _close_inherited_stdout,
            "on_ready": stdout_ready.set,
        },
        daemon=True,
    )
    stderr_ready = threading.Event()
    stderr_thread = threading.Thread(
        target=_proxy_stream,
        args=(agent.stderr, stderr_dst, stop_copy),
        kwargs={"on_ready": stderr_ready.set},
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    ready_deadline = time.monotonic() + (
        float(extra["ready_timeout"])
        if extra.get("ready_timeout") is not None
        else 1.0
    )
    stdout_ok = stdout_ready.wait(timeout=max(0.0, ready_deadline - time.monotonic()))
    stderr_ok = stderr_ready.wait(timeout=max(0.0, ready_deadline - time.monotonic()))
    started_fd = extra.get("started_fd")
    if started_fd is not None and stdout_ok and stderr_ok:
        try:
            os.write(int(started_fd), b"1")
        except OSError:
            pass
        _close_fd(int(started_fd))
    elif started_fd is not None:
        _close_fd(int(started_fd))

    while agent.poll() is None and not stop_requested:
        event = _poll_control(_POLL_INTERVAL)
        if event in {ControlEvent.STOP, ControlEvent.EOF, ControlEvent.ERROR}:
            request_agent_stop()
            break

    cleanup_deadline = CleanupDeadline.after(JANITOR_CLEANUP_BUDGET_SECONDS)

    def join_proxies(*, bound: float) -> None:
        stdout_thread.join(timeout=min(bound, max(0.0, cleanup_deadline.remaining())))
        stderr_thread.join(timeout=min(bound, max(0.0, cleanup_deadline.remaining())))
        if stdout_thread.is_alive() or stderr_thread.is_alive():
            stop_copy.set()
            leftover = min(0.05, max(0.0, cleanup_deadline.remaining()))
            stdout_thread.join(timeout=leftover)
            stderr_thread.join(timeout=leftover)
        if not stdout_thread.is_alive() and not stderr_thread.is_alive():
            _close_inherited_stdio_write_ends()
        elif not stdout_thread.is_alive():
            _close_inherited_stdout()

    observed = agent.poll()
    drain = drain_once()
    return_code = _wait_agent(agent, cleanup_deadline)
    join_proxies(bound=min(_PROXY_JOIN_SECONDS, 0.2))
    drain = drain_result_if_proxies_live(
        drain,
        proxies_done=(
            not stdout_thread.is_alive() and not stderr_thread.is_alive()
        ),
    )
    if observed == 0:
        return_code = 0
    if return_code is None:
        return_code = 1
        drain = DrainResult.SURVIVORS if drain is DrainResult.CLEAN else drain
    payload = {
        "agent_code": return_code,
        "drain": drain.value,
        "stop_requested": stop_requested,
    }
    if drain is DrainResult.CLEAN:
        _write_status(status_fd, payload)
        _close_agent_streams(agent)
        return 0 if stop_requested and return_code < 0 else return_code

    _close_agent_streams(agent)
    active = cleanup_deadline or CleanupDeadline.after(_ESCALATE_HANDOFF_SECONDS)
    handed = _handoff_group_escalation(
        pgid=os.getpgrp(),
        status_fd=status_fd,
        agent_code=return_code,
        stop_requested=stop_requested,
        deadline=active,
        leader_pid=os.getpid(),
    )
    if handed is DrainResult.CLEAN:
        handed = drain_result_if_proxies_live(
            handed,
            proxies_done=(
                not stdout_thread.is_alive() and not stderr_thread.is_alive()
            ),
        )
    if handed is DrainResult.CLEAN:
        _write_status(
            status_fd,
            {
                "agent_code": return_code,
                "drain": DrainResult.CLEAN.value,
                "stop_requested": stop_requested,
            },
        )
        return 0 if stop_requested and return_code < 0 else return_code
    _abandon_group_if_unresolved(DrainResult.SURVIVORS)
    _hold_ownership_anchor(active)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
