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
    format_provider_model_name,
    enrich_provider_observability_event,
    normalize_cursor_event,
    resolve_agent_binary,
    resolve_provider_cli_model,
)
from core_tools.provider.events import (
    format_manifest_prompt,
    format_request_prompt,
    format_tool_call_summary,
    is_tool_call_end,
    is_tool_call_start,
)


def test_format_manifest_prompt_surfaces_protocol_instructions() -> None:
    prompt = format_manifest_prompt(
        "planner",
        {
            "phase": "planning",
            "protocol_instructions": [
                "Mutate plan state only through tdp agent plan commands.",
                "Do not use host planning modes.",
            ],
        },
    )

    assert prompt.startswith("Role: planner\n\nProtocol:\n")
    assert "- Mutate plan state only through tdp agent plan commands." in prompt
    assert "- Do not use host planning modes." in prompt
    assert "\nContext manifest:\n" in prompt
    assert '"phase": "planning"' in prompt


def test_format_manifest_prompt_surfaces_advisory_guidance() -> None:
    prompt = format_manifest_prompt(
        "producer",
        {
            "phase": "production",
            "protocol_instructions": ["Record batches through tdp agent production."],
            "agent_context": {
                "role": "producer",
                "guidance": [
                    "Work in coherent batches.",
                    "Commit when the checkpoint is useful.",
                ],
                "resources": [],
                "skills": [],
            },
        },
    )

    assert "\nProtocol:\n" in prompt
    assert "\nAdvisory role guidance:\n" in prompt
    assert "- Work in coherent batches." in prompt
    assert "- Commit when the checkpoint is useful." in prompt
    assert prompt.index("Advisory role guidance:") < prompt.index("Context manifest:")
    assert '"guidance"' in prompt


def test_format_request_prompt_surfaces_protocol_and_role_from_agent_context() -> None:
    prompt = format_request_prompt(
        {
            "phase": "whole_plan_review",
            "agent_context": {"role": "reviewer"},
            "protocol_instructions": [
                "Submit decisions only through tdp agent review respond.",
            ],
        },
    )

    assert prompt.startswith("Role: reviewer\n\nProtocol:\n")
    assert "- Submit decisions only through tdp agent review respond." in prompt
    assert "\nRequest:\n" in prompt
    assert '"phase": "whole_plan_review"' in prompt


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
    argv = build_agent_argv(
        {},
        binary="/fake/agent",
        workspace=tmp_path,
        session_id="provider-chat-1",
        prompt="Plan the work",
        model="composer-2.5",
    )
    assert argv[:9] == [
        "/fake/agent",
        "--print",
        "--output-format",
        "stream-json",
        "--trust",
        "--approve-mcps",
        "--force",
        "--workspace",
        str(tmp_path),
    ]
    assert "--model" in argv
    assert argv[argv.index("--model") + 1] == "composer-2.5"
    assert "--resume" in argv
    assert argv[argv.index("--resume") + 1] == "provider-chat-1"
    assert argv[-1] == "Plan the work"


def test_build_agent_argv_omits_resume_for_transient_pending_session(tmp_path: Path) -> None:
    argv = build_agent_argv(
        {},
        binary="/fake/agent",
        workspace=tmp_path,
        session_id="cursor-pending-1",
        prompt="Review the package",
    )
    assert "--resume" not in argv
    assert argv[-1] == "Review the package"


def test_cursor_reviewer_send_before_first_turn_omits_resume_for_pending_session(
    tmp_path: Path,
) -> None:
    captured_argv: list[list[str]] = []

    def fake_runner(argv: list[str], cwd: Path):
        captured_argv.append(argv)
        yield json.dumps(
            {
                "type": "system",
                "subtype": "init",
                "session_id": "chat-reviewer-1",
            }
        )
        yield json.dumps(
            {
                "type": "assistant",
                "session_id": "chat-reviewer-1",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "reviewed"}],
                },
            }
        )
        yield json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "session_id": "chat-reviewer-1",
                "is_error": False,
                "result": "reviewed",
            }
        )

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

    session_id = provider.start_reviewer_session({"loop_id": "review-01"})
    provider.send(session_id, {"action": "initial_review", "loop_id": "review-01"})
    list(provider.stream_events(session_id))

    assert len(captured_argv) == 1
    assert "--resume" not in captured_argv[0]
    assert provider.canonical_session_id(session_id) == "chat-reviewer-1"


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
    assert session_id == "cursor-pending-1"
    events = list(provider.stream_events(session_id))
    assert provider.canonical_session_id(session_id) == "chat-abc"
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


def test_normalize_cursor_event_maps_thinking_text_field() -> None:
    normalized = normalize_cursor_event(
        {
            "type": "thinking",
            "subtype": "extended",
            "session_id": "chat-1",
            "text": "Planning the work.",
        }
    )
    assert normalized is not None
    assert normalized["type"] == "thinking"
    assert normalized["text"] == "Planning the work."


def test_normalize_cursor_event_maps_assistant_text_field() -> None:
    normalized = normalize_cursor_event(
        {
            "type": "assistant",
            "session_id": "chat-1",
            "text": "Plan candidate ready.",
        }
    )
    assert normalized is not None
    assert normalized["text"] == "Plan candidate ready."


def test_normalize_cursor_event_skips_empty_thinking() -> None:
    assert normalize_cursor_event({"type": "thinking", "session_id": "chat-1"}) is None


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


def test_normalize_cursor_event_enriches_tool_call() -> None:
    normalized = normalize_cursor_event(
        {
            "type": "tool_call",
            "session_id": "chat-1",
            "tool": "plan_apply",
            "request": {"base_revision": 0, "operations": [{}, {}, {}]},
        }
    )
    assert normalized is not None
    assert normalized["tool"] == "plan_apply"
    assert normalized["subtype"] == "started"
    assert normalized["request"]["base_revision"] == 0
    assert normalized["summary"] == "plan_apply @r0 3 ops"


def test_normalize_cursor_event_formats_native_tool_call_details() -> None:
    normalized = normalize_cursor_event(
        {
            "type": "tool_call",
            "subtype": "started",
            "session_id": "chat-1",
            "call_id": "call_42",
            "tool_call": {
                "shellToolCall": {"args": {"command": "tdp agent plan snapshot"}},
            },
        }
    )
    assert normalized is not None
    assert normalized["tool"] == "shell"
    assert normalized["call_id"] == "call_42"
    assert normalized["summary"] == "shell: tdp agent plan snapshot"
    assert is_tool_call_start(normalized) is True


def test_normalize_cursor_event_dedupes_call_id_from_fc_id() -> None:
    normalized = normalize_cursor_event(
        {
            "type": "tool_call",
            "subtype": "started",
            "call_id": "call_bPgGmDNx1soGmKYA0hHy5zMy",
            "id": "fc_0fa0b760219b86b0016a6b6111c32081a3bb69b021a4e17163",
            "tool_call": {"grepToolCall": {"args": {"pattern": "plan_apply"}}},
        }
    )
    assert normalized is not None
    assert normalized["call_id"] == "call_bPgGmDNx1soGmKYA0hHy5zMy"
    assert format_tool_call_summary(normalized) == "grep plan_apply"


def test_normalize_cursor_event_normalizes_completed_tool_call() -> None:
    normalized = normalize_cursor_event(
        {
            "type": "tool_call",
            "subtype": "completed",
            "session_id": "chat-1",
            "call_id": "call_42",
            "tool_call": {
                "readToolCall": {"args": {"path": "README.md"}},
            },
        }
    )
    assert normalized is not None
    assert normalized["subtype"] == "completed"
    assert normalized["call_id"] == "call_42"
    assert normalized["summary"] == "read README.md"
    assert is_tool_call_end(normalized) is True
    assert is_tool_call_start(normalized) is False


def test_normalize_cursor_event_drops_tool_result() -> None:
    assert normalize_cursor_event(
        {
            "type": "tool_result",
            "session_id": "chat-1",
            "tool": "read",
            "is_error": False,
        }
    ) is None


def test_normalize_cursor_event_passes_through_error_text() -> None:
    normalized = normalize_cursor_event({"type": "error", "text": "provider crashed"})
    assert normalized is not None
    assert normalized["text"] == "provider crashed"


def test_normalize_cursor_event_passes_through_done() -> None:
    normalized = normalize_cursor_event(
        {
            "type": "done",
            "subtype": "success",
            "text": "ok",
            "is_error": False,
            "signal": "candidate_plan_ready",
        }
    )
    assert normalized is not None
    assert normalized["type"] == "done"
    assert normalized["signal"] == "candidate_plan_ready"


def test_normalize_cursor_event_passes_through_result_signal() -> None:
    normalized = normalize_cursor_event(
        {
            "type": "result",
            "subtype": "success",
            "result": "candidate_plan_ready",
            "is_error": False,
            "signal": "candidate_plan_ready",
        }
    )
    assert normalized is not None
    assert normalized["type"] == "done"
    assert normalized["signal"] == "candidate_plan_ready"


def test_format_tool_call_summary_formats_cursor_grep() -> None:
    normalized = normalize_cursor_event(
        {
            "type": "tool_call",
            "subtype": "started",
            "tool_call": {"grepToolCall": {"args": {"pattern": "plan_apply"}}},
        }
    )
    assert normalized is not None
    assert format_tool_call_summary(normalized) == "grep plan_apply"


def test_stub_emits_events_when_stream_events_drains_turn() -> None:
    seen: list[str] = []
    provider = StubProvider(
        on_provider_event=lambda event: seen.append(str(event.get("type")))
    )
    provider.script_turn(
        [
            {"type": "assistant", "text": "hello"},
            {"type": "done", "subtype": "success", "text": "ok", "is_error": False},
        ]
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    assert seen == ["assistant", "done"]
    drained: list[str] = []
    for event in provider.stream_events(session_id):
        drained.append(str(event.get("type")))
    assert drained == ["assistant", "done"]


def test_cursor_provider_emits_events_during_stream_events(tmp_path: Path) -> None:
    seen: list[str] = []
    stream_lines = [
        json.dumps(
            {
                "type": "assistant",
                "session_id": "chat-live",
                "message": {"content": "working"},
            }
        ),
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "session_id": "chat-live",
                "is_error": False,
                "result": "ok",
            }
        ),
    ]

    def runner(argv: list[str], cwd: Path):
        for line in stream_lines:
            yield line

    config = {"provider": {"name": "cursor"}, "limits": {"provider": {"max_retries_per_call": 0}}}
    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        config,
        workspace=tmp_path,
        runner=runner,
        binary=str(agent_path),
        skip_probe=True,
        on_provider_event=lambda event: seen.append(str(event.get("type"))),
    )
    session_id = provider.start_primary_session("planner", {"goal": "build"})
    assert session_id == "cursor-pending-1"
    assert seen == []
    list(provider.stream_events(session_id))
    assert seen == ["assistant", "done"]
    assert provider.canonical_session_id(session_id) == "chat-live"


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
    list(provider.stream_events(session_id))
    assert provider.canonical_session_id(session_id) == "chat-retry"
    assert attempts["count"] == 2


def test_cursor_provider_emits_retry_events(tmp_path: Path) -> None:
    seen: list[str] = []
    attempts = {"count": 0}

    def flaky_runner(argv: list[str], cwd: Path):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise ProviderTurnError("transient failure")
        yield json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "session_id": "chat-retry-emit",
                "is_error": False,
                "result": "ok",
            }
        )

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
        on_provider_event=lambda event: seen.append(str(event.get("type"))),
    )
    session_id = provider.start_primary_session("planner", {"goal": "build"})
    list(provider.stream_events(session_id))
    assert "retry" in seen


@pytest.mark.skipif(
    shutil.which("agent") is None and shutil.which("cursor-agent") is None,
    reason="Cursor CLI not installed",
)
def test_cursor_smoke_binary_probe() -> None:
    binary = resolve_agent_binary(None)
    assert binary


def test_build_agent_argv_explicit_model_overrides_provider_default(tmp_path: Path) -> None:
    argv = build_agent_argv(
        {},
        binary="/fake/agent",
        workspace=tmp_path,
        model="session-model",
    )
    assert argv[argv.index("--model") + 1] == "session-model"


def test_cursor_provider_stores_model_and_reuses_on_resume(tmp_path: Path) -> None:
    stream_lines = [
        json.dumps(
            {
                "type": "system",
                "subtype": "init",
                "session_id": "chat-model",
            }
        ),
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "session_id": "chat-model",
                "is_error": False,
                "result": "ok",
            }
        ),
    ]
    captured_argv: list[list[str]] = []

    def fake_runner(argv: list[str], cwd: Path):
        captured_argv.append(argv)
        for line in stream_lines:
            yield line

    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=fake_runner,
        binary=str(agent_path),
        skip_probe=True,
    )
    session_id = provider.start_primary_session(
        "planner",
        {"goal": "build"},
        model="planner-model",
    )
    assert provider.get_session_reference(session_id)["model"] == "planner-model"
    list(provider.stream_events(session_id))
    assert captured_argv[0][captured_argv[0].index("--model") + 1] == "planner-model"

    provider.send(session_id, {"action": "continue"})
    list(provider.stream_events(session_id))
    assert captured_argv[1][captured_argv[1].index("--model") + 1] == "planner-model"


def test_cursor_resume_primary_session_restores_after_terminate(tmp_path: Path) -> None:
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
                "type": "result",
                "subtype": "success",
                "session_id": "chat-abc",
                "is_error": False,
                "result": "ok",
            }
        ),
    ]
    captured_argv: list[list[str]] = []

    def fake_runner(argv: list[str], cwd: Path):
        captured_argv.append(argv)
        for line in stream_lines:
            yield line

    agent_path = tmp_path / "agent"
    agent_path.write_text("", encoding="utf-8")
    provider = CursorProvider(
        {},
        workspace=tmp_path,
        runner=fake_runner,
        binary=str(agent_path),
        skip_probe=True,
    )

    session_id = provider.start_primary_session("producer", {"goal": "build"})
    list(provider.stream_events(session_id))
    canonical_id = provider.canonical_session_id(session_id)
    assert canonical_id == "chat-abc"

    provider.terminate_all_sessions()
    provider.resume_primary_session(canonical_id, {"action": "address_review_findings"})
    list(provider.stream_events(canonical_id))

    assert captured_argv[1][captured_argv[1].index("--resume") + 1] == "chat-abc"


def test_resolve_provider_cli_model_skips_auto_and_blank() -> None:
    assert resolve_provider_cli_model(model=None) is None
    assert resolve_provider_cli_model(model="auto") is None
    assert resolve_provider_cli_model(model="  auto  ") is None
    assert resolve_provider_cli_model(model="reasoning-model") == "reasoning-model"


def test_format_provider_model_name_labels_auto() -> None:
    assert format_provider_model_name(None) == "auto"
    assert format_provider_model_name("auto") == "auto"
    assert format_provider_model_name("coding-model") == "coding-model"


def test_cursor_reviewer_turn_rejects_transient_only_stream_session_id(
    tmp_path: Path,
) -> None:
    stream_lines = [
        json.dumps(
            {
                "type": "system",
                "subtype": "init",
                "session_id": "cursor-pending-1",
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "session_id": "cursor-pending-1",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "reviewed"}],
                },
            }
        ),
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "session_id": "cursor-pending-1",
                "is_error": False,
                "result": "reviewed",
            }
        ),
    ]

    def fake_runner(argv: list[str], cwd: Path):
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

    session_id = provider.start_reviewer_session({"loop_id": "review-01"})
    assert session_id == "cursor-pending-1"
    with pytest.raises(ProviderTurnError, match="durable provider session id"):
        list(provider.stream_events(session_id))


def test_cursor_reviewer_turn_accepts_durable_session_id_on_init(
    tmp_path: Path,
) -> None:
    stream_lines = [
        json.dumps(
            {
                "type": "system",
                "subtype": "init",
                "session_id": "chat-reviewer-1",
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "session_id": "chat-reviewer-1",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "reviewed"}],
                },
            }
        ),
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "session_id": "chat-reviewer-1",
                "is_error": False,
                "result": "reviewed",
            }
        ),
    ]

    def fake_runner(argv: list[str], cwd: Path):
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

    session_id = provider.start_reviewer_session({"loop_id": "review-01"})
    list(provider.stream_events(session_id))
    assert provider.canonical_session_id(session_id) == "chat-reviewer-1"


def test_enrich_provider_observability_event_attaches_session_and_model() -> None:
    enriched = enrich_provider_observability_event(
        {"type": "assistant", "text": "hello"},
        session_id="session-1",
        model="coding-model",
    )
    assert enriched["session_id"] == "session-1"
    assert enriched["model"] == "coding-model"
    assert enriched["text"] == "hello"

    auto = enrich_provider_observability_event(
        {"type": "done", "subtype": "success"},
        session_id="session-2",
        model=None,
    )
    assert auto["model"] == "auto"

