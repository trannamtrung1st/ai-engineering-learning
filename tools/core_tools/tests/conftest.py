"""Shared pytest helpers for core_tools tests."""

from __future__ import annotations

import subprocess

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
        identity=ProcessIdentity(pid=pid, start_time=start_time, run_id=run_id),
        proc=proc,
    )
