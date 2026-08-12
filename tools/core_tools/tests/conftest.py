"""Shared pytest helpers for core_tools tests."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from core_tools.provider.cursor import _TrackedTurnProc
from core_tools.provider.process_identity import ProcessIdentity


def tracked_turn_proc(
    session_id: str,
    role: str,
    pid: int,
    *,
    proc: subprocess.Popen | None = None,
    start_time: str = "100",
    run_id: str | None = None,
) -> _TrackedTurnProc:
    return _TrackedTurnProc(
        session_id=session_id,
        role=role,
        proc=proc,
        identity=ProcessIdentity(pid=pid, start_time=start_time, run_id=run_id),
    )


def spawn_sigterm_ignoring_leader_with_child(
    tmp_path: Path,
) -> tuple[subprocess.Popen[str], int]:
    """Start a leader that ignores SIGTERM and forks a sleeping child."""

    child_pid_file = tmp_path / "child.pid"
    script = (
        "import os, signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"child_pid_file = {str(child_pid_file)!r}\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        "with open(child_pid_file, 'w', encoding='utf-8') as handle:\n"
        "    handle.write(str(child))\n"
        "time.sleep(60)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        text=True,
    )
    for _ in range(40):
        if child_pid_file.exists():
            return proc, int(child_pid_file.read_text(encoding="utf-8").strip())
        time.sleep(0.05)
    proc.kill()
    proc.wait(timeout=5)
    raise AssertionError("child PID file was not written")
