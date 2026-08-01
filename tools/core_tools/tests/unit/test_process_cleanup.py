"""Unit tests for provider subprocess cleanup."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from core_tools.provider.cursor import CursorProvider
from core_tools.provider.process_cleanup import terminate_process_tree
from core_tools.provider.stub import StubProvider


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
def test_terminate_process_tree_kills_child_process() -> None:
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import os, signal, time; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "os.setpgrp(); "
                "child = os.fork() or (time.sleep(60), os._exit(0))[1]; "
                "time.sleep(60)"
            ),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    time.sleep(0.1)
    terminate_process_tree(proc)
    assert proc.poll() is not None


def test_cursor_provider_terminate_all_sessions_kills_tracked_turn(tmp_path: Path) -> None:
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
    provider._tracked_turn_procs[proc.pid] = ("cursor-session-1", "planner")

    terminated = provider.terminate_all_sessions()

    assert proc.poll() is not None
    assert not provider._tracked_turn_procs
    assert any(record.get("pid") == proc.pid for record in terminated)


def test_stub_provider_list_active_sessions() -> None:
    provider = StubProvider()
    provider.script_turn([{"type": "done", "subtype": "success", "text": "ok"}])
    session_id = provider.start_primary_session("planner", {"goal": "x"})

    active = provider.list_active_sessions()

    assert active == [
        {
            "session_id": session_id,
            "role": "planner",
            "kind": "primary",
            "model": "auto",
        },
    ]


def test_stub_provider_terminate_all_sessions_clears_sessions() -> None:
    provider = StubProvider()
    provider.script_turn([{"type": "done", "subtype": "success", "text": "ok"}])
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    assert provider.get_session_reference(session_id)["session_id"] == session_id

    provider.terminate_all_sessions()

    with pytest.raises(Exception):
        provider.get_session_reference(session_id)
