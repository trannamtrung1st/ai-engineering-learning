"""CursorProvider session tracking migration and concurrency (S5-RR5-001/002/005)."""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.cursor import CursorProvider
from core_tools.provider.errors import ProviderSessionTerminationError
from core_tools.provider.process_identity import TerminateIdentityResult
from tests.conftest import tracked_turn_proc


def test_durable_migration_retags_tracked_pid(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=lambda argv, cwd: iter(()),
        binary=str(agent_path),
        skip_probe=True,
    )
    pending_id = provider.start_primary_session("planner", {"goal": "x"})
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=sys.platform != "win32",
    )
    provider._tracked_turn_procs[proc.pid] = tracked_turn_proc(
        pending_id,
        "planner",
        proc.pid,
        proc=proc,
    )
    durable_id = "chat-planner-1"

    migrated = provider._maybe_migrate_session(pending_id, durable_id)

    assert migrated == durable_id
    assert provider._tracked_turn_procs[proc.pid].session_id == durable_id
    assert provider._tracked_turn_procs[proc.pid].role == "planner"
    with patch(
        "core_tools.provider.cursor.terminate_verified_process_identity",
        return_value=TerminateIdentityResult.FAILED,
    ):
        with pytest.raises(ProviderSessionTerminationError) as exc_info:
            provider.terminate_session(durable_id)
    assert proc.pid in exc_info.value.surviving_pids
    proc.kill()
    proc.wait(timeout=5)


def test_durable_migration_does_not_retag_other_session_pids(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=lambda argv, cwd: iter(()),
        binary=str(agent_path),
        skip_probe=True,
    )
    pending_a = provider.start_primary_session("planner", {"goal": "a"})
    pending_b = provider.start_primary_session("producer", {"goal": "b"})
    provider._tracked_turn_procs[101] = tracked_turn_proc(pending_a, "planner", 101)
    provider._tracked_turn_procs[202] = tracked_turn_proc(pending_b, "producer", 202)

    provider._maybe_migrate_session(pending_a, "chat-planner-1")

    assert provider._tracked_turn_procs[101].session_id == "chat-planner-1"
    assert provider._tracked_turn_procs[202].session_id == pending_b


def test_failure_record_ignored_when_pid_already_dead(tmp_path: Path) -> None:
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
    records = [{"pid": 4242, "reason": "termination_failed"}]

    with patch("core_tools.provider.cursor.is_pid_alive", return_value=False):
        surviving = provider._surviving_pids_for_session(session_id, records)

    assert surviving == ()


def test_concurrent_collect_contexts_track_distinct_pids(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=lambda argv, cwd: iter(()),
        binary=str(agent_path),
        skip_probe=True,
    )
    session_a = provider.start_primary_session("planner", {"goal": "a"})
    session_b = provider.start_primary_session("producer", {"goal": "b"})
    barrier = threading.Barrier(2)
    tracked: dict[str, int] = {}
    procs: list[subprocess.Popen[bytes]] = []

    def track(session_id: str, role: str, key: str) -> None:
        provider._set_collect_context(session_id, role)
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=sys.platform != "win32",
        )
        procs.append(proc)
        provider._register_tracked_turn_proc(proc)
        barrier.wait(timeout=0.5)
        context = provider._get_collect_context()
        assert context == (session_id, role)
        tracked[key] = proc.pid
        provider._clear_collect_context()

    thread_a = threading.Thread(target=track, args=(session_a, "planner", "a"))
    thread_b = threading.Thread(target=track, args=(session_b, "producer", "b"))
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=0.5)
    thread_b.join(timeout=0.5)

    assert tracked["a"] != tracked["b"]
    assert provider._tracked_turn_procs[tracked["a"]].session_id == session_a
    assert provider._tracked_turn_procs[tracked["b"]].session_id == session_b

    provider.terminate_session(session_a)

    assert session_a not in provider._sessions
    assert provider._tracked_turn_procs[tracked["b"]].session_id == session_b
    for proc in procs:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
