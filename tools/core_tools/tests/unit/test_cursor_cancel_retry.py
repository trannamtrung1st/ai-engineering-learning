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
