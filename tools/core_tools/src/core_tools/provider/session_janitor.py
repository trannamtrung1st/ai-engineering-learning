"""Session-leader janitor that owns a process group until the agent tree is gone.

The janitor is spawned with ``start_new_session=True`` so its PID is the PGID.
It proxies agent stdio so descendants cannot hold Cursor's external pipes, and it
does not exit successfully until the owned group is empty.
"""

from __future__ import annotations

import errno
import os
import select
import signal
import subprocess
import sys
import threading
import time
from enum import Enum
from pathlib import Path

JANITOR_EXIT_UNVERIFIABLE = 124
JANITOR_EXIT_SURVIVORS = 125

_TERM_DRAIN_SECONDS = 5.0
_KILL_DRAIN_SECONDS = 5.0
_POLL_INTERVAL = 0.05
_AGENT_WAIT_SECONDS = 2.0
_TAIL_DRAIN_SECONDS = 0.2


class DrainResult(Enum):
    CLEAN = "clean"
    UNVERIFIABLE = "unverifiable"
    SURVIVORS = "survivors"


class ControlEvent(Enum):
    TIMEOUT = "timeout"
    STOP = "stop"
    EOF = "eof"
    ERROR = "error"


def janitor_command(agent_argv: list[str]) -> list[str]:
    """Return argv that runs *agent_argv* under this session-leader janitor."""

    return [sys.executable, "-u", str(Path(__file__).resolve()), *agent_argv]


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


def _ps_peer_pids(pgid: int, me: int) -> list[int] | None:
    read_fd, write_fd = os.pipe()
    try:
        helper_pid = os.fork()
    except OSError:
        os.close(read_fd)
        os.close(write_fd)
        return None
    if helper_pid == 0:
        os.close(read_fd)
        try:
            os.setsid()
        except OSError:
            os._exit(127)
        os.dup2(write_fd, 1)
        os.close(write_fd)
        try:
            os.execvp("ps", ["ps", "-axo", "pid=,pgid="])
        except OSError:
            os._exit(127)
        os._exit(127)
    os.close(write_fd)
    chunks: list[bytes] = []
    try:
        while True:
            data = os.read(read_fd, 65536)
            if not data:
                break
            chunks.append(data)
    except OSError:
        chunks = []
    finally:
        os.close(read_fd)
    _, status = os.waitpid(helper_pid, 0)
    if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
        return None
    text = b"".join(chunks).decode("utf-8", errors="replace")
    peers: list[int] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2:
            return None
        try:
            pid = int(parts[0])
            member_pgid = int(parts[1])
        except ValueError:
            return None
        if pid in {me, helper_pid}:
            continue
        if member_pgid == pgid:
            peers.append(pid)
    return _confirmed_peers(peers, pgid, me)


def _confirmed_peers(candidates: list[int], pgid: int, me: int) -> list[int]:
    peers: list[int] = []
    for pid in candidates:
        if pid == me:
            continue
        try:
            if os.getpgid(pid) != pgid:
                continue
        except OSError:
            continue
        peers.append(pid)
    return peers


def _peer_pids() -> list[int] | None:
    """Return same-group peers excluding this process, or None if listing failed."""

    mode = os.environ.get("CORE_TOOLS_JANITOR_PEERS")
    if mode in {"unreadable", "malformed"}:
        return None
    if mode == "empty":
        return []

    me = os.getpid()
    pgid = os.getpgrp()
    if sys.platform.startswith("linux") and os.path.isdir("/proc"):
        return _linux_peer_pids(pgid, me)
    return _ps_peer_pids(pgid, me)


def _signal_group(sig: int) -> None:
    try:
        os.killpg(os.getpgrp(), sig)
    except OSError:
        pass


def _escalate_kill_group() -> None:
    pgid = os.getpgrp()
    helper = (
        "import os, signal, sys\n"
        f"os.killpg({pgid}, signal.SIGKILL)\n"
    )
    try:
        subprocess.Popen(
            [sys.executable, "-c", helper],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass
    deadline = time.monotonic() + _KILL_DRAIN_SECONDS
    while time.monotonic() < deadline:
        time.sleep(_POLL_INTERVAL)


def _wait_peers_gone(timeout: float) -> DrainResult:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        peers = _peer_pids()
        if peers is None:
            return DrainResult.UNVERIFIABLE
        if not peers:
            return DrainResult.CLEAN
        time.sleep(_POLL_INTERVAL)
    peers = _peer_pids()
    if peers is None:
        return DrainResult.UNVERIFIABLE
    if not peers:
        return DrainResult.CLEAN
    return DrainResult.SURVIVORS


def _drain_group() -> DrainResult:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    _signal_group(signal.SIGTERM)
    result = _wait_peers_gone(_TERM_DRAIN_SECONDS)
    if result is DrainResult.CLEAN:
        return result
    if result is DrainResult.UNVERIFIABLE:
        return result
    _escalate_kill_group()
    return _wait_peers_gone(_KILL_DRAIN_SECONDS)


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


def _exit_for_drain(agent_code: int, drain: DrainResult) -> int:
    if drain is DrainResult.UNVERIFIABLE:
        return JANITOR_EXIT_UNVERIFIABLE
    if drain is DrainResult.SURVIVORS:
        return JANITOR_EXIT_SURVIVORS
    return agent_code if agent_code is not None else 1


def main(argv: list[str] | None = None) -> int:
    command = list(sys.argv[1:] if argv is None else argv)
    if not command:
        return 2

    agent = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    drain_lock = threading.Lock()
    drained: DrainResult | None = None
    stop_requested = False
    stop_copy = threading.Event()

    def drain_once() -> DrainResult:
        nonlocal drained
        with drain_lock:
            if drained is not None:
                return drained
            drained = _drain_group()
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

    stop_copy.set()
    if agent.stdout is not None:
        _copy_available(agent.stdout.fileno(), stdout_dst, _TAIL_DRAIN_SECONDS)
    if agent.stderr is not None:
        _copy_available(agent.stderr.fileno(), stderr_dst, _TAIL_DRAIN_SECONDS)
    stdout_thread.join(timeout=1)
    stderr_thread.join(timeout=1)
    observed = agent.poll()
    drain = drain_once()
    try:
        return_code = agent.wait(timeout=_AGENT_WAIT_SECONDS)
    except subprocess.TimeoutExpired:
        return_code = agent.poll()
        if return_code is None:
            return_code = 1
    if observed == 0:
        return_code = 0
    elif (
        return_code is not None
        and return_code < 0
        and drain is DrainResult.CLEAN
    ):
        return_code = 0
    for stream in (agent.stdout, agent.stderr):
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
    return _exit_for_drain(return_code, drain)


if __name__ == "__main__":
    raise SystemExit(main())
