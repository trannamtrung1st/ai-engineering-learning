"""Tests for CursorProvider idle stream timeout."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from core_tools.provider.cursor import CursorProvider
from core_tools.provider.errors import ProviderTurnStalledError


def test_cursor_provider_raises_when_stream_idle_exceeds_timeout(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    release = threading.Event()

    def blocking_runner(argv: list[str], cwd: Path):
        yield '{"type":"assistant","message":{"content":[{"type":"text","text":"start"}]}}'
        release.wait(timeout=1)

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
    thread.join(timeout=1)
    release.set()

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], ProviderTurnStalledError)


def test_cursor_provider_does_not_retry_after_idle_timeout(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    attempts = {"count": 0}
    release = threading.Event()

    def blocking_runner(argv: list[str], cwd: Path):
        attempts["count"] += 1
        yield '{"type":"assistant","message":{"content":[{"type":"text","text":"start"}]}}'
        release.wait(timeout=1)

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
    provider.resume_primary_session(session_id, {"goal": "follow-up"})
    stream = provider.stream_events(session_id)

    def consume() -> None:
        try:
            list(stream)
        except ProviderTurnStalledError:
            return

    thread = threading.Thread(target=consume)
    thread.start()
    thread.join(timeout=1)
    release.set()

    assert attempts["count"] == 1


def test_cursor_provider_idle_timeout_disabled_by_default(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    release = threading.Event()
    errors: list[BaseException] = []

    def blocking_runner(argv: list[str], cwd: Path):
        release.wait(timeout=0.2)
        yield from ()

    provider = CursorProvider(
        {"limits": {"provider": {"max_retries_per_call": 0}}},
        workspace=tmp_path,
        runner=blocking_runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    provider.resume_primary_session(session_id, {"goal": "follow-up"})
    stream = provider.stream_events(session_id)

    def consume() -> None:
        try:
            list(stream)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=consume)
    thread.start()
    time.sleep(0.05)
    release.set()
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert errors
