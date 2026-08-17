"""Slice 5 rereview b8a5a80: buffered drain, one cleanup deadline, identity-safe survivors."""

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


def _provider(tmp_path: Path, runner) -> CursorProvider:
    agent = tmp_path / "agent"
    agent.write_text("", encoding="utf-8")
    return CursorProvider(
        _idle_config(0.08),
        workspace=tmp_path,
        runner=runner,
        binary=str(agent),
        skip_probe=True,
    )


def _system_init(session_id: str) -> str:
    return json.dumps({"type": "system", "subtype": "init", "session_id": session_id})


def test_zero_budget_still_drains_buffered_final_line(tmp_path: Path) -> None:
    payload = json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "tail"}]}}
    )
    init = _system_init("chat-zero-budget")
    script = (
        "import sys\n"
        f"sys.stdout.write({init!r} + '\\n' + {payload!r})\n"
        "sys.stdout.flush()\n"
    )
    iterator_holder: dict[str, _SubprocessStdoutIterator] = {}

    def runner(argv: list[str], cwd: Path):
        del argv
        iterator = _SubprocessStdoutIterator([sys.executable, "-c", script], cwd)
        iterator_holder["it"] = iterator
        return iterator

    def consume_budget(pid, run_id=None, command=None, timeout=None):
        del run_id, command
        if timeout:
            time.sleep(min(0.05, float(timeout)))
        return ProcessIdentity(pid=pid, start_time="synthetic-test")

    provider = _provider(tmp_path, runner)
    try:
        with patch(
            "core_tools.provider.cursor.read_process_identity",
            side_effect=consume_budget,
        ), patch(
            "core_tools.provider.cursor.terminate_process_tree",
            return_value=True,
        ):
            session_id = provider.start_primary_session("planner", {"goal": "x"})
            events = list(provider.stream_events(session_id))
    finally:
        iterator = iterator_holder.get("it")
        proc = getattr(iterator, "_proc", None) if iterator is not None else None
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
    texts = [str(event.get("text") or "") for event in events]
    assert any("tail" in text for text in texts)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess stdout")
def test_large_final_line_without_newline_is_preserved(tmp_path: Path) -> None:
    init = _system_init("chat-large-final")
    blob = "x" * 8192
    payload = json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": blob}]}}
    )
    script = (
        "import sys\n"
        f"sys.stdout.write({init!r} + '\\n' + {payload!r})\n"
        "sys.stdout.flush()\n"
    )

    def runner(argv: list[str], cwd: Path):
        del argv
        return _SubprocessStdoutIterator([sys.executable, "-c", script], cwd)

    provider = _provider(tmp_path, runner)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    events = list(provider.stream_events(session_id))
    texts = [str(event.get("text") or "") for event in events]
    assert any(blob[:32] in text for text in texts)


def test_slow_process_creation_is_not_counted_as_idle_stall(tmp_path: Path) -> None:
    payload = json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "ready"}]}}
    )
    init = _system_init("chat-slow-spawn")

    def runner(argv: list[str], cwd: Path):
        del argv
        time.sleep(0.12)
        script = f"print({init!r}, flush=True)\nprint({payload!r}, flush=True)\n"
        return _SubprocessStdoutIterator([sys.executable, "-c", script], cwd)

    provider = _provider(tmp_path, runner)
    with patch(
        "core_tools.provider.cursor.capture_process_group_identities",
        return_value=[],
    ):
        session_id = provider.start_primary_session("planner", {"goal": "x"})
        events = list(provider.stream_events(session_id))
    texts = [str(event.get("text") or "") for event in events]
    assert any("ready" in text for text in texts)


def test_slow_event_processing_does_not_false_stall_buffered_lines(tmp_path: Path) -> None:
    init = _system_init("chat-slow-cb")
    lines = [
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": str(i)}]}})
        for i in range(5)
    ]
    script = f"print({init!r}, flush=True)\n" + "".join(
        f"print({line!r}, flush=True)\n" for line in lines
    )

    def runner(argv: list[str], cwd: Path):
        del argv
        return _SubprocessStdoutIterator([sys.executable, "-c", script], cwd)

    seen: list[float] = []

    def slow_emit(self, event):
        del self
        seen.append(time.monotonic())
        time.sleep(0.05)
        del event

    provider = _provider(tmp_path, runner)
    with patch.object(CursorProvider, "_emit_provider_event", slow_emit), patch(
        "core_tools.provider.cursor.capture_process_group_identities",
        return_value=[],
    ):
        session_id = provider.start_primary_session("planner", {"goal": "x"})
        events = list(provider.stream_events(session_id))
    assert len(events) >= 5


def test_cleanup_deadline_is_not_reset_in_finally(tmp_path: Path) -> None:
    script = "import time\ntime.sleep(60)\n"
    calls: list[float | None] = []
    clock = {"t": 100.0}

    def fake_monotonic() -> float:
        clock["t"] += 0.03
        return clock["t"]

    def recording_terminate(proc, **kwargs):
        del proc
        calls.append(kwargs.get("timeout"))
        clock["t"] += 1.8
        return True

    def runner(argv: list[str], cwd: Path):
        del argv
        return _SubprocessStdoutIterator([sys.executable, "-c", script], cwd)

    agent = tmp_path / "agent"
    agent.write_text("", encoding="utf-8")
    provider = CursorProvider(
        _idle_config(0.05),
        workspace=tmp_path,
        runner=runner,
        binary=str(agent),
        skip_probe=True,
    )
    with patch("core_tools.provider.cursor.time.monotonic", fake_monotonic), patch(
        "core_tools.provider.cursor.terminate_process_tree",
        side_effect=recording_terminate,
    ):
        session_id = provider.start_primary_session("planner", {"goal": "x"})
        with pytest.raises(ProviderTurnStalledError):
            list(provider.stream_events(session_id))
    assert calls
    assert calls[0] == pytest.approx(DEFAULT_TURN_TREE_CLEANUP_SECONDS, abs=0.05)
    if len(calls) > 1:
        assert calls[1] < DEFAULT_TURN_TREE_CLEANUP_SECONDS - 0.5


def test_stall_decision_ignores_cleanup_wall_time(tmp_path: Path) -> None:
    idle = 0.08
    script = "import time\ntime.sleep(60)\n"
    clock = {"t": 0.0}
    stall_clock: dict[str, float] = {}

    def fake_monotonic() -> float:
        return clock["t"]

    def fake_read_nonempty_line(self, timeout: float):
        del self
        clock["t"] += max(0.0, timeout)
        return None

    def runner(argv: list[str], cwd: Path):
        del argv
        return _SubprocessStdoutIterator([sys.executable, "-c", script], cwd)

    def cleanup_without_wall_clock(*args, **kwargs):
        del args, kwargs
        stall_clock["t"] = clock["t"]
        return True

    agent = tmp_path / "agent"
    agent.write_text("", encoding="utf-8")
    provider = CursorProvider(
        _idle_config(idle),
        workspace=tmp_path,
        runner=runner,
        binary=str(agent),
        skip_probe=True,
    )
    with patch("core_tools.provider.cursor.time.monotonic", fake_monotonic), patch.object(
        _SubprocessStdoutIterator,
        "read_nonempty_line",
        fake_read_nonempty_line,
    ), patch(
        "core_tools.provider.cursor.terminate_process_tree",
        side_effect=cleanup_without_wall_clock,
    ):
        session_id = provider.start_primary_session("planner", {"goal": "x"})
        with pytest.raises(ProviderTurnStalledError):
            list(provider.stream_events(session_id))
    assert stall_clock["t"] <= idle + 1e-6


def test_reused_pgid_occupant_is_not_a_session_survivor(tmp_path: Path) -> None:
    agent = tmp_path / "agent"
    agent.write_text("", encoding="utf-8")
    provider = CursorProvider(
        _idle_config(0.08),
        workspace=tmp_path,
        runner=lambda argv, cwd: iter(()),
        binary=str(agent),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    leader = ProcessIdentity(pid=4242, start_time="100")
    provider._tracked_turn_procs[4242] = tracked_turn_proc(session_id, "planner", 4242)
    provider._tracked_turn_procs[4242].identity = leader
    provider._tracked_turn_procs[4242].pgid = 4242
    provider._tracked_turn_procs[4242].member_identities = (leader,)
    provider._tracked_turn_procs[4242].proc = None

    with patch("core_tools.provider.cursor.is_pid_alive", return_value=True), patch(
        "core_tools.provider.cursor.process_identity_is_live",
        return_value=False,
    ):
        surviving = provider._surviving_pids_for_session(session_id, [])
    assert surviving == ()


def test_sync_member_snapshot_survives_leader_exit(tmp_path: Path) -> None:
    agent = tmp_path / "agent"
    agent.write_text("", encoding="utf-8")
    provider = CursorProvider(
        _idle_config(2.0),
        workspace=tmp_path,
        runner=lambda argv, cwd: iter(()),
        binary=str(agent),
        skip_probe=True,
    )
    child = ProcessIdentity(pid=5151, start_time="200")
    captured = {"n": 0}

    def fake_capture(identity, timeout=None):
        del identity, timeout
        captured["n"] += 1
        return [ProcessIdentity(pid=4242, start_time="100"), child]

    class FakeProc:
        pid = 4242

        def poll(self):
            return 0

    with patch(
        "core_tools.provider.cursor.read_process_identity",
        return_value=ProcessIdentity(pid=4242, start_time="100"),
    ), patch(
        "core_tools.provider.cursor.read_process_group_id",
        return_value=4242,
    ), patch(
        "core_tools.provider.cursor.is_pid_alive",
        return_value=True,
    ), patch(
        "core_tools.provider.cursor.capture_process_group_identities",
        side_effect=fake_capture,
    ):
        provider._set_collect_context("sess-1", "planner")
        provider._register_tracked_turn_proc(FakeProc(), timeout=0.05)
    entry = provider._tracked_turn_procs[4242]
    assert captured["n"] == 1
    assert entry.member_identities is not None
    assert any(identity.pid == 5151 for identity in entry.member_identities)
    names = {thread.name for thread in __import__("threading").enumerate()}
    assert "cursor-group-snapshot" not in names
