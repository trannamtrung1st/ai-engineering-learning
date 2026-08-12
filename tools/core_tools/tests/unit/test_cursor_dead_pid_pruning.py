"""CursorProvider dead PID pruning (S5-RR6-001)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from core_tools.provider.cursor import CursorProvider


def test_terminate_session_removes_stale_tracked_pid_when_process_already_dead(
    tmp_path: Path,
) -> None:
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
    stale_pid = 9090
    provider._tracked_turn_procs[stale_pid] = (session_id, "planner")

    with patch("core_tools.provider.cursor.is_pid_alive", return_value=False):
        with patch("core_tools.provider.cursor.terminate_pid_tree", return_value=False):
            provider.terminate_session(session_id)

    assert stale_pid not in provider._tracked_turn_procs
