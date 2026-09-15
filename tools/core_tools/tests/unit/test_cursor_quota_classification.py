"""Quota / action-required classification across Cursor failure surfaces."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core_tools.provider import (
    CursorProvider,
    ProviderActionRequiredError,
    ProviderSessionNotFoundError,
    ProviderTurnError,
)
from core_tools.provider.cursor_session_errors import (
    ACTION_REQUIRED_QUOTA_EXHAUSTED,
    classify_cursor_failure,
    classify_cursor_session_failure,
    cursor_message_indicates_quota_exhausted,
    reclassify_provider_turn_error,
)

INCIDENT_QUOTA_MESSAGE = (
    "Increase limits for faster responses You're out of usage. "
    "Switch to Auto, or ask your admin to increase your limit to continue."
)


def _provider(tmp_path: Path, runner) -> CursorProvider:
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    return CursorProvider(
        {"limits": {"provider": {"max_retries_per_call": 0}}},
        workspace=tmp_path,
        runner=runner,
        binary=str(agent_path),
        skip_probe=True,
    )


@pytest.mark.parametrize(
    "message",
    [
        INCIDENT_QUOTA_MESSAGE,
        "You're out of usage",
        "you are out of usage",
        "quota exhausted",
        "quota exceeded",
    ],
)
def test_incident_wording_classifies_as_quota_exhausted(message: str) -> None:
    assert cursor_message_indicates_quota_exhausted(message) is True
    classified = classify_cursor_failure(message, session_id="chat-1")
    assert isinstance(classified, ProviderActionRequiredError)
    assert classified.reason == ACTION_REQUIRED_QUOTA_EXHAUSTED
    assert classified.session_id == "chat-1"


@pytest.mark.parametrize(
    "message",
    [
        "rate limit exceeded",
        "transient network failure",
        "permission denied",
        "increase the max_items_added limit",
        "hit the configured limit",
        "session not found",
        "",
    ],
)
def test_quota_classifier_does_not_match_generic_limit_or_session_messages(
    message: str,
) -> None:
    assert cursor_message_indicates_quota_exhausted(message) is False


def test_session_not_found_still_wins_over_quota_classifier() -> None:
    message = "session not found"
    assert classify_cursor_session_failure(message, session_id="chat-x") is not None
    classified = classify_cursor_failure(message, session_id="chat-x")
    assert isinstance(classified, ProviderSessionNotFoundError)


def test_reclassify_maps_cli_stderr_quota_to_action_required() -> None:
    exc = ProviderTurnError(f"Cursor CLI failed: {INCIDENT_QUOTA_MESSAGE}")
    classified = reclassify_provider_turn_error(exc, session_id="chat-1")
    assert isinstance(classified, ProviderActionRequiredError)
    assert classified.reason == ACTION_REQUIRED_QUOTA_EXHAUSTED


def test_cursor_provider_raises_quota_from_cli_stderr(tmp_path: Path) -> None:
    def failing_runner(argv: list[str], cwd):
        raise ProviderTurnError(f"Cursor CLI failed: {INCIDENT_QUOTA_MESSAGE}")

    provider = _provider(tmp_path, failing_runner)
    session_id = provider.start_primary_session("planner", {"goal": "build"})
    with pytest.raises(ProviderActionRequiredError) as exc_info:
        list(provider.stream_events(session_id))
    assert exc_info.value.reason == ACTION_REQUIRED_QUOTA_EXHAUSTED
    assert exc_info.value.session_id == session_id


def test_cursor_provider_raises_quota_from_stream_error_event(tmp_path: Path) -> None:
    def runner(argv: list[str], cwd):
        yield json.dumps(
            {
                "type": "system",
                "subtype": "init",
                "session_id": "chat-quota",
            }
        )
        yield json.dumps(
            {
                "type": "error",
                "session_id": "chat-quota",
                "message": INCIDENT_QUOTA_MESSAGE,
            }
        )

    provider = _provider(tmp_path, runner)
    session_id = provider.start_primary_session("planner", {"goal": "build"})
    with pytest.raises(ProviderActionRequiredError) as exc_info:
        list(provider.stream_events(session_id))
    assert exc_info.value.reason == ACTION_REQUIRED_QUOTA_EXHAUSTED


def test_cursor_provider_raises_quota_from_terminal_result_is_error(
    tmp_path: Path,
) -> None:
    def runner(argv: list[str], cwd):
        yield json.dumps(
            {
                "type": "assistant",
                "session_id": "chat-quota",
                "message": {"content": [{"type": "text", "text": "starting"}]},
            }
        )
        yield json.dumps(
            {
                "type": "result",
                "subtype": "error",
                "is_error": True,
                "session_id": "chat-quota",
                "result": INCIDENT_QUOTA_MESSAGE,
            }
        )
        yield json.dumps({"type": "system", "subtype": "keepalive"})

    provider = _provider(tmp_path, runner)
    session_id = provider.start_primary_session("planner", {"goal": "build"})
    with pytest.raises(ProviderActionRequiredError) as exc_info:
        list(provider.stream_events(session_id))
    assert exc_info.value.reason == ACTION_REQUIRED_QUOTA_EXHAUSTED
