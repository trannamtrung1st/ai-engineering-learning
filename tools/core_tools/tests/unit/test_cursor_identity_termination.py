"""Cursor provider identity-safe tracked-process termination (S5-RR9-001)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.cursor import CursorProvider, _TrackedTurnProc
from core_tools.provider.process_identity import (
    ProcessIdentity,
    TerminateIdentityResult,
)


def _tracked(
    session_id: str,
    role: str,
    proc: subprocess.Popen[bytes],
) -> _TrackedTurnProc:
    return _TrackedTurnProc(
        session_id=session_id,
        role=role,
        proc=proc,  # type: ignore[arg-type]
        identity=ProcessIdentity(pid=proc.pid, start_time="100"),
    )


def test_cursor_terminate_tracked_proc_uses_bound_popen(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=lambda argv, cwd: iter(()),
        binary=str(agent_path),
        skip_probe=True,
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=sys.platform != "win32",
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    provider._tracked_turn_procs[proc.pid] = _tracked(session_id, "planner", proc)

    try:
        with patch(
            "core_tools.provider.cursor.terminate_verified_process_identity",
            return_value=TerminateIdentityResult.TERMINATED,
        ) as terminate:
            records = provider._terminate_tracked_turn_procs()

        assert records[0]["reason"] == "terminated"
        assert records[0]["process_identity"] == f"{proc.pid}:100"
        terminate.assert_called_once()
        assert terminate.call_args.kwargs["proc"] is proc
        assert proc.pid not in provider._tracked_turn_procs
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_cursor_terminate_tracked_proc_does_not_signal_pid_reuse(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=lambda argv, cwd: iter(()),
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    stale_identity = ProcessIdentity(pid=4242, start_time="100")
    provider._tracked_turn_procs[4242] = _TrackedTurnProc(
        session_id=session_id,
        role="planner",
        proc=None,
        identity=stale_identity,
    )

    with patch(
        "core_tools.provider.cursor.is_pid_alive",
        return_value=True,
    ):
        with patch(
            "core_tools.provider.cursor.terminate_verified_process_identity",
            return_value=TerminateIdentityResult.IDENTITY_MISMATCH,
        ) as terminate:
            records = provider._terminate_tracked_turn_procs()

    assert records == []
    terminate.assert_called_once_with(
        stale_identity,
        proc=None,
        pgid=None,
        member_identities=None,
        timeout=None,
    )
    assert 4242 not in provider._tracked_turn_procs


def test_cursor_failed_termination_record_carries_original_identity(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=lambda argv, cwd: iter(()),
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    identity = ProcessIdentity(pid=4242, start_time="100")
    provider._tracked_turn_procs[4242] = _TrackedTurnProc(
        session_id=session_id,
        role="planner",
        proc=None,
        identity=identity,
    )

    with patch(
        "core_tools.provider.cursor.is_pid_alive",
        return_value=True,
    ):
        with patch(
            "core_tools.provider.cursor.terminate_verified_process_identity",
            return_value=TerminateIdentityResult.FAILED,
        ):
            records = provider._terminate_tracked_turn_procs()

    assert records == [
        {
            "pid": 4242,
            "role": "planner",
            "session_id": session_id,
            "tree_status": "unresolved",
            "member_pids": [4242],
            "member_identities": ["4242:100"],
            "start_time": "100",
            "process_identity": "4242:100",
            "run_id": None,
            "reason": "termination_failed",
        }
    ]
