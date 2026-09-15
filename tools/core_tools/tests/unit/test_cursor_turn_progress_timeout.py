"""Logical-progress watchdog vs transport idle timeout for CursorProvider."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from core_tools.provider.cursor import (
    DEFAULT_TURN_TREE_CLEANUP_SECONDS,
    CursorProvider,
)
from core_tools.provider.errors import (
    ProviderActionRequiredError,
    ProviderTurnError,
    ProviderTurnProgressStalledError,
    ProviderTurnStalledError,
)
from core_tools.provider.events import cursor_record_indicates_turn_progress

INCIDENT_QUOTA_MESSAGE = (
    "Increase limits for faster responses You're out of usage. "
    "Switch to Auto, or ask your admin to increase your limit to continue."
)


def _live_named(name: str) -> list[threading.Thread]:
    return [
        thread
        for thread in threading.enumerate()
        if thread.name == name and thread.is_alive()
    ]


def _provider(tmp_path: Path, runner, **provider_limits) -> CursorProvider:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    limits = {
        "max_retries_per_call": 0,
        "turn_idle_timeout_seconds": 1.0,
        "turn_progress_timeout_seconds": 0.08,
    }
    limits.update(provider_limits)
    return CursorProvider(
        {"limits": {"provider": limits}},
        workspace=tmp_path,
        runner=runner,
        binary=str(agent_path),
        skip_probe=True,
    )


def _assistant_line(text: str, session_id: str = "chat-progress") -> str:
    return json.dumps(
        {
            "type": "assistant",
            "session_id": session_id,
            "message": {"content": [{"type": "text", "text": text}]},
        }
    )


def _system_line(subtype: str = "keepalive", session_id: str = "chat-progress") -> str:
    return json.dumps({"type": "system", "subtype": subtype, "session_id": session_id})


def test_system_and_unknown_records_are_not_meaningful_progress() -> None:
    assert (
        cursor_record_indicates_turn_progress(
            {"type": "system", "subtype": "keepalive", "session_id": "chat-1"}
        )
        is False
    )
    assert cursor_record_indicates_turn_progress({"type": "tool_result"}) is False
    assert cursor_record_indicates_turn_progress({"type": "unknown-heartbeat"}) is False
    assert cursor_record_indicates_turn_progress({"type": "thinking"}) is False
    assert (
        cursor_record_indicates_turn_progress(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "hello"}]},
            }
        )
        is True
    )
    assert (
        cursor_record_indicates_turn_progress(
            {"type": "tool_call", "subtype": "started", "tool": "read"}
        )
        is True
    )
    assert (
        cursor_record_indicates_turn_progress(
            {"type": "result", "is_error": True, "result": "failed"}
        )
        is True
    )


def test_noisy_non_progress_stream_hits_logical_progress_timeout(
    tmp_path: Path,
) -> None:
    """Required regression: complete heartbeats must not keep a turn alive forever."""

    closed = threading.Event()

    class _CloseableNoisy:
        def __init__(self) -> None:
            self._started = False

        def __iter__(self):
            return self

        def __next__(self) -> str:
            if not self._started:
                self._started = True
                return _assistant_line("start")
            if closed.wait(timeout=0.01):
                raise StopIteration
            return _system_line()

        def close(self) -> None:
            closed.set()

    provider = _provider(
        tmp_path,
        lambda argv, cwd: _CloseableNoisy(),
        turn_idle_timeout_seconds=1.0,
        turn_progress_timeout_seconds=0.08,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    started_at = time.monotonic()
    with pytest.raises(ProviderTurnProgressStalledError) as exc_info:
        list(provider.stream_events(session_id))
    elapsed = time.monotonic() - started_at
    assert elapsed < 0.8
    assert "meaningful" in str(exc_info.value).lower() or "progress" in str(
        exc_info.value
    ).lower()
    assert _live_named("cursor-idle-stream") == []
    closed.set()


def test_genuine_progress_resets_logical_progress_deadline(tmp_path: Path) -> None:
    def runner(argv: list[str], cwd: Path):
        del argv, cwd
        yield _assistant_line("start")
        yield _system_line()
        time.sleep(0.05)
        yield _assistant_line("still working")
        time.sleep(0.05)
        yield json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "session_id": "chat-progress",
                "result": "ok",
            }
        )

    provider = _provider(
        tmp_path,
        runner,
        turn_idle_timeout_seconds=1.0,
        turn_progress_timeout_seconds=0.2,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    events = list(provider.stream_events(session_id))
    texts = [event.get("text") for event in events if event.get("type") == "assistant"]
    assert "start" in texts
    assert "still working" in texts
    assert any(event.get("type") == "done" and not event.get("is_error") for event in events)


def test_terminal_result_is_error_does_not_wait_for_eof(tmp_path: Path) -> None:
    closed = threading.Event()
    yielded_error = threading.Event()

    class _ErrorThenHangStream:
        def __iter__(self):
            return self

        def __next__(self) -> str:
            if not yielded_error.is_set():
                yielded_error.set()
                return json.dumps(
                    {
                        "type": "result",
                        "subtype": "error",
                        "is_error": True,
                        "session_id": "chat-hang",
                        "result": "provider boom",
                    }
                )
            closed.wait(timeout=30)
            raise StopIteration

        def close(self) -> None:
            closed.set()

    provider = _provider(
        tmp_path,
        lambda argv, cwd: _ErrorThenHangStream(),
        turn_idle_timeout_seconds=5.0,
        turn_progress_timeout_seconds=5.0,
        max_retries_per_call=0,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    started_at = time.monotonic()
    with pytest.raises(ProviderTurnError, match="provider boom") as exc_info:
        list(provider.stream_events(session_id))
    assert not isinstance(exc_info.value, ProviderTurnProgressStalledError)
    assert time.monotonic() - started_at < 1.0
    assert _live_named("cursor-idle-stream") == []
    closed.set()


def test_terminal_quota_result_is_error_does_not_wait_for_eof(tmp_path: Path) -> None:
    closed = threading.Event()

    class _QuotaThenHangStream:
        def __init__(self) -> None:
            self._emitted = False

        def __iter__(self):
            return self

        def __next__(self) -> str:
            if not self._emitted:
                self._emitted = True
                return json.dumps(
                    {
                        "type": "result",
                        "subtype": "error",
                        "is_error": True,
                        "session_id": "chat-hang",
                        "result": INCIDENT_QUOTA_MESSAGE,
                    }
                )
            closed.wait(timeout=30)
            raise StopIteration

        def close(self) -> None:
            closed.set()

    provider = _provider(
        tmp_path,
        lambda argv, cwd: _QuotaThenHangStream(),
        turn_idle_timeout_seconds=5.0,
        turn_progress_timeout_seconds=5.0,
        max_retries_per_call=0,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    started_at = time.monotonic()
    with pytest.raises(ProviderActionRequiredError):
        list(provider.stream_events(session_id))
    assert time.monotonic() - started_at < 1.0
    assert _live_named("cursor-idle-stream") == []
    closed.set()


def test_idle_stream_teardown_does_not_wait_watchdog_timeouts(tmp_path: Path) -> None:
    """Collector cleanup is bounded by process-tree cleanup, not idle/progress windows."""

    release = threading.Event()

    class _ErrorThenIgnoreClose:
        def __init__(self) -> None:
            self._emitted = False

        def __iter__(self):
            return self

        def __next__(self) -> str:
            if not self._emitted:
                self._emitted = True
                return json.dumps(
                    {
                        "type": "result",
                        "subtype": "error",
                        "is_error": True,
                        "session_id": "chat-hang",
                        "result": "provider boom",
                    }
                )
            release.wait(timeout=60)
            raise StopIteration

        def close(self) -> None:
            return

    watchdog = 4.0
    provider = _provider(
        tmp_path,
        lambda argv, cwd: _ErrorThenIgnoreClose(),
        turn_idle_timeout_seconds=watchdog,
        turn_progress_timeout_seconds=watchdog,
        max_retries_per_call=0,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    started_at = time.monotonic()
    try:
        with pytest.raises(ProviderTurnError, match="provider boom"):
            list(provider.stream_events(session_id))
        elapsed = time.monotonic() - started_at
        assert elapsed < DEFAULT_TURN_TREE_CLEANUP_SECONDS + 0.75
        assert elapsed < watchdog - 0.5
    finally:
        release.set()


def test_progress_timeout_zero_is_explicit_opt_out_when_idle_remains(
    tmp_path: Path,
) -> None:
    closed = threading.Event()

    class _HeartbeatThenIdle:
        def __init__(self) -> None:
            self._count = 0

        def __iter__(self):
            return self

        def __next__(self) -> str:
            self._count += 1
            if self._count <= 3:
                return _system_line()
            closed.wait(timeout=30)
            raise StopIteration

        def close(self) -> None:
            closed.set()

    provider = _provider(
        tmp_path,
        lambda argv, cwd: _HeartbeatThenIdle(),
        turn_idle_timeout_seconds=0.08,
        turn_progress_timeout_seconds=0,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    with pytest.raises(ProviderTurnStalledError) as exc_info:
        list(provider.stream_events(session_id))
    assert not isinstance(exc_info.value, ProviderTurnProgressStalledError)
    closed.set()


def test_default_progress_timeout_matches_idle_default(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=lambda argv, cwd: iter(()),
        binary=str(agent_path),
        skip_probe=True,
    )
    assert provider._turn_idle_timeout_seconds() == 300.0
    assert provider._turn_progress_timeout_seconds() == 300.0


def test_both_timeouts_zero_is_the_explicit_dual_opt_out(tmp_path: Path) -> None:
    started = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    def blocking_runner(argv: list[str], cwd: Path):
        started.set()
        release.wait(timeout=0.5)
        yield from ()

    provider = _provider(
        tmp_path,
        blocking_runner,
        turn_idle_timeout_seconds=0,
        turn_progress_timeout_seconds=0,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    stream = provider.stream_events(session_id)

    def consume() -> None:
        try:
            list(stream)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=consume)
    thread.start()
    assert started.wait(timeout=0.5)
    time.sleep(0.15)
    assert thread.is_alive()
    release.set()
    thread.join(timeout=1)
    assert not thread.is_alive()
    assert errors
