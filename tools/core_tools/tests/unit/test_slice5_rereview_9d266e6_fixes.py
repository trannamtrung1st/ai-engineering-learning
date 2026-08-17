"""Slice 5 rereview 9d266e6: session-scoped enrichment and one cleanup deadline."""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core_tools.provider.cursor import (
    DEFAULT_TURN_TREE_CLEANUP_SECONDS,
    CursorProvider,
    _SubprocessStdoutIterator,
)


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
        _idle_config(0.0),
        workspace=tmp_path,
        runner=runner or (lambda argv, cwd: iter(())),
        binary=str(agent),
        skip_probe=True,
    )


def test_abort_turn_does_not_join_unstarted_enrichment(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    entered_start = threading.Event()
    allow_start = threading.Event()
    errors: list[BaseException] = []
    original_thread = threading.Thread

    class DelayedStart(original_thread):
        def start(self) -> None:
            entered_start.set()
            assert allow_start.wait(timeout=2)
            super().start()

    def run_start() -> None:
        with patch("core_tools.provider.cursor.threading.Thread", DelayedStart):
            provider._set_collect_context(session_id, "planner")
            try:
                provider._start_turn_enrichment(MagicMock(pid=4242), timeout=0.05)
            finally:
                provider._clear_collect_context()

    def run_abort() -> None:
        try:
            provider.abort_turn(session_id, timeout=1.0)
        except BaseException as exc:
            errors.append(exc)

    starter = original_thread(target=run_start)
    aborter = original_thread(target=run_abort)
    starter.start()
    assert entered_start.wait(timeout=2)
    aborter.start()
    time.sleep(0.05)
    allow_start.set()
    starter.join(timeout=2)
    aborter.join(timeout=2)
    assert starter.is_alive() is False
    assert aborter.is_alive() is False
    assert errors == []


def test_abort_session_does_not_wait_foreign_enrichment(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    session_a = provider.start_primary_session("planner", {"goal": "a"})
    session_b = provider.start_reviewer_session({"goal": "b"})
    hold_b = threading.Event()

    def enrich_b(proc, *, timeout: float) -> None:
        del proc, timeout
        hold_b.wait(timeout=5)

    with patch.object(provider, "_enrich_tracked_turn_proc", enrich_b):
        provider._set_collect_context(session_b, "reviewer")
        try:
            provider._start_turn_enrichment(MagicMock(pid=9001), timeout=0.05)
        finally:
            provider._clear_collect_context()
        started = time.monotonic()
        provider.abort_turn(session_a, timeout=0.25)
        elapsed = time.monotonic() - started
    hold_b.set()
    for thread in threading.enumerate():
        if thread.name == "cursor-turn-enrich" and thread is not threading.current_thread():
            thread.join(timeout=1)
    assert elapsed < 0.15


def test_cleanup_deadline_covers_enrichment_before_terminate(tmp_path: Path) -> None:
    init = json.dumps(
        {"type": "system", "subtype": "init", "session_id": "chat-deadline"}
    )
    payload = json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}}
    )
    script = f"print({init!r}, flush=True)\nprint({payload!r}, flush=True)\n"
    calls: list[float | None] = []
    clock = {"t": 100.0}

    def fake_monotonic() -> float:
        clock["t"] += 0.001
        return clock["t"]

    def recording_terminate(proc, **kwargs):
        del proc
        calls.append(kwargs.get("timeout"))
        return True

    def wait_enrichment(*, timeout: float | None = None, session_id: str | None = None):
        del session_id
        clock["t"] += 1.0
        del timeout

    def runner(argv: list[str], cwd: Path):
        del argv
        return _SubprocessStdoutIterator([sys.executable, "-c", script], cwd)

    provider = _provider(tmp_path, runner)
    with patch("core_tools.provider.cursor.time.monotonic", fake_monotonic), patch(
        "core_tools.provider.cursor.terminate_process_tree",
        side_effect=recording_terminate,
    ), patch.object(provider, "_wait_turn_enrichment", wait_enrichment):
        session_id = provider.start_primary_session("planner", {"goal": "x"})
        list(provider.stream_events(session_id))
    assert calls
    assert calls[-1] == pytest.approx(DEFAULT_TURN_TREE_CLEANUP_SECONDS - 1.0, abs=0.2)
    assert calls[-1] < DEFAULT_TURN_TREE_CLEANUP_SECONDS - 0.5
