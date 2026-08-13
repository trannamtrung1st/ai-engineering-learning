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

JANITOR_CLEANUP_BUDGET_SECONDS = (
    2 * _PROXY_JOIN_SECONDS
    + _TERM_DRAIN_SECONDS
    + _KILL_DRAIN_SECONDS
    + 2 * _AGENT_WAIT_SECONDS
    + _TAIL_DRAIN_SECONDS
    + 2 * _PS_TIMEOUT_SECONDS
)
JANITOR_PARENT_WAIT_SECONDS = JANITOR_CLEANUP_BUDGET_SECONDS + _PARENT_WAIT_MARGIN_SECONDS


@dataclass(frozen=True)
class CleanupDeadline:
    """Absolute monotonic deadline for janitor tree cleanup."""

    end: float

    @classmethod
    def after(cls, seconds: float) -> CleanupDeadline:
        return cls(time.monotonic() + max(0.0, seconds))

    def remaining(self) -> float:
        return max(0.0, self.end - time.monotonic())


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


def _linux_peer_pids(pgid: int, me: int) -> list[int] | None:
    proc_root = "/proc"
    try:
        entries = os.listdir(proc_root)
    except OSError:
        return None
    peers: list[int] = []
    for entry in entries:
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid == me:
            continue
        try:
            with open(os.path.join(proc_root, entry, "stat"), encoding="utf-8") as handle:
                text = handle.read()
        except OSError:
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
    return _confirmed_peers(peers, pgid, me)


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
    return _confirmed_peers(peers, pgid, me)


def _confirmed_peers(candidates: list[int], pgid: int, me: int) -> list[int] | None:
    peers: list[int] = []
    for pid in candidates:
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


def _peer_pids(deadline: CleanupDeadline | None = None) -> list[int] | None:
    """Return same-group peers excluding this process, or None if listing failed."""

    if deadline is not None and deadline.remaining() <= 0:
        return None
    me = os.getpid()
    pgid = os.getpgrp()
    if sys.platform.startswith("linux") and os.path.isdir("/proc"):
        return _linux_peer_pids(pgid, me)
    return _ps_peer_pids(pgid, me, deadline=deadline)


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


def _wait_peers_gone(deadline: CleanupDeadline, *, budget: float) -> DrainResult:
    phase_end = time.monotonic() + min(max(0.0, budget), deadline.remaining())
    last: DrainResult = DrainResult.SURVIVORS
    while time.monotonic() < phase_end and deadline.remaining() > 0:
        peers = _peer_pids(deadline)
        if peers is None:
            return DrainResult.UNVERIFIABLE
        if not peers:
            return DrainResult.CLEAN
        last = DrainResult.SURVIVORS
        time.sleep(min(_POLL_INTERVAL, deadline.remaining()))
    peers = _peer_pids(deadline)
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
        if deadline.remaining() <= 0:
            return result
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


def _parse_argv(argv: list[str]) -> tuple[int | None, list[str]]:
    args = list(argv)
    status_fd: int | None = None
    if len(args) >= 2 and args[0] == "--status-fd":
        try:
            status_fd = int(args[1])
        except ValueError:
            status_fd = None
        args = args[2:]
    if args[:1] == ["--"]:
        args = args[1:]
    return status_fd, args


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


def main(
    argv: list[str] | None = None,
    *,
    status_fd: int | None = None,
) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    parsed_fd, command = _parse_argv(raw)
    if status_fd is None:
        status_fd = parsed_fd
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
    _write_status(status_fd, payload)
    for stream in (agent.stdout, agent.stderr):
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
    _abandon_group_if_unresolved(drain)
    if drain is DrainResult.CLEAN:
        return 0 if stop_requested and return_code < 0 else return_code
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
