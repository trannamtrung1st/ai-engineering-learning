"""Session-leader janitor that owns a process group until the agent tree is gone.

The janitor is spawned with ``start_new_session=True`` so its PID is the PGID.
It runs the agent as a same-group child and stays alive until teardown, so
``killpg`` from the bound Popen cannot hit a reused group ID.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path


def janitor_command(agent_argv: list[str]) -> list[str]:
    """Return argv that runs *agent_argv* under this session-leader janitor."""

    return [sys.executable, str(Path(__file__).resolve()), *agent_argv]


def _teardown_group(child: subprocess.Popen[bytes] | None, *, final_kill: bool) -> None:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    try:
        os.killpg(os.getpgrp(), signal.SIGTERM)
    except OSError:
        pass
    if child is not None:
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    if not final_kill:
        return
    try:
        os.killpg(os.getpgrp(), signal.SIGKILL)
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    command = list(sys.argv[1:] if argv is None else argv)
    if not command:
        return 2
    child = subprocess.Popen(command)

    def _shutdown(_signum: int, _frame: object) -> None:
        _teardown_group(child, final_kill=True)
        raise SystemExit(child.poll() if child.poll() is not None else 1)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    return_code = child.wait()
    _teardown_group(child, final_kill=False)
    return return_code if return_code is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
