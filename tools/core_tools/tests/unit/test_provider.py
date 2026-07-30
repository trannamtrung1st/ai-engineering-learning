"""Unit tests for provider adapters (stub + Cursor argv construction)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from core_tools.provider import (
    CursorProvider,
    ProviderBinaryNotFoundError,
    ProviderTurnError,
    StubProvider,
    build_agent_argv,
    create_provider,
    normalize_cursor_event,
    resolve_agent_binary,
)


def test_stub_start_send_stream_round_trip() -> None:
    provider = StubProvider()
    provider.script_turn(
        [
            {"type": "assistant", "text": "plan candidate"},
            {"type": "done", "subtype": "success", "text": "plan candidate", "is_error": False},
        ]
    )

    session_id = provider.start_primary_session(
        "planner",
        {"output_goal": "Ship feature", "stop_hint": "Stop when ready."},
    )
    events = list(provider.stream_events(session_id))
    assert any(event.get("type") == "assistant" for event in events)
    assert events[-1]["type"] == "done"

    provider.script_turn(
        [
            {"type": "assistant", "text": "revision applied"},
            {"type": "done", "subtype": "success", "text": "revision applied", "is_error": False},
        ]
    )
    provider.send(session_id, {"action": "revise", "note": "add tests"})
    follow_up = list(provider.stream_events(session_id))
    assert follow_up[0]["text"] == "revision applied"

    ref = provider.get_session_reference(session_id)
    assert ref["provider"] == "stub"
    assert ref["turn_count"] == 2


def test_stub_resume_primary_session_keeps_same_session_id() -> None:
    provider = StubProvider()
    provider.script_turn(
        [
            {"type": "assistant", "text": "started"},
            {"type": "done", "subtype": "success", "text": "started", "is_error": False},
        ]
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    list(provider.stream_events(session_id))

    provider.script_turn(
        [
            {"type": "assistant", "text": "resumed"},
            {"type": "done", "subtype": "success", "text": "resumed", "is_error": False},
        ]
    )
    provider.resume_primary_session(session_id, {"action": "continue"})
    events = list(provider.stream_events(session_id))
    assert events[0]["text"] == "resumed"
    assert provider.get_session_reference(session_id)["turn_count"] == 2


def test_create_provider_selects_stub_from_config(tmp_path: Path) -> None:
    config = {"provider": {"name": "stub"}}
    provider = create_provider(config, workspace=tmp_path)
    assert isinstance(provider, StubProvider)


def test_build_agent_argv_shape_with_fake_runner(tmp_path: Path) -> None:
    config = {"provider": {"model": "composer-2.5"}}
    argv = build_agent_argv(
        config,
        binary="/fake/agent",
        workspace=tmp_path,
        session_id="provider-chat-1",
        prompt="Plan the work",
    )
    assert argv[:8] == [
        "/fake/agent",
        "--print",
        "--output-format",
        "stream-json",
        "--trust",
        "--approve-mcps",
        "--workspace",
        str(tmp_path),
    ]
    assert "--model" in argv
    assert argv[argv.index("--model") + 1] == "composer-2.5"
    assert "--resume" in argv
    assert argv[argv.index("--resume") + 1] == "provider-chat-1"
    assert argv[-1] == "Plan the work"


def test_cursor_provider_uses_injected_runner(tmp_path: Path) -> None:
    stream_lines = [
        json.dumps(
            {
                "type": "system",
                "subtype": "init",
                "session_id": "chat-abc",
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "session_id": "chat-abc",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "hello"}],
                },
            }
        ),
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "session_id": "chat-abc",
                "is_error": False,
                "result": "hello",
            }
        ),
    ]
    captured_argv: list[list[str]] = []

    def fake_runner(argv: list[str], cwd: Path):
        captured_argv.append(argv)
        for line in stream_lines:
            yield line

    config = {"provider": {"name": "cursor"}}
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        config,
        workspace=tmp_path,
        runner=fake_runner,
        binary=str(agent_path),
        skip_probe=True,
    )

    session_id = provider.start_primary_session("planner", {"goal": "build"})
    assert session_id == "chat-abc"
    events = list(provider.stream_events(session_id))
    assert captured_argv[0][0].endswith("agent")
    assert "--workspace" in captured_argv[0]
    assert "--resume" not in captured_argv[0]
    assert events[0]["type"] == "system"
    assert any(event.get("type") == "assistant" for event in events)
    assert events[-1]["type"] == "done"

    ref = provider.get_session_reference(session_id)
    assert ref["session_id"] == "chat-abc"


def test_stub_missing_script_raises() -> None:
    provider = StubProvider()
    with pytest.raises(ProviderTurnError, match="no scripted provider turn"):
        provider.start_primary_session("planner", {"goal": "x"})


def test_normalize_cursor_event_maps_result_to_done() -> None:
    normalized = normalize_cursor_event(
        {
            "type": "result",
            "subtype": "success",
            "session_id": "chat-1",
            "is_error": False,
            "result": "ok",
        }
    )
    assert normalized is not None
    assert normalized["type"] == "done"
    assert normalized["text"] == "ok"


def test_resolve_agent_binary_missing_raises() -> None:
    with pytest.raises(ProviderBinaryNotFoundError):
        resolve_agent_binary("/nonexistent/agent-binary")


def test_cursor_provider_retries_transient_turn_errors(tmp_path: Path) -> None:
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

    config = {
        "provider": {"name": "cursor"},
        "limits": {"provider": {"max_retries_per_call": 2}},
    }
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        config,
        workspace=tmp_path,
        runner=flaky_runner,
        binary=str(agent_path),
        skip_probe=True,
    )

    session_id = provider.start_primary_session("planner", {"goal": "build"})
    assert session_id == "chat-retry"
    assert attempts["count"] == 2


@pytest.mark.skipif(
    shutil.which("agent") is None and shutil.which("cursor-agent") is None,
    reason="Cursor CLI not installed",
)
def test_cursor_smoke_binary_probe() -> None:
    binary = resolve_agent_binary(None)
    assert binary

