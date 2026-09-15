"""Zero-output Cursor startup is a non-retryable protocol failure."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core_tools.provider import CursorProvider, ProviderTurnError, ProviderTurnStartupError


def _provider(tmp_path: Path, runner, *, retries: int = 5, events=None):
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    seen: list[dict] = []
    provider = CursorProvider(
        {
            "provider": {"name": "cursor", "model": "composer-2.5"},
            "limits": {"provider": {"max_retries_per_call": retries}},
        },
        workspace=tmp_path,
        runner=runner,
        binary=str(agent_path),
        skip_probe=True,
        on_provider_event=lambda event: seen.append(event),
    )
    if events is not None:
        events.extend(seen)
        provider._on_provider_event = lambda event: events.append(event)
    return provider, seen


def test_zero_output_startup_raises_typed_error_and_is_not_retried(tmp_path: Path) -> None:
    attempts = {"count": 0}

    def empty_runner(argv: list[str], cwd: Path):
        attempts["count"] += 1
        return iter(())

    events: list[dict] = []
    provider, _seen = _provider(tmp_path, empty_runner, retries=5, events=events)
    session_id = provider.start_reviewer_session(
        {
            "loop_id": "review-01",
            "protocol_instructions": "Submit the decision through tdp agent review respond.",
            "secret_should_not_log": "PROMPT-SECRET-BODY",
        }
    )
    with pytest.raises(ProviderTurnStartupError) as exc_info:
        list(provider.stream_events(session_id))

    error = exc_info.value
    assert attempts["count"] == 1
    diagnostics = error.diagnostics
    assert diagnostics["prompt_bytes"] > 0
    assert diagnostics["argv_count"] >= 2
    assert diagnostics["argv_bytes"] >= diagnostics["prompt_bytes"]
    assert diagnostics["new_session"] is True
    assert diagnostics["zero_output"] is True
    assert "role" in diagnostics
    assert "kind" in diagnostics
    assert "model" in diagnostics
    dumped = json.dumps({"error": str(error), "diagnostics": diagnostics, "events": events})
    assert "PROMPT-SECRET-BODY" not in dumped
    assert "Submit the decision through tdp agent review respond." not in dumped
    for event in events:
        encoded = json.dumps(event)
        assert "PROMPT-SECRET-BODY" not in encoded
        if event.get("type") in {"error", "retry"}:
            assert "prompt_bytes" in event
            assert "argv_bytes" in event


def test_transient_turn_errors_before_remote_activity_are_still_retried(
    tmp_path: Path,
) -> None:
    attempts = {"count": 0}
    stream_lines = [
        json.dumps(
            {
                "type": "system",
                "subtype": "init",
                "session_id": "chat-retry",
            }
        ),
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "session_id": "chat-retry",
                "is_error": False,
                "result": "ok",
            }
        ),
    ]

    def flaky_runner(argv: list[str], cwd: Path):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise ProviderTurnError("transient failure")
        for line in stream_lines:
            yield line

    provider, _seen = _provider(tmp_path, flaky_runner, retries=2)
    session_id = provider.start_primary_session("planner", {"goal": "build"})
    list(provider.stream_events(session_id))
    assert attempts["count"] == 2
    assert provider.canonical_session_id(session_id) == "chat-retry"
