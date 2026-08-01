"""Tests for Cursor session-not-found classification."""

from __future__ import annotations

import json

import pytest

from core_tools.provider import (
    CursorProvider,
    ProviderSessionNotFoundError,
    ProviderTurnError,
)
from core_tools.provider.cursor_session_errors import (
    classify_cursor_session_failure,
    cursor_message_indicates_session_not_found,
)


@pytest.mark.parametrize(
    "message",
    [
        "session not found",
        "Error: Session not found for id chat-abc",
        "unknown session id: chat-abc",
        "could not resume session chat-abc",
        "chat session not found",
    ],
)
def test_cursor_message_indicates_session_not_found(message: str) -> None:
    assert cursor_message_indicates_session_not_found(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "transient network failure",
        "rate limit exceeded",
        "permission denied",
        "",
    ],
)
def test_cursor_message_does_not_classify_generic_failures(message: str) -> None:
    assert cursor_message_indicates_session_not_found(message) is False


def test_classify_cursor_session_failure_returns_typed_error() -> None:
    exc = classify_cursor_session_failure(
        "session not found",
        session_id="chat-missing",
    )
    assert isinstance(exc, ProviderSessionNotFoundError)
    assert exc.provider == "cursor"
    assert exc.session_id == "chat-missing"


def test_cursor_provider_raises_session_not_found_from_cli_stderr(tmp_path) -> None:
    def missing_session_runner(argv: list[str], cwd):
        raise ProviderTurnError("Cursor CLI failed: session not found")

    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=missing_session_runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "build"})
    with pytest.raises(ProviderSessionNotFoundError) as exc_info:
        list(provider.stream_events(session_id))
    assert exc_info.value.provider == "cursor"
    assert exc_info.value.session_id == session_id


def test_cursor_provider_raises_session_not_found_from_stream_error_event(tmp_path) -> None:
    stream_lines = [
        json.dumps(
            {
                "type": "error",
                "session_id": "chat-missing",
                "message": "session not found",
            }
        ),
    ]

    def runner(argv: list[str], cwd):
        for line in stream_lines:
            yield line

    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "build"})
    with pytest.raises(ProviderSessionNotFoundError):
        list(provider.stream_events(session_id))


def test_cursor_provider_keeps_generic_turn_errors(tmp_path) -> None:
    def failing_runner(argv: list[str], cwd):
        raise ProviderTurnError("Cursor CLI failed: rate limit exceeded")

    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=failing_runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session("planner", {"goal": "build"})
    with pytest.raises(ProviderTurnError, match="rate limit"):
        list(provider.stream_events(session_id))
