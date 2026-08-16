"""Slice 5 rereview 992f5a0: framing, cleanup budget, waitpid ownership, PGID fail-closed."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.cursor import (
    CursorProvider,
    _SubprocessStdoutIterator,
)
from core_tools.provider.errors import ProviderStreamRecordTooLargeError
from core_tools.provider.process_cleanup import (
    ProcessGroupState,
    terminate_process_tree,
)
from core_tools.provider.process_identity import (
    ProcessIdentity,
    _fallback_kill_bound_janitor_group,
)
from core_tools.provider.session_janitor import DrainResult
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


def _provider(tmp_path: Path, runner=None, idle: float = 0.0) -> CursorProvider:
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


def _result() -> str:
    return json.dumps({"type": "result", "subtype": "success", "result": "ok"})


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout")
def test_partial_json_without_newline_is_not_promoted_while_process_lives(
    tmp_path: Path,
) -> None:
    script = (
        "import sys, time\n"
        "sys.stdout.write('{\"type\":\"assistant\"')\n"
        "sys.stdout.flush()\n"
        "time.sleep(60)\n"
    )
    iterator = _SubprocessStdoutIterator([sys.executable, "-c", script], tmp_path)
    try:
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if iterator.wait_readable(0.05):
                break
        assert iterator.read_nonempty_line(0.0) is None
        assert b"\n" not in iterator._stdout_buf
        assert iterator._proc.poll() is None
    finally:
        terminate_process_tree(iterator._proc)
        iterator.close()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout")
def test_oversized_record_raises_typed_error_not_idle_stall(tmp_path: Path) -> None:
    script = (
        "import os, sys, time\n"
        "os.write(1, b'x' * (300 * 1024))\n"
        "sys.stdout.flush()\n"
        "time.sleep(60)\n"
    )
    iterator = _SubprocessStdoutIterator([sys.executable, "-c", script], tmp_path)
    try:
        with pytest.raises(ProviderStreamRecordTooLargeError):
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                iterator.read_nonempty_line(0.05)
        assert iterator._proc.poll() is None
    finally:
        terminate_process_tree(iterator._proc)
        iterator.close()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout")
def test_proxy_delay_after_agent_exit_still_delivers_tail(tmp_path: Path) -> None:
    init = _system_init("chat-proxy-tail")
    payload = _assistant("tail-event")
    script = (
        "import sys, time\n"
        f"print({init!r}, flush=True)\n"
        "time.sleep(0.05)\n"
        f"print({payload!r}, flush=True)\n"
    )
    provider = _provider(tmp_path, lambda argv, cwd: _SubprocessStdoutIterator(
        [sys.executable, "-c", script], cwd
    ), idle=0.5)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    events = list(provider.stream_events(session_id))
    texts = [str(event.get("text") or "") for event in events]
    assert any("tail-event" in text for text in texts)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout")
def test_cleanup_deadline_starts_at_finalization_not_first_event(tmp_path: Path) -> None:
    init = _system_init("chat-budget")
    later = _assistant("later")
    result = _result()
    script = (
        "import sys, time\n"
        f"print({init!r}, flush=True)\n"
        "time.sleep(0.08)\n"
        f"print({later!r}, flush=True)\n"
        f"print({result!r}, flush=True)\n"
    )
    captured: list[float | None] = []
    real_term = terminate_process_tree

    def fake_term(proc, **kwargs):
        captured.append(kwargs.get("timeout"))
        return real_term(proc, **kwargs)

    provider = _provider(
        tmp_path,
        lambda argv, cwd: _SubprocessStdoutIterator(
            [sys.executable, "-c", script], cwd
        ),
        idle=0.0,
    )
    with patch(
        "core_tools.provider.cursor.DEFAULT_TURN_TREE_CLEANUP_SECONDS",
        0.05,
    ), patch(
        "core_tools.provider.cursor.terminate_process_tree",
        side_effect=fake_term,
    ):
        session_id = provider.start_primary_session("planner", {"goal": "x"})
        list(provider.stream_events(session_id))
    assert captured
    assert captured[-1] == pytest.approx(0.05, abs=0.03)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX waitpid ownership")
def test_terminate_process_tree_does_not_reap_unrelated_host_child() -> None:
    sibling = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.exit(17)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    target = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.05)
        terminate_process_tree(target, timeout=1.0)
        assert sibling.wait(timeout=2.0) == 17
    finally:
        if target.poll() is None:
            target.kill()
            target.wait(timeout=2.0)
        if sibling.poll() is None:
            sibling.kill()
            sibling.wait(timeout=2.0)


def test_live_pgid_without_observed_gone_is_fail_closed(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    leader = ProcessIdentity(pid=4242, start_time="100")
    provider._tracked_turn_procs[4242] = tracked_turn_proc(session_id, "planner", 4242)
    provider._tracked_turn_procs[4242].identity = leader
    provider._tracked_turn_procs[4242].pgid = 4242
    provider._tracked_turn_procs[4242].member_identities = (leader,)
    provider._tracked_turn_procs[4242].proc = None
    provider._tracked_turn_procs[4242].group_observed_gone = False
    with patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ), patch(
        "core_tools.provider.cursor.process_group_state",
        return_value=ProcessGroupState.LIVE,
    ):
        assert provider._tracked_tree_is_live(provider._tracked_turn_procs[4242]) is False


def test_reused_pgid_after_observed_gone_is_released(tmp_path: Path) -> None:
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


def test_fallback_does_not_killpg_after_leader_raw_exit() -> None:
    class ExitedProc:
        pid = 4242

        def poll(self) -> int:
            return 0

        def _core_tools_raw_poll(self) -> int:
            return 0

    with patch("core_tools.provider.process_identity.os.killpg") as killpg, patch(
        "core_tools.provider.process_identity.list_process_group_pids",
        return_value=[9999],
    ):
        status = _fallback_kill_bound_janitor_group(ExitedProc(), pgid=4242, timeout=0.1)
    assert killpg.call_count == 0
    assert status["drain"] == DrainResult.UNVERIFIABLE.value


def test_fallback_empty_group_after_leader_exit_is_clean_without_killpg() -> None:
    class ExitedProc:
        pid = 4242

        def poll(self) -> int:
            return 0

        def _core_tools_raw_poll(self) -> int:
            return 0

    with patch("core_tools.provider.process_identity.os.killpg") as killpg, patch(
        "core_tools.provider.process_identity.list_process_group_pids",
        return_value=[],
    ), patch(
        "core_tools.provider.process_identity.is_pid_alive",
        return_value=False,
    ):
        status = _fallback_kill_bound_janitor_group(ExitedProc(), pgid=4242, timeout=0.1)
    assert killpg.call_count == 0
    assert status["drain"] == DrainResult.CLEAN.value
