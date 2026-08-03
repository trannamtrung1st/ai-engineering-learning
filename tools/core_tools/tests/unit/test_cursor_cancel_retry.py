"""Tests for CursorProvider cancel/retry interaction."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from core_tools.provider.cursor import CursorProvider
from core_tools.provider.errors import ProviderTurnError


def test_cursor_provider_does_not_retry_after_terminate_all_sessions(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    attempts = {"count": 0}
    release = threading.Event()

    def flaky_runner(argv: list[str], cwd: Path):
        attempts["count"] += 1
        if attempts["count"] == 1:
            release.wait(timeout=1)
            raise ProviderTurnError("broken pipe")
        yield from ()

    provider = CursorProvider(
        {"limits": {"provider": {"max_retries_per_call": 2}}},
        workspace=tmp_path,
        runner=flaky_runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    provider.resume_primary_session(session_id, {"goal": "follow-up"})
    stream = provider.stream_events(session_id)

    errors: list[BaseException] = []

    def consume() -> None:
        try:
            list(stream)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=consume)
    thread.start()
    time.sleep(0.05)
    provider.terminate_all_sessions()
    release.set()
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert attempts["count"] == 1


def test_cursor_provider_terminate_session_aborts_inflight_turn(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    release = threading.Event()

    def blocking_runner(argv: list[str], cwd: Path):
        release.wait(timeout=1)
        yield from ()

    provider = CursorProvider(
        {"limits": {"provider": {"max_retries_per_call": 0}}},
        workspace=tmp_path,
        runner=blocking_runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("producer", {"goal": "x"})
    provider.resume_primary_session(session_id, {"goal": "follow-up"})
    stream = provider.stream_events(session_id)

    errors: list[BaseException] = []

    def consume() -> None:
        try:
            list(stream)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=consume)
    thread.start()
    time.sleep(0.05)
    provider.terminate_session(session_id)
    release.set()
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert errors == []


def test_cursor_provider_abort_turn_keeps_session_for_follow_up(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    release = threading.Event()
    attempts = {"count": 0}

    def blocking_runner(argv: list[str], cwd: Path):
        attempts["count"] += 1
        release.wait(timeout=1)
        yield from ()

    provider = CursorProvider(
        {"limits": {"provider": {"max_retries_per_call": 0}}},
        workspace=tmp_path,
        runner=blocking_runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("producer", {"goal": "x"})
    provider.resume_primary_session(session_id, {"goal": "follow-up"})
    stream = provider.stream_events(session_id)

    def consume() -> None:
        list(stream)

    thread = threading.Thread(target=consume)
    thread.start()
    time.sleep(0.05)
    provider.abort_turn(session_id)
    release.set()
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert session_id in provider._sessions
    provider.resume_primary_session(session_id, {"goal": "next batch"})
    assert provider._sessions[session_id].pending_argv is not None
