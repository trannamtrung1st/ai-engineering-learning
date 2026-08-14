"""Tests for CursorProvider idle stream timeout."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from unittest.mock import patch

import pytest

from core_tools.provider.cursor import CursorProvider
from core_tools.provider.errors import ProviderTurnError, ProviderTurnStalledError


class _CloseableIdleStream:
    def __init__(self, first_line: str) -> None:
        self._first_line = first_line
        self._emitted = False
        self._closed = threading.Event()

    def __iter__(self):
        return self

    def __next__(self) -> str:
        if not self._emitted:
            self._emitted = True
            return self._first_line
        self._closed.wait(timeout=30)
        raise StopIteration

    def close(self) -> None:
        self._closed.set()


def _live_named(name: str) -> list[threading.Thread]:
    return [
        thread
        for thread in threading.enumerate()
        if thread.name == name and thread.is_alive()
    ]


def test_cursor_provider_raises_when_stream_idle_exceeds_timeout(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")

    def blocking_runner(argv: list[str], cwd: Path):
        return _CloseableIdleStream(
            '{"type":"assistant","message":{"content":[{"type":"text","text":"start"}]}}'
        )

    provider = CursorProvider(
        {
            "limits": {
                "provider": {
                    "turn_idle_timeout_seconds": 0.1,
                    "max_retries_per_call": 2,
                }
            }
        },
        workspace=tmp_path,
        runner=blocking_runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    stream = provider.stream_events(session_id)

    errors: list[BaseException] = []

    def consume() -> None:
        try:
            list(stream)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=consume)
    thread.start()
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], ProviderTurnStalledError)
    assert _live_named("cursor-idle-stream") == []


def test_cursor_provider_does_not_retry_after_idle_timeout(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    attempts = {"count": 0}

    def blocking_runner(argv: list[str], cwd: Path):
        attempts["count"] += 1
        return _CloseableIdleStream(
            '{"type":"assistant","message":{"content":[{"type":"text","text":"start"}]}}'
        )

    provider = CursorProvider(
        {
            "limits": {
                "provider": {
                    "turn_idle_timeout_seconds": 0.05,
                    "max_retries_per_call": 2,
                }
            }
        },
        workspace=tmp_path,
        runner=blocking_runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    stream = provider.stream_events(session_id)

    def consume() -> None:
        try:
            list(stream)
        except ProviderTurnStalledError:
            return

    thread = threading.Thread(target=consume)
    thread.start()
    thread.join(timeout=1)

    assert attempts["count"] == 1
    assert _live_named("cursor-idle-stream") == []


def test_cursor_idle_timeout_joins_producer_without_post_hoc_release(
    tmp_path: Path,
) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")

    def blocking_runner(argv: list[str], cwd: Path):
        return _CloseableIdleStream(
            '{"type":"assistant","message":{"content":[{"type":"text","text":"start"}]}}'
        )

    provider = CursorProvider(
        {
            "limits": {
                "provider": {
                    "turn_idle_timeout_seconds": 0.05,
                    "max_retries_per_call": 0,
                }
            }
        },
        workspace=tmp_path,
        runner=blocking_runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    with pytest.raises(ProviderTurnStalledError):
        list(provider.stream_events(session_id))
    assert _live_named("cursor-idle-stream") == []


def test_cursor_provider_idle_timeout_opt_out_is_explicit_zero(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    started = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    def blocking_runner(argv: list[str], cwd: Path):
        started.set()
        release.wait(timeout=0.5)
        yield from ()

    provider = CursorProvider(
        {"limits": {"provider": {"max_retries_per_call": 0, "turn_idle_timeout_seconds": 0}}},
        workspace=tmp_path,
        runner=blocking_runner,
        binary=str(agent_path),
        skip_probe=True,
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
    assert started.wait(timeout=0.5), "fake runner did not reach blocking point"
    release.set()
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert errors


class _IgnoreCloseIdleStream:
    def __init__(self, first_line: str | None = None) -> None:
        self._first_line = first_line
        self._emitted = False

    def __iter__(self):
        return self

    def __next__(self) -> str:
        if self._first_line is not None and not self._emitted:
            self._emitted = True
            return self._first_line
        while True:
            threading.Event().wait(timeout=0.05)

    def close(self) -> None:
        return


def test_default_config_cursor_stream_stalls_without_override(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")

    def silent_runner(argv: list[str], cwd: Path):
        return _IgnoreCloseIdleStream()

    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=silent_runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    assert provider._turn_idle_timeout_seconds() == 2.0
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    started = time.monotonic()
    with pytest.raises((ProviderTurnStalledError, ProviderTurnError)):
        list(provider.stream_events(session_id))
    assert time.monotonic() - started < 8.0


def test_default_config_stalls_after_done_looking_payload(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")

    def runner(argv: list[str], cwd: Path):
        return _IgnoreCloseIdleStream(
            '{"type":"result","subtype":"success","is_error":false}'
        )

    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    with pytest.raises((ProviderTurnStalledError, ProviderTurnError)):
        list(provider.stream_events(session_id))


def test_idle_watchdog_stops_producer_that_ignores_close(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")

    def runner(argv: list[str], cwd: Path):
        return _IgnoreCloseIdleStream(
            '{"type":"assistant","message":{"content":[{"type":"text","text":"start"}]}}'
        )

    provider = CursorProvider(
        {
            "limits": {
                "provider": {
                    "turn_idle_timeout_seconds": 0.05,
                    "max_retries_per_call": 0,
                }
            }
        },
        workspace=tmp_path,
        runner=runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    with patch("ctypes.pythonapi.PyThreadState_SetAsyncExc") as async_exc:
        with pytest.raises(ProviderTurnError, match="idle-stream producer failed to stop"):
            list(provider.stream_events(session_id))
    assert async_exc.call_count == 0
