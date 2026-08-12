"""Tests for CursorProvider cancel/retry interaction."""

from __future__ import annotations

import threading
from pathlib import Path

from core_tools.provider.cursor import CursorProvider
from core_tools.provider.errors import ProviderTurnError


def _wait_for_runner_block(
    started: threading.Event,
    *,
    timeout: float = 0.5,
) -> None:
    assert started.wait(timeout=timeout), "fake runner did not reach blocking point"


def test_cursor_provider_does_not_retry_after_terminate_all_sessions(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    attempts = {"count": 0}
    started = threading.Event()
    release = threading.Event()

    def flaky_runner(argv: list[str], cwd: Path):
        attempts["count"] += 1
        if attempts["count"] == 1:
            started.set()
            release.wait(timeout=0.5)
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
    stream = provider.stream_events(session_id)

    errors: list[BaseException] = []

    def consume() -> None:
        try:
            list(stream)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=consume)
    thread.start()
    _wait_for_runner_block(started)
    provider.terminate_all_sessions()
    release.set()
    thread.join(timeout=0.5)

    assert not thread.is_alive()
    assert attempts["count"] == 1


def test_cursor_provider_terminate_session_aborts_inflight_turn(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    started = threading.Event()
    release = threading.Event()

    def blocking_runner(argv: list[str], cwd: Path):
        started.set()
        release.wait(timeout=0.5)
        yield from ()

    provider = CursorProvider(
        {"limits": {"provider": {"max_retries_per_call": 0}}},
        workspace=tmp_path,
        runner=blocking_runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("producer", {"goal": "x"})
    provider.abort_turn(session_id)
    provider.resume_primary_session(session_id, {"goal": "follow-up"}, role="producer")
    stream = provider.stream_events(session_id)

    errors: list[BaseException] = []

    def consume() -> None:
        try:
            list(stream)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=consume)
    thread.start()
    _wait_for_runner_block(started)
    provider.terminate_session(session_id)
    release.set()
    thread.join(timeout=0.5)

    assert not thread.is_alive()
    assert errors == []


def test_cursor_provider_abort_turn_keeps_session_for_follow_up(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    started = threading.Event()
    release = threading.Event()
    attempts = {"count": 0}

    def blocking_runner(argv: list[str], cwd: Path):
        attempts["count"] += 1
        started.set()
        release.wait(timeout=0.5)
        yield from ()

    provider = CursorProvider(
        {"limits": {"provider": {"max_retries_per_call": 0}}},
        workspace=tmp_path,
        runner=blocking_runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("producer", {"goal": "x"})
    provider.abort_turn(session_id)
    provider.resume_primary_session(session_id, {"goal": "follow-up"}, role="producer")
    stream = provider.stream_events(session_id)

    def consume() -> None:
        list(stream)

    thread = threading.Thread(target=consume)
    thread.start()
    _wait_for_runner_block(started)
    provider.abort_turn(session_id)
    release.set()
    thread.join(timeout=0.5)

    assert not thread.is_alive()
    assert session_id in provider._sessions
    provider.resume_primary_session(session_id, {"goal": "next batch"}, role="producer")
    assert provider._sessions[session_id].pending_argv is not None


def test_cursor_provider_abort_turn_drops_buffered_events(tmp_path: Path) -> None:
    import json

    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    started = threading.Event()
    release = threading.Event()
    block_second = threading.Event()
    durable_id = "chat-producer-1"
    stream_lines = [
        json.dumps(
            {
                "type": "system",
                "subtype": "init",
                "session_id": durable_id,
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "session_id": durable_id,
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "should not be delivered"}],
                },
            }
        ),
    ]

    def slow_runner(argv: list[str], cwd: Path):
        yield stream_lines[0]
        started.set()
        block_second.wait(timeout=0.5)
        yield stream_lines[1]
        release.wait(timeout=0.5)

    provider = CursorProvider(
        {"limits": {"provider": {"max_retries_per_call": 0}}},
        workspace=tmp_path,
        runner=slow_runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("producer", {"goal": "x"})
    provider.abort_turn(session_id)
    provider.resume_primary_session(session_id, {"goal": "follow-up"}, role="producer")
    stream = provider.stream_events(session_id)
    events: list[dict] = []

    def consume() -> None:
        for event in stream:
            events.append(event)

    thread = threading.Thread(target=consume)
    thread.start()
    _wait_for_runner_block(started)
    provider.abort_turn(session_id)
    block_second.set()
    release.set()
    thread.join(timeout=0.5)

    assert not thread.is_alive()
    assert all(event.get("type") != "assistant" for event in events)


def test_cursor_provider_abort_turn_before_durable_id_does_not_raise(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    started = threading.Event()
    release = threading.Event()

    def blocking_runner(argv: list[str], cwd: Path):
        started.set()
        release.wait(timeout=0.5)
        yield from ()

    provider = CursorProvider(
        {"limits": {"provider": {"max_retries_per_call": 0}}},
        workspace=tmp_path,
        runner=blocking_runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("producer", {"goal": "x"})
    provider.abort_turn(session_id)
    provider.resume_primary_session(session_id, {"goal": "follow-up"}, role="producer")
    stream = provider.stream_events(session_id)
    errors: list[BaseException] = []

    def consume() -> None:
        try:
            list(stream)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=consume)
    thread.start()
    _wait_for_runner_block(started)
    provider.abort_turn(session_id)
    release.set()
    thread.join(timeout=0.5)

    assert not thread.is_alive()
    assert errors == []


def test_cursor_provider_queue_turn_waits_for_stalled_collector(tmp_path: Path) -> None:
    import json

    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    started = threading.Event()
    release = threading.Event()
    durable_id = "chat-producer-stall"

    def stalling_runner(argv: list[str], cwd: Path):
        yield json.dumps(
            {
                "type": "system",
                "subtype": "init",
                "session_id": durable_id,
            }
        )
        started.set()
        release.wait(timeout=0.5)
        yield json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "session_id": durable_id,
                "is_error": False,
                "result": "done",
            }
        )

    provider = CursorProvider(
        {"limits": {"provider": {"max_retries_per_call": 0}}},
        workspace=tmp_path,
        runner=stalling_runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("producer", {"goal": "x"})
    provider.abort_turn(session_id)
    provider.resume_primary_session(session_id, {"goal": "turn-1"}, role="producer")

    errors: list[BaseException] = []

    def consume() -> None:
        try:
            list(provider.stream_events(session_id))
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=consume)
    thread.start()
    _wait_for_runner_block(started)
    provider.abort_turn(session_id)
    provider.resume_primary_session(session_id, {"goal": "turn-2"}, role="producer")
    release.set()
    thread.join(timeout=0.5)

    assert not thread.is_alive()
    assert errors == []
    assert provider._sessions[durable_id].pending_argv is not None


def test_cursor_provider_wait_turn_settled_after_abort(tmp_path: Path) -> None:
    import json

    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    started = threading.Event()
    release = threading.Event()
    durable_id = "chat-producer-abort-wait"

    def stalling_runner(argv: list[str], cwd: Path):
        yield json.dumps(
            {
                "type": "system",
                "subtype": "init",
                "session_id": durable_id,
            }
        )
        started.set()
        release.wait(timeout=0.5)
        yield json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "session_id": durable_id,
                "is_error": False,
                "result": "done",
            }
        )

    provider = CursorProvider(
        {"limits": {"provider": {"max_retries_per_call": 0}}},
        workspace=tmp_path,
        runner=stalling_runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("producer", {"goal": "x"})
    provider.abort_turn(session_id)
    provider.resume_primary_session(session_id, {"goal": "turn-1"}, role="producer")

    def consume() -> None:
        list(provider.stream_events(session_id))

    thread = threading.Thread(target=consume)
    thread.start()
    _wait_for_runner_block(started)
    provider.abort_turn(session_id)
    provider.wait_turn_settled(session_id)
    release.set()
    thread.join(timeout=0.5)

    assert not thread.is_alive()
    session = provider._sessions[durable_id]
    assert not session.turn_running
    assert session.collector_thread is None or not session.collector_thread.is_alive()
