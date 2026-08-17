"""Slice 5 rereview 084505: EOF vs janitor, drain cap, zombie reap, identity generation."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.cursor import (
    CursorProvider,
    _MAX_IDLE_RESCUE_BYTES,
    _SubprocessStdoutIterator,
    _TrackedTurnProc,
)
from core_tools.provider.errors import (
    ProviderLifecycleTimeoutError,
    ProviderSessionTerminationError,
    ProviderStreamRecordTooLargeError,
)
from core_tools.provider.process_cleanup import (
    ProcessGroupState,
    is_pid_alive,
    is_pid_reaped,
    terminate_process_tree,
)
from core_tools.provider.process_identity import ProcessIdentity
from tests.conftest import tracked_turn_proc


def _idle_config(idle: float) -> dict:
    return {
        "limits": {
            "provider": {
                "turn_idle_timeout_seconds": idle,
                "max_retries_per_call": 0,
            }
        }
    }


def _provider(tmp_path: Path, runner=None, idle: float = 0.08) -> CursorProvider:
    agent = tmp_path / "agent"
    agent.write_text("", encoding="utf-8")
    return CursorProvider(
        _idle_config(idle),
        workspace=tmp_path,
        runner=runner or (lambda argv, cwd: iter(())),
        binary=str(agent),
        skip_probe=True,
    )


def _system_init(session_id: str) -> str:
    return json.dumps({"type": "system", "subtype": "init", "session_id": session_id})


def _assistant(text: str) -> str:
    return json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}
    )


def _script_runner(script: str):
    def runner(argv: list[str], cwd: Path):
        del argv
        return _SubprocessStdoutIterator([sys.executable, "-c", script], cwd)

    return runner


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout")
def test_newline_free_flood_terminates_within_rescue_cap(tmp_path: Path) -> None:
    script = (
        "import os, sys, time\n"
        "os.write(1, b'x' * (512 * 1024))\n"
        "sys.stdout.flush()\n"
        "time.sleep(60)\n"
    )
    iterator = _SubprocessStdoutIterator([sys.executable, "-c", script], tmp_path)
    try:
        started = time.monotonic()
        with pytest.raises(ProviderStreamRecordTooLargeError):
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                iterator.read_nonempty_line(0.05)
        assert time.monotonic() - started < 1.2
        assert len(iterator._stdout_buf) <= _MAX_IDLE_RESCUE_BYTES + 65536
    finally:
        terminate_process_tree(iterator._proc)
        iterator.close()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout")
def test_legitimate_64kib_record_still_succeeds(tmp_path: Path) -> None:
    blob = "y" * 65536
    payload = _assistant(blob)
    script = (
        "import sys\n"
        f"sys.stdout.write({_system_init('chat-64k-ok')!r} + '\\n' + {payload!r} + '\\n')\n"
        "sys.stdout.flush()\n"
    )
    iterator = _SubprocessStdoutIterator([sys.executable, "-c", script], tmp_path)
    try:
        first = iterator.read_nonempty_line(1.0)
        second = iterator.read_nonempty_line(1.0)
        assert first is not None
        assert second is not None
        assert blob[:32] in second
    finally:
        iterator.close()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process table")
def test_zombie_is_not_alive_until_reaped() -> None:
    script = (
        "import os, sys\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    os._exit(0)\n"
        "sys.stdout.write(str(child) + '\\n')\n"
        "sys.stdout.flush()\n"
        "sys.stdin.readline()\n"
        "os.waitpid(child, 0)\n"
        "sys.stdout.write('reaped\\n')\n"
        "sys.stdout.flush()\n"
    )
    helper = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        assert helper.stdout is not None
        line = helper.stdout.readline()
        child = int(line.strip())
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and is_pid_alive(child):
            time.sleep(0.01)
        assert is_pid_alive(child) is False
        assert is_pid_reaped(child) is False
        assert helper.stdin is not None
        helper.stdin.write("\n")
        helper.stdin.flush()
        reaped_line = helper.stdout.readline()
        assert reaped_line.strip() == "reaped"
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and not is_pid_reaped(child):
            time.sleep(0.01)
        assert is_pid_reaped(child) is True
    finally:
        helper.kill()
        helper.wait(timeout=2)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX Cursor adapter")
def test_identity_enrichment_does_not_overwrite_replaced_generation(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    provider._set_collect_context(session_id, "planner")
    blocked = threading.Event()
    proceed = threading.Event()

    class FakeProc:
        def __init__(self, marker: str) -> None:
            self.pid = 4242
            self.marker = marker

        def poll(self) -> int | None:
            return None

    old_proc = FakeProc("old")
    new_proc = FakeProc("new")
    provider._register_tracked_turn_proc(old_proc, timeout=0)  # type: ignore[arg-type]
    old_generation = provider._tracked_turn_procs[4242].generation

    def slow_identity(pid, **kwargs):
        del pid, kwargs
        blocked.set()
        proceed.wait(timeout=2.0)
        return ProcessIdentity(pid=4242, start_time="old")

    with patch(
        "core_tools.provider.cursor.read_process_identity",
        side_effect=slow_identity,
    ), patch(
        "core_tools.provider.cursor.is_pid_alive",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.read_process_group_id",
        return_value=None,
    ), patch(
        "core_tools.provider.cursor.capture_process_group_identities",
        return_value=[],
    ):
        enricher = threading.Thread(
            target=provider._enrich_tracked_turn_proc,
            args=(old_proc,),
            daemon=True,
        )
        enricher.start()
        assert blocked.wait(timeout=1.0)
        provider._register_tracked_turn_proc(new_proc, timeout=0)  # type: ignore[arg-type]
        new_entry = provider._tracked_turn_procs[4242]
        assert new_entry.proc is new_proc
        assert new_entry.generation != old_generation
        proceed.set()
        enricher.join(timeout=1.0)
        current = provider._tracked_turn_procs[4242]
        assert current.proc is new_proc
        assert current.identity is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX Cursor adapter")
def test_no_cursor_track_identity_thread_after_completed_turn(tmp_path: Path) -> None:
    script = (
        "import json, sys\n"
        f"print({_system_init('chat-done')!r}, flush=True)\n"
        f"print({_assistant('ok')!r}, flush=True)\n"
    )
    provider = _provider(tmp_path, _script_runner(script), idle=1.0)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    list(provider.stream_events(session_id))
    assert [
        item.name
        for item in threading.enumerate()
        if item.name == "cursor-track-identity"
    ] == []


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX Cursor adapter")
def test_janitor_cleanup_after_output_does_not_idle_stall(tmp_path: Path) -> None:
    init = _system_init("chat-janitor-eof")
    payload = _assistant("ready")
    script = (
        "import sys\n"
        f"print({init!r}, flush=True)\n"
        f"print({payload!r}, flush=True)\n"
    )
    provider = _provider(tmp_path, _script_runner(script), idle=0.08)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    events = list(provider.stream_events(session_id))
    texts = [str(event.get("text") or "") for event in events]
    assert any("ready" in text for text in texts)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_unexpected_janitor_exit_after_late_child_reaps_or_fail_closes(
    tmp_path: Path,
) -> None:
    child_pid_file = tmp_path / "child.pid"
    script = (
        "import json, os, sys, time\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        f"open({str(child_pid_file)!r}, 'w', encoding='utf-8').write(str(child))\n"
        "print(json.dumps({'type': 'system', 'subtype': 'init', 'session_id': 'chat-leader'}), flush=True)\n"
        "print(json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'ok'}]}}), flush=True)\n"
        "time.sleep(60)\n"
    )
    provider = _provider(tmp_path, _script_runner(script), idle=5.0)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    events: list[dict] = []

    def collect() -> None:
        for event in provider.stream_events(session_id):
            events.append(event)
            if len(events) >= 1:
                break

    thread = threading.Thread(target=collect, daemon=True)
    child_pid = None
    try:
        thread.start()
        for _ in range(40):
            if child_pid_file.exists():
                child_pid = int(child_pid_file.read_text(encoding="utf-8").strip())
                break
            time.sleep(0.05)
        assert child_pid is not None
        tracked = next(iter(provider._tracked_turn_procs.values()), None)
        assert tracked is not None and tracked.proc is not None
        os.kill(tracked.proc.pid, signal.SIGKILL)
        released = False
        try:
            provider.terminate_session(session_id)
            released = True
        except (ProviderSessionTerminationError, ProviderLifecycleTimeoutError):
            released = False
        if released:
            assert is_pid_alive(child_pid) is False
        else:
            bound = provider.canonical_session_id(session_id)
            assert bound in provider._sessions or session_id in provider._sessions
    finally:
        thread.join(timeout=2.0)
        if child_pid is not None and is_pid_alive(child_pid):
            os.kill(child_pid, signal.SIGKILL)
        for entry in list(provider._tracked_turn_procs.values()):
            if entry.proc is not None:
                terminate_process_tree(entry.proc)


def test_raw_pgid_live_without_trusted_identity_releases_session(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    leader = ProcessIdentity(pid=4242, start_time="100")
    provider._tracked_turn_procs[4242] = tracked_turn_proc(session_id, "planner", 4242)
    provider._tracked_turn_procs[4242].identity = leader
    provider._tracked_turn_procs[4242].pgid = 4242
    provider._tracked_turn_procs[4242].member_identities = (leader,)
    provider._tracked_turn_procs[4242].proc = None
    provider._tracked_turn_procs[4242].group_observed_gone = True
    with patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ):
        assert provider._tracked_tree_is_live(provider._tracked_turn_procs[4242]) is False
        provider.terminate_session(session_id)
    assert session_id not in provider._sessions
