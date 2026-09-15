"""Idle-stream collector ownership and cleanup-budget invariants for CursorProvider."""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

from core_tools.provider.cursor import (
    DEFAULT_TURN_TREE_CLEANUP_SECONDS,
    CursorProvider,
    _SubprocessStdoutIterator,
)
from core_tools.provider.errors import (
    ProviderActionRequiredError,
    ProviderTurnCleanupError,
    ProviderTurnError,
    ProviderTurnProgressStalledError,
    ProviderTurnStalledError,
)

INCIDENT_QUOTA_MESSAGE = (
    "Increase limits for faster responses You're out of usage. "
    "Switch to Auto, or ask your admin to increase your limit to continue."
)


def _live_idle_stream_collectors() -> list[threading.Thread]:
    return [
        thread
        for thread in threading.enumerate()
        if thread.name == "cursor-idle-stream" and thread.is_alive()
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


def _terminal_error_line(message: str = "provider boom") -> str:
    return json.dumps(
        {
            "type": "result",
            "subtype": "error",
            "is_error": True,
            "session_id": "chat-hang",
            "result": message,
        }
    )


class _TerminalErrorThenBlock:
    def __init__(
        self,
        *,
        message: str = "provider boom",
        release: threading.Event,
        cooperative: bool,
    ) -> None:
        self._message = message
        self._release = release
        self._cooperative = cooperative
        self._emitted = False

    def __iter__(self):
        return self

    def __next__(self) -> str:
        if not self._emitted:
            self._emitted = True
            return _terminal_error_line(self._message)
        self._release.wait(timeout=60)
        raise StopIteration

    def close(self) -> None:
        if self._cooperative:
            self._release.set()


def test_cooperative_close_releases_idle_stream_collector_promptly(tmp_path: Path) -> None:
    release = threading.Event()
    provider = _provider(
        tmp_path,
        lambda argv, cwd: _TerminalErrorThenBlock(release=release, cooperative=True),
        turn_idle_timeout_seconds=120.0,
        turn_progress_timeout_seconds=120.0,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    started_at = time.monotonic()
    with pytest.raises(ProviderTurnError, match="provider boom"):
        list(provider.stream_events(session_id))
    elapsed = time.monotonic() - started_at
    assert elapsed < DEFAULT_TURN_TREE_CLEANUP_SECONDS + 0.75
    assert elapsed < 1.0
    assert _live_idle_stream_collectors() == []


def test_non_cooperative_close_fails_closed_within_cleanup_budget(
    tmp_path: Path,
) -> None:
    release = threading.Event()
    provider = _provider(
        tmp_path,
        lambda argv, cwd: _TerminalErrorThenBlock(release=release, cooperative=False),
        turn_idle_timeout_seconds=120.0,
        turn_progress_timeout_seconds=120.0,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    started_at = time.monotonic()
    with pytest.raises(ProviderTurnError, match="provider boom") as exc_info:
        list(provider.stream_events(session_id))
    elapsed = time.monotonic() - started_at
    assert elapsed < DEFAULT_TURN_TREE_CLEANUP_SECONDS + 0.75
    assert elapsed < 120.0 - 1.0
    notes = getattr(exc_info.value, "__notes__", [])
    assert any("cleanup" in str(note).lower() for note in notes)
    assert _live_idle_stream_collectors() != []
    release.set()
    for thread in _live_idle_stream_collectors():
        thread.join(timeout=1.0)
    assert _live_idle_stream_collectors() == []


def test_idle_stall_with_non_cooperative_close_raises_cleanup_error(
    tmp_path: Path,
) -> None:
    release = threading.Event()

    class _HeartbeatThenIgnoreClose:
        def __init__(self) -> None:
            self._count = 0

        def __iter__(self):
            return self

        def __next__(self) -> str:
            self._count += 1
            if self._count <= 2:
                return json.dumps(
                    {"type": "system", "subtype": "keepalive", "session_id": "chat-idle"}
                )
            release.wait(timeout=60)
            raise StopIteration

        def close(self) -> None:
            return

    provider = _provider(
        tmp_path,
        lambda argv, cwd: _HeartbeatThenIgnoreClose(),
        turn_idle_timeout_seconds=0.05,
        turn_progress_timeout_seconds=120.0,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    started_at = time.monotonic()
    with pytest.raises((ProviderTurnStalledError, ProviderTurnCleanupError)):
        list(provider.stream_events(session_id))
    elapsed = time.monotonic() - started_at
    assert elapsed < DEFAULT_TURN_TREE_CLEANUP_SECONDS + 0.75
    assert _live_idle_stream_collectors() != []
    release.set()
    for thread in _live_idle_stream_collectors():
        thread.join(timeout=1.0)


def test_small_watchdog_values_do_not_shrink_cleanup_budget(tmp_path: Path) -> None:
    release = threading.Event()

    class _ErrorThenIgnoreClose:
        def __init__(self) -> None:
            self._emitted = False

        def __iter__(self):
            return self

        def __next__(self) -> str:
            if not self._emitted:
                self._emitted = True
                return _terminal_error_line()
            release.wait(timeout=60)
            raise StopIteration

        def close(self) -> None:
            return

    provider = _provider(
        tmp_path,
        lambda argv, cwd: _ErrorThenIgnoreClose(),
        turn_idle_timeout_seconds=0.02,
        turn_progress_timeout_seconds=0.02,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    started_at = time.monotonic()
    with pytest.raises(ProviderTurnError, match="provider boom"):
        list(provider.stream_events(session_id))
    elapsed = time.monotonic() - started_at
    assert elapsed >= 0.01
    assert elapsed < DEFAULT_TURN_TREE_CLEANUP_SECONDS + 0.75
    release.set()
    for thread in _live_idle_stream_collectors():
        thread.join(timeout=1.0)


def test_large_watchdog_values_do_not_extend_cleanup_budget(tmp_path: Path) -> None:
    release = threading.Event()
    watchdog = 120.0
    provider = _provider(
        tmp_path,
        lambda argv, cwd: _TerminalErrorThenBlock(release=release, cooperative=False),
        turn_idle_timeout_seconds=watchdog,
        turn_progress_timeout_seconds=watchdog,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    started_at = time.monotonic()
    with pytest.raises(ProviderTurnError, match="provider boom"):
        list(provider.stream_events(session_id))
    elapsed = time.monotonic() - started_at
    assert elapsed < DEFAULT_TURN_TREE_CLEANUP_SECONDS + 0.75
    assert elapsed < watchdog - 5.0
    release.set()
    for thread in _live_idle_stream_collectors():
        thread.join(timeout=1.0)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess cleanup")
def test_subprocess_terminal_quota_error_cleans_up_within_budget(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    script = (
        "import json, sys, time\n"
        "print(json.dumps({"
        "'type': 'result', "
        "'subtype': 'error', "
        "'is_error': True, "
        "'session_id': 'chat-quota-sub', "
        f"'result': {INCIDENT_QUOTA_MESSAGE!r}"
        "}), flush=True)\n"
        "time.sleep(60)\n"
    )
    provider = CursorProvider(
        {
            "limits": {
                "provider": {
                    "max_retries_per_call": 0,
                    "turn_idle_timeout_seconds": 120.0,
                    "turn_progress_timeout_seconds": 120.0,
                }
            }
        },
        workspace=tmp_path,
        runner=lambda argv, cwd: _SubprocessStdoutIterator(
            [sys.executable, "-c", script],
            cwd,
        ),
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    started_at = time.monotonic()
    with pytest.raises(ProviderActionRequiredError):
        list(provider.stream_events(session_id))
    elapsed = time.monotonic() - started_at
    assert elapsed < DEFAULT_TURN_TREE_CLEANUP_SECONDS + 1.5
    assert elapsed < 120.0 - 5.0
    assert provider._tracked_turn_procs == {}
    assert _live_idle_stream_collectors() == []
