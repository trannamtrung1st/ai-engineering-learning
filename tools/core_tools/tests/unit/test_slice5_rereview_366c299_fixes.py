"""Slice 5 rereview 366c299: shared idle deadline, separate teardown, one registration."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider.cursor import (
    DEFAULT_TURN_TREE_CLEANUP_SECONDS,
    CursorProvider,
    _SubprocessStdoutIterator,
)
from core_tools.provider.errors import ProviderTurnStalledError
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


def test_registration_shares_idle_detection_deadline(tmp_path: Path) -> None:
    idle = 0.08
    script = "import time\ntime.sleep(60)\n"

    def runner(argv: list[str], cwd: Path):
        del argv
        return _SubprocessStdoutIterator([sys.executable, "-c", script], cwd)

    agent = tmp_path / "agent"
    agent.write_text("", encoding="utf-8")
    provider = CursorProvider(
        _idle_config(idle),
        workspace=tmp_path,
        runner=runner,
        binary=str(agent),
        skip_probe=True,
    )
    handshake_at: dict[str, float] = {}
    idle_call: dict[str, object] = {}
    original_wait = _SubprocessStdoutIterator.wait_agent_started
    original_idle = CursorProvider._iter_stream_with_idle_timeout

    def wait_then_mark(self, timeout=None):
        original_wait(self, timeout=timeout)
        handshake_at["t"] = time.monotonic()

    def capture_idle(self, stream, **kwargs):
        del self
        idle_call["deadline"] = kwargs.get("deadline")
        idle_call["idle_timeout"] = kwargs.get("idle_timeout")
        idle_call["armed_at"] = time.monotonic()
        return original_idle(stream, **kwargs)

    with patch.object(
        _SubprocessStdoutIterator,
        "wait_agent_started",
        wait_then_mark,
    ), patch.object(
        CursorProvider,
        "_iter_stream_with_idle_timeout",
        capture_idle,
    ), patch(
        "core_tools.provider.cursor.terminate_process_tree",
        return_value=True,
    ):
        session_id = provider.start_primary_session("planner", {"goal": "x"})
        with pytest.raises(ProviderTurnStalledError):
            list(provider.stream_events(session_id))
    deadline = idle_call["deadline"]
    armed_at = idle_call["armed_at"]
    assert isinstance(deadline, float)
    assert isinstance(armed_at, float)
    assert idle_call["idle_timeout"] == idle
    assert deadline >= handshake_at["t"]
    assert deadline - armed_at == pytest.approx(idle, abs=0.02)
    assert provider._tracked_turn_procs == {}


def test_idle_teardown_uses_separate_cleanup_budget() -> None:
    assert DEFAULT_TURN_TREE_CLEANUP_SECONDS >= 2.0


def test_stream_registers_tracked_process_exactly_once(tmp_path: Path) -> None:
    lines = [
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": str(i)}]}})
        for i in range(100)
    ]
    init = json.dumps({"type": "system", "subtype": "init", "session_id": "chat-once"})
    script = (
        "import sys\n"
        f"print({init!r}, flush=True)\n"
        + "".join(f"print({line!r}, flush=True)\n" for line in lines)
    )

    def runner(argv: list[str], cwd: Path):
        del argv
        return _SubprocessStdoutIterator([sys.executable, "-c", script], cwd)

    agent = tmp_path / "agent"
    agent.write_text("", encoding="utf-8")
    provider = CursorProvider(
        _idle_config(2.0),
        workspace=tmp_path,
        runner=runner,
        binary=str(agent),
        skip_probe=True,
    )
    real = provider._register_tracked_turn_proc
    calls = {"n": 0}

    def counting(proc, *, timeout=None):
        calls["n"] += 1
        return real(proc, timeout=timeout)

    with patch.object(provider, "_register_tracked_turn_proc", counting):
        session_id = provider.start_primary_session("planner", {"goal": "x"})
        list(provider.stream_events(session_id))
    assert calls["n"] == 1


def test_surviving_pids_report_live_descendant_not_dead_leader(tmp_path: Path) -> None:
    agent = tmp_path / "agent"
    agent.write_text("", encoding="utf-8")
    provider = CursorProvider(
        _idle_config(0.08),
        workspace=tmp_path,
        runner=lambda argv, cwd: iter(()),
        binary=str(agent),
        skip_probe=True,
    )
    leader = ProcessIdentity(pid=4242, start_time="1")
    child = ProcessIdentity(pid=4243, start_time="2")
    provider._tracked_turn_procs[4242] = tracked_turn_proc("sess-1", "planner", 4242)
    provider._tracked_turn_procs[4242].identity = leader
    provider._tracked_turn_procs[4242].pgid = 4242
    provider._tracked_turn_procs[4242].member_identities = (leader, child)
    provider._tracked_turn_procs[4242].proc = None

    with patch(
        "core_tools.provider.cursor.process_identity_is_live",
        side_effect=lambda identity, timeout=None: identity.pid == 4243,
    ):
        surviving = provider._surviving_pids_for_session("sess-1", [])
    assert 4243 in surviving
    assert 4242 not in surviving
