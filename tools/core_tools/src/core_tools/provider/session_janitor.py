"""Session-leader janitor that owns a process group until the agent tree is gone.

The janitor is spawned with ``start_new_session=True`` so its PID is the PGID.
It proxies agent stdio so descendants cannot hold Cursor's pipes open, and it
does not exit until the owned group is empty (TERM, drain, then SIGKILL peers).
"""

from __future__ import annotations

import os
import select
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

_TERM_DRAIN_SECONDS = 5.0
_KILL_DRAIN_SECONDS = 5.0
_POLL_INTERVAL = 0.05


def janitor_command(agent_argv: list[str]) -> list[str]:
    """Return argv that runs *agent_argv* under this session-leader janitor."""

    return [sys.executable, "-u", str(Path(__file__).resolve()), *agent_argv]


def _copy_stream(src: object, dst: object) -> None:
    read = getattr(src, "read", None)
    write = getattr(dst, "write", None)
    flush = getattr(dst, "flush", None)
    if read is None or write is None:
        return
    try:
        while True:
            chunk = read(8192)
            if not chunk:
                break
            write(chunk)
            if flush is not None:
                flush()
    except OSError:
        pass


def _peer_pids() -> list[int] | None:
    """Return same-group peers excluding this process, or None if listing failed."""

    me = os.getpid()
    pgid = os.getpgrp()
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,pgid="],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    peers: list[int] = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
            member_pgid = int(parts[1])
        except ValueError:
            continue
        if member_pgid == pgid and pid != me:
            peers.append(pid)
    return peers


def _signal_peers(sig: int) -> None:
    me = os.getpid()
    pgid = os.getpgrp()
    peers = _peer_pids()
    if not peers:
        return
    for pid in peers:
        if pid == me:
            continue
        try:
            if os.getpgid(pid) != pgid:
                continue
            os.kill(pid, sig)
        except OSError:
            pass


def _wait_peers_gone(timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        peers = _peer_pids()
        if peers is not None and not peers:
            return True
        time.sleep(_POLL_INTERVAL)
    peers = _peer_pids()
    return peers is not None and not peers


def _drain_group() -> None:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    _signal_peers(signal.SIGTERM)
    if _wait_peers_gone(_TERM_DRAIN_SECONDS):
        return
    _signal_peers(signal.SIGKILL)
    _wait_peers_gone(_KILL_DRAIN_SECONDS)


def _poll_stop(timeout: float) -> bool:
    try:
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
    except (OSError, ValueError):
        return False
    if not ready:
        return False
    try:
        line = sys.stdin.readline()
    except OSError:
        return False
    return line.strip() == "STOP"


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
    drained = False

    stop_requested = False

    def drain_once() -> None:
        nonlocal drained
        with drain_lock:
            if drained:
                return
            drained = True
            _drain_group()

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
        target=_copy_stream,
        args=(agent.stdout, stdout_dst),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_copy_stream,
        args=(agent.stderr, stderr_dst),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()

    while agent.poll() is None and not stop_requested:
        if _poll_stop(_POLL_INTERVAL):
            request_agent_stop()
            break

    for stream in (agent.stdout, agent.stderr):
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
    stdout_thread.join(timeout=1)
    stderr_thread.join(timeout=1)
    drain_once()
    return_code = agent.wait()
    return return_code if return_code is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
