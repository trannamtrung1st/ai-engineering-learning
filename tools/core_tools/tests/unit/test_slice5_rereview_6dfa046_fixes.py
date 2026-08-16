"""Slice 5 rereview 6dfa046: idle-first tracking, multi-chunk drain, identity-safe liveness."""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.cursor import (
    CursorProvider,
    _SubprocessStdoutIterator,
    _TrackedTurnProc,
)
from core_tools.provider.errors import ProviderSessionTerminationError
from core_tools.provider.process_cleanup import (
    ProcessGroupState,
    is_pid_alive,
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


def _provider(tmp_path: Path, runner=None) -> CursorProvider:
    agent = tmp_path / "agent"
    agent.write_text("", encoding="utf-8")
    return CursorProvider(
        _idle_config(0.08),
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


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout")
@pytest.mark.parametrize("size", [4095, 4096, 4097, 8192, 16384])
def test_zero_budget_drains_all_readable_bytes(tmp_path: Path, size: int) -> None:
    blob = "x" * size
    payload = _assistant(blob)
    script = (
        "import sys, time\n"
        f"sys.stdout.write({_system_init('chat-drain')!r} + '\\n' + {payload!r})\n"
        "sys.stdout.flush()\n"
        "time.sleep(60)\n"
    )
    iterator = _SubprocessStdoutIterator([sys.executable, "-c", script], tmp_path)
    try:
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if iterator.wait_readable(0.05):
                break
        assert iterator.wait_readable(0.0) is True
        first = iterator._pop_complete_line()
        assert first is not None
        assert iterator.wait_readable(0.0) is True
        second = iterator._pop_complete_line()
        assert second is not None
        assert blob[:32] in second
        assert len(second) >= size
    finally:
        terminate_process_tree(iterator._proc)
        iterator.close()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout")
def test_exited_process_preserves_64kib_final_line(tmp_path: Path) -> None:
    blob = "y" * 65536
    payload = _assistant(blob)
    script = (
        "import sys\n"
        f"sys.stdout.write({_system_init('chat-64k')!r} + '\\n' + {payload!r})\n"
        "sys.stdout.flush()\n"
    )
    iterator = _SubprocessStdoutIterator([sys.executable, "-c", script], tmp_path)
    try:
        iterator._proc.wait(timeout=2)
        assert iterator.wait_readable(0.0) is True
        iterator._pop_complete_line()
        assert iterator.wait_readable(0.0) is True
        second = iterator._pop_complete_line()
        assert second is not None
        assert blob[:32] in second
    finally:
        iterator.close()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout")
def test_zero_budget_preserves_multiple_buffered_lines(tmp_path: Path) -> None:
    lines = [_system_init("chat-multi"), _assistant("one"), _assistant("two")]
    script = (
        "import sys, time\n"
        f"sys.stdout.write({repr(chr(10).join(lines))})\n"
        "sys.stdout.flush()\n"
        "time.sleep(60)\n"
    )
    iterator = _SubprocessStdoutIterator([sys.executable, "-c", script], tmp_path)
    try:
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and not iterator.wait_readable(0.05):
            pass
        popped = []
        for _ in range(3):
            assert iterator.wait_readable(0.0) is True
            line = iterator._pop_complete_line()
            assert line is not None
            popped.append(line)
        assert "one" in popped[1]
        assert "two" in popped[2]
    finally:
        terminate_process_tree(iterator._proc)
        iterator.close()


def test_identity_bookkeeping_does_not_block_first_stdout(tmp_path: Path) -> None:
    init = _system_init("chat-first")
    payload = _assistant("ready")
    script = (
        "import sys\n"
        f"print({init!r}, flush=True)\n"
        f"print({payload!r}, flush=True)\n"
    )

    def runner(argv: list[str], cwd: Path):
        del argv
        return _SubprocessStdoutIterator([sys.executable, "-c", script], cwd)

    def slow_identity(pid, run_id=None, command=None, timeout=None):
        del pid, run_id, command, timeout
        time.sleep(0.2)
        return ProcessIdentity(pid=1, start_time="1")

    provider = _provider(tmp_path, runner)
    with patch(
        "core_tools.provider.cursor.read_process_identity",
        side_effect=slow_identity,
    ), patch(
        "core_tools.provider.cursor.terminate_process_tree",
        return_value=True,
    ):
        session_id = provider.start_primary_session("planner", {"goal": "x"})
        started = time.monotonic()
        stream = provider.stream_events(session_id)
        first = next(stream)
        first_event_at = time.monotonic() - started
        events = [first, *list(stream)]
    assert first_event_at < 0.18
    texts = [str(event.get("text") or "") for event in events]
    assert any("ready" in text for text in texts)


def test_reused_live_pgid_is_not_owned_after_group_gone(tmp_path: Path) -> None:
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
    ), patch(
        "core_tools.provider.cursor.terminate_verified_process_identity",
        return_value=__import__(
            "core_tools.provider.process_identity",
            fromlist=["TerminateIdentityResult"],
        ).TerminateIdentityResult.ALREADY_GONE,
    ):
        assert provider._tracked_tree_is_live(provider._tracked_turn_procs[4242]) is False
        provider.terminate_session(session_id)
        assert session_id not in provider._sessions
        provider.terminate_all_sessions()
        assert provider.list_active_sessions() == []


def test_live_pgid_without_trusted_identity_is_consistent_across_teardown_apis(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    leader = ProcessIdentity(pid=4242, start_time="100")
    provider._tracked_turn_procs[4242] = tracked_turn_proc(session_id, "planner", 4242)
    provider._tracked_turn_procs[4242].identity = leader
    provider._tracked_turn_procs[4242].pgid = 4242
    provider._tracked_turn_procs[4242].member_identities = (leader,)
    provider._tracked_turn_procs[4242].proc = None

    with patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ), patch(
        "core_tools.provider.cursor.terminate_verified_process_identity",
        return_value=__import__(
            "core_tools.provider.process_identity",
            fromlist=["TerminateIdentityResult"],
        ).TerminateIdentityResult.ALREADY_GONE,
    ):
        assert provider._surviving_pids_for_session(session_id, []) == ()
        assert provider._tracked_tree_is_live(provider._tracked_turn_procs[4242]) is True
        with pytest.raises(ProviderSessionTerminationError, match="unresolved"):
            provider.terminate_session(session_id)
        assert session_id in provider._sessions
        leftover = provider.terminate_all_sessions()
        del leftover
        assert any(
            session["session_id"] == session_id
            for session in provider.list_active_sessions()
        )


def test_unverifiable_group_without_trusted_identity_stays_owned(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    provider._tracked_turn_procs[4242] = _TrackedTurnProc(
        session_id=session_id,
        role="planner",
        proc=None,
        identity=None,
        pgid=4242,
        member_identities=None,
    )

    with patch(
        "core_tools.provider.cursor.process_group_state",
        return_value=ProcessGroupState.UNVERIFIABLE,
    ), patch(
        "core_tools.provider.cursor.terminate_verified_process_identity",
        return_value=__import__(
            "core_tools.provider.process_identity",
            fromlist=["TerminateIdentityResult"],
        ).TerminateIdentityResult.ALREADY_GONE,
    ):
        assert provider._tracked_tree_is_live(provider._tracked_turn_procs[4242]) is True
        with pytest.raises(ProviderSessionTerminationError, match="unresolved"):
            provider.terminate_session(session_id)
        assert session_id in provider._sessions


@pytest.mark.skipif(sys.platform == "win32", reason="process groups differ on Windows")
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_late_janitor_child_is_reaped_or_fail_closed(tmp_path: Path) -> None:
    child_pid_file = tmp_path / "child.pid"
    script = (
        "import json, os, sys, time\n"
        "time.sleep(0.08)\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        f"open({str(child_pid_file)!r}, 'w', encoding='utf-8').write(str(child))\n"
        "print(json.dumps({'type': 'system', 'subtype': 'init', 'session_id': 'chat-late'}), flush=True)\n"
        "print(json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'ok'}]}}), flush=True)\n"
        "time.sleep(60)\n"
    )

    def runner(argv: list[str], cwd: Path):
        del argv
        return _SubprocessStdoutIterator([sys.executable, "-c", script], cwd)

    (tmp_path / "agent").write_text("", encoding="utf-8")
    provider = CursorProvider(
        _idle_config(5.0),
        workspace=tmp_path,
        runner=runner,
        binary=str(tmp_path / "agent"),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    events: list[dict] = []
    error: list[BaseException] = []

    def collect() -> None:
        try:
            for event in provider.stream_events(session_id):
                events.append(event)
                if len(events) >= 1:
                    break
        except BaseException as exc:
            error.append(exc)

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
        os.kill(child_pid, 0)
        released = False
        try:
            provider.terminate_session(session_id)
            released = True
        except ProviderSessionTerminationError:
            released = False
        if released:
            assert is_pid_alive(child_pid) is False
        else:
            assert session_id in provider._sessions
    finally:
        thread.join(timeout=2.0)
        if child_pid is not None and is_pid_alive(child_pid):
            os.kill(child_pid, signal.SIGKILL)
        for entry in list(provider._tracked_turn_procs.values()):
            proc = entry.proc
            if proc is not None:
                terminate_process_tree(proc)
