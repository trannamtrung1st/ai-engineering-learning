"""Session-leader janitor that owns a process group until the agent tree is gone.

The janitor is spawned with ``start_new_session=True`` so its PID is the PGID.
It proxies agent stdio so descendants cannot hold Cursor's external pipes, and it
does not drop the ownership anchor until the owned group is emptied or SIGKILL'd
while this process is still the live session leader.
"""

from __future__ import annotations

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
        clock: Callable[[], float] = time.monotonic,
    ) -> CleanupDeadline:
        return cls(clock() + max(0.0, seconds), clock=clock)

    def remaining(self) -> float:
        return max(0.0, self.end - self.clock())


class DrainResult(Enum):
    CLEAN = "clean"
    UNVERIFIABLE = "unverifiable"
    SURVIVORS = "survivors"


class ControlEvent(Enum):
    TIMEOUT = "timeout"
    STOP = "stop"
    EOF = "eof"
    ERROR = "error"


def janitor_command(agent_argv: list[str], *, status_fd: int | None = None) -> list[str]:
    """Return argv that runs *agent_argv* under this session-leader janitor."""

    command = [sys.executable, "-u", str(Path(__file__).resolve())]
    if status_fd is not None:
        command.extend(["--status-fd", str(status_fd)])
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


def _deadline_expired(deadline: CleanupDeadline | None) -> bool:
    return deadline is not None and deadline.remaining() <= 0


def _linux_peer_pids(
    pgid: int,
    me: int,
    deadline: CleanupDeadline | None = None,
) -> list[int] | None:
    if _deadline_expired(deadline):
        return None
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
        if pid == me:
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
    return _confirmed_peers(peers, pgid, me, deadline=deadline)


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
) -> list[int] | None:
    timeout = _scan_timeout(deadline)
    if timeout <= 0:
        return None
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
        if pid == me:
            continue
        if member_pgid == pgid:
            peers.append(pid)
    return _confirmed_peers(peers, pgid, me, deadline=deadline)


def _confirmed_peers(
    candidates: list[int],
    pgid: int,
    me: int,
    deadline: CleanupDeadline | None = None,
) -> list[int] | None:
    peers: list[int] = []
    for pid in candidates:
        if _deadline_expired(deadline):
            return None
        if pid == me:
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
) -> list[int] | None:
    """Return same-group peers excluding this process, or None if listing failed."""

    if _deadline_expired(deadline):
        return None
    self_pid = os.getpid() if me is None else me
    group = os.getpgrp() if pgid is None else pgid
    if sys.platform.startswith("linux") and os.path.isdir("/proc"):
        return _linux_peer_pids(group, self_pid, deadline=deadline)
    return _ps_peer_pids(group, self_pid, deadline=deadline)


def _signal_group(sig: int) -> None:
    try:
        os.killpg(os.getpgrp(), sig)
    except OSError:
        pass


def _kill_agent(agent: subprocess.Popen[Any]) -> None:
    if agent.poll() is None:
        try:
            agent.kill()
        except OSError:
            pass


def _wait_peers_gone(
    deadline: CleanupDeadline,
    *,
    budget: float,
    pgid: int | None = None,
    me: int | None = None,
) -> DrainResult:
    now = deadline.clock
    phase_end = now() + min(max(0.0, budget), deadline.remaining())
    last: DrainResult = DrainResult.SURVIVORS
    while now() < phase_end and deadline.remaining() > 0:
        peers = _peer_pids(deadline, pgid=pgid, me=me)
        if peers is None:
            return DrainResult.UNVERIFIABLE
        if not peers:
            return DrainResult.CLEAN
        last = DrainResult.SURVIVORS
        pause = min(_POLL_INTERVAL, deadline.remaining())
        if pause > 0 and deadline.clock is time.monotonic:
            time.sleep(pause)
    peers = _peer_pids(deadline, pgid=pgid, me=me)
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
        result = _wait_peers_gone(deadline, budget=_TERM_DRAIN_SECONDS)
        if result is DrainResult.CLEAN:
            return result
        _kill_agent(agent)
        return result
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


def _proxy_stream(src: object, dst: object, stop: threading.Event) -> None:
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


def _parse_argv(argv: list[str]) -> tuple[int | None, list[str], dict[str, Any]]:
    args = list(argv)
    status_fd: int | None = None
    escalate_pgid: int | None = None
    handshake_fd: int | None = None
    agent_code = 0
    stop_requested = False
    while len(args) >= 2 and args[0].startswith("--") and args[0] != "--":
        flag = args[0]
        raw_value = args[1]
        args = args[2:]
        try:
            if flag == "--status-fd":
                status_fd = int(raw_value)
            elif flag == "--escalate-pgid":
                escalate_pgid = int(raw_value)
            elif flag == "--handshake-fd":
                handshake_fd = int(raw_value)
            elif flag == "--agent-code":
                agent_code = int(raw_value)
            elif flag == "--stop-requested":
                stop_requested = raw_value in {"1", "true", "True"}
            else:
                args = [flag, raw_value, *args]
                break
        except ValueError:
            continue
    if args[:1] == ["--"]:
        args = args[1:]
    extra = {
        "escalate_pgid": escalate_pgid,
        "handshake_fd": handshake_fd,
        "agent_code": agent_code,
        "stop_requested": stop_requested,
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


def _handoff_group_escalation(
    *,
    pgid: int,
    status_fd: int | None,
    agent_code: int,
    stop_requested: bool,
    deadline: CleanupDeadline,
) -> bool:
    handshake_r, handshake_w = os.pipe()
    command = [sys.executable, "-u", str(Path(__file__).resolve())]
    pass_fds = [handshake_w]
    if status_fd is not None:
        command.extend(["--status-fd", str(status_fd)])
        pass_fds.append(status_fd)
    command.extend(
        [
            "--escalate-pgid",
            str(pgid),
            "--handshake-fd",
            str(handshake_w),
            "--agent-code",
            str(agent_code),
            "--stop-requested",
            "1" if stop_requested else "0",
        ]
    )
    try:
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
            pass_fds=tuple(pass_fds),
        )
    except OSError:
        os.close(handshake_r)
        os.close(handshake_w)
        return False
    os.close(handshake_w)
    timeout = min(_ESCALATE_HANDOFF_SECONDS, max(0.0, deadline.remaining()))
    try:
        ready, _, _ = select.select([handshake_r], [], [], timeout)
        if not ready:
            os.close(handshake_r)
            return False
        data = os.read(handshake_r, 16)
    except OSError:
        try:
            os.close(handshake_r)
        except OSError:
            pass
        return False
    try:
        os.close(handshake_r)
    except OSError:
        pass
    return data.startswith(b"READY")


def _run_escalation(
    *,
    pgid: int,
    status_fd: int | None,
    handshake_fd: int | None,
    agent_code: int,
    stop_requested: bool,
) -> int:
    if handshake_fd is not None:
        try:
            os.write(handshake_fd, b"READY\n")
        except OSError:
            pass
        try:
            os.close(handshake_fd)
        except OSError:
            pass
    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        pass
    deadline = CleanupDeadline.after(_KILL_DRAIN_SECONDS + _PS_TIMEOUT_SECONDS)
    drain = _wait_peers_gone(deadline, budget=_KILL_DRAIN_SECONDS, pgid=pgid)
    _write_status(
        status_fd,
        {
            "agent_code": agent_code,
            "drain": drain.value,
            "stop_requested": stop_requested,
        },
    )
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
            agent_code=int(extra["agent_code"]),
            stop_requested=bool(extra["stop_requested"]),
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
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_proxy_stream,
        args=(agent.stderr, stderr_dst, stop_copy),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()

    while agent.poll() is None and not stop_requested:
        event = _poll_control(_POLL_INTERVAL)
        if event in {ControlEvent.STOP, ControlEvent.EOF, ControlEvent.ERROR}:
            request_agent_stop()
            break

    cleanup_deadline = CleanupDeadline.after(JANITOR_CLEANUP_BUDGET_SECONDS)
    stop_copy.set()
    stdout_thread.join(timeout=min(_PROXY_JOIN_SECONDS, max(0.0, cleanup_deadline.remaining())))
    stderr_thread.join(timeout=min(_PROXY_JOIN_SECONDS, max(0.0, cleanup_deadline.remaining())))
    observed = agent.poll()
    drain = drain_once()
    return_code = _wait_agent(agent, cleanup_deadline)
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
    )
    if handed:
        remaining = active.remaining()
        if remaining > 0:
            time.sleep(remaining)
        _write_status(
            status_fd,
            {
                "agent_code": return_code,
                "drain": DrainResult.UNVERIFIABLE.value,
                "stop_requested": stop_requested,
            },
        )
        return 1
    _write_status(status_fd, payload)
    _abandon_group_if_unresolved(drain)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
