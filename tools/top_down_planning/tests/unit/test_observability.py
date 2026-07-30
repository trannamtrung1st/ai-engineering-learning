"""Unit tests for Top Down Planning observability."""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.observability import ConsoleEvent
from core_tools.provider.events import normalize_cursor_event
from core_tools.provider.stub import StubProvider
from top_down_planning.observability import (
    ObservabilityContext,
    ObservabilityOptions,
    ProviderToConsoleBridge,
    build_observability_context,
    map_audit_event,
)
from tests.helpers import done_events


class _CollectSink:
    def __init__(self) -> None:
        self.events: list[ConsoleEvent] = []

    def emit(self, event: ConsoleEvent) -> None:
        self.events.append(event)


def _normalized_tool_call(**fields: object) -> dict:
    event = normalize_cursor_event({"type": "tool_call", **fields})
    assert event is not None
    return event


def test_map_audit_event_maps_planning_candidate_ready() -> None:
    mapped = map_audit_event(
        {
            "type": "planning_candidate_ready",
            "plan_revision": 2,
            "session_id": "planner-1",
        }
    )
    assert mapped is not None
    assert mapped.category == "state"
    assert mapped.fields["plan_revision"] == 2


def test_provider_bridge_streams_thinking_sentences_not_empty_lines() -> None:
    collector = _CollectSink()
    context = ObservabilityContext(sink=collector)
    bridge = ProviderToConsoleBridge(context)

    for chunk in ("Let me inspect the config.", " I'll read the schema next"):
        bridge.handle({"type": "thinking", "text": chunk})

    thinking = [event.message for event in collector.events if event.category == "thinking"]
    assert thinking == ["Let me inspect the config."]
    bridge.handle(_normalized_tool_call(tool="read", request={"path": "schema.md"}))
    thinking = [event.message for event in collector.events if event.category == "thinking"]
    assert thinking == ["Let me inspect the config.", "I'll read the schema next"]


def test_provider_bridge_ignores_empty_thinking_events() -> None:
    collector = _CollectSink()
    context = ObservabilityContext(sink=collector)
    bridge = ProviderToConsoleBridge(context)
    bridge.handle({"type": "thinking", "text": ""})
    bridge.handle({"type": "thinking"})
    assert collector.events == []


def test_provider_bridge_flushes_response_on_tool_call() -> None:
    collector = _CollectSink()
    context = ObservabilityContext(sink=collector)
    bridge = ProviderToConsoleBridge(context)

    bridge.handle({"type": "assistant", "text": "Partial reply"})
    bridge.handle(_normalized_tool_call(tool="read", request={"path": "README.md"}))

    response = [event.message for event in collector.events if event.category == "response"]
    assert response == ["Partial reply"]
    assert any(event.category == "tool:start" for event in collector.events)


def test_provider_bridge_streams_cumulative_thinking_chunks() -> None:
    collector = _CollectSink()
    context = ObservabilityContext(sink=collector)
    bridge = ProviderToConsoleBridge(context)

    bridge.handle({"type": "thinking", "text": "Hello"})
    bridge.handle({"type": "thinking", "text": "Hello world."})
    bridge.handle({"type": "thinking", "text": "Hello world. Done."})

    thinking = [event.message for event in collector.events if event.category == "thinking"]
    assert thinking == ["Hello world.", "Done."]


def test_provider_bridge_emits_tool_start_summary_only() -> None:
    collector = _CollectSink()
    context = ObservabilityContext(sink=collector)
    bridge = ProviderToConsoleBridge(context)
    bridge.handle(
        _normalized_tool_call(
            tool="plan_apply",
            request={"base_revision": 0, "operations": [{}, {}, {}]},
        )
    )
    assert [event.category for event in collector.events] == ["tool:start"]
    assert collector.events[0].message == "plan_apply @r0 3 ops"
    assert collector.events[0].fields == {}


def test_provider_bridge_emits_tool_end_for_completed_tool_calls() -> None:
    collector = _CollectSink()
    context = ObservabilityContext(sink=collector)
    bridge = ProviderToConsoleBridge(context)
    started = normalize_cursor_event(
        {
            "type": "tool_call",
            "subtype": "started",
            "call_id": "call-1",
            "tool_call": {"readToolCall": {"args": {"path": "src/app.ts"}}},
        }
    )
    completed = normalize_cursor_event(
        {
            "type": "tool_call",
            "subtype": "completed",
            "call_id": "call-1",
            "tool_call": {"readToolCall": {"args": {"path": "src/app.ts"}}},
        }
    )
    assert started is not None
    assert completed is not None
    bridge.handle(started)
    bridge.handle(completed)
    assert [event.category for event in collector.events] == ["tool:start", "tool:end"]
    assert collector.events[0].message == "read src/app.ts"
    assert collector.events[1].message == "read src/app.ts"


def test_provider_bridge_dedupes_duplicate_tool_call_start() -> None:
    collector = _CollectSink()
    context = ObservabilityContext(sink=collector)
    bridge = ProviderToConsoleBridge(context)
    started = normalize_cursor_event(
        {
            "type": "tool_call",
            "subtype": "started",
            "call_id": "call_bPgGmDNx1soGmKYA0hHy5zMy",
            "tool_call": {"grepToolCall": {"args": {"pattern": "plan_apply"}}},
        }
    )
    assert started is not None
    bridge.handle(started)
    bridge.handle(dict(started))
    tool_starts = [event for event in collector.events if event.category == "tool:start"]
    assert len(tool_starts) == 1
    assert tool_starts[0].message == "grep plan_apply"


def test_provider_bridge_clears_tool_start_dedup_on_done() -> None:
    collector = _CollectSink()
    context = ObservabilityContext(sink=collector)
    bridge = ProviderToConsoleBridge(context)
    started = normalize_cursor_event(
        {
            "type": "tool_call",
            "subtype": "started",
            "call_id": "call-9",
            "tool": "plan_apply",
            "request": {"base_revision": 0, "operations": [{}]},
        }
    )
    assert started is not None
    bridge.handle(started)
    bridge.handle(
        {
            "type": "done",
            "subtype": "success",
            "text": "ok",
            "is_error": False,
        }
    )
    bridge.handle(started)
    tool_starts = [event for event in collector.events if event.category == "tool:start"]
    assert len(tool_starts) == 2


def test_stub_provider_events_reach_bridge_before_stream_drain() -> None:
    collector = _CollectSink()
    context = ObservabilityContext(sink=collector)
    provider = StubProvider(on_provider_event=context.provider_callback())
    provider.script_turn(
        [
            {"type": "assistant", "text": "planning turn"},
            *done_events(signal="candidate_plan_ready"),
        ]
    )
    session_id = provider.start_primary_session("planner", {"goal": "x"})
    assert any(event.category == "response" for event in collector.events)
    drained = list(provider.stream_events(session_id))
    assert len(drained) == 3
    assert drained[-1]["type"] == "done"


def test_stdout_stderr_separation_for_stream_json(tmp_path: Path) -> None:
    stderr = io.StringIO()
    with patch("core_tools.observability.console.sys.stderr", stderr):
        context = build_observability_context(
            options=ObservabilityOptions(color="never"),
            run_id="run-test",
            run_dir=tmp_path / "run-test",
        )
        context.emit(ConsoleEvent(category="done", message="finished", run_id="run-test"))
        context.close()
    assert "finished" in stderr.getvalue()


def test_jsonl_log_format_writes_valid_json_to_stderr() -> None:
    stderr = io.StringIO()
    with patch("top_down_planning.observability.sys.stderr", stderr):
        context = build_observability_context(
            options=ObservabilityOptions(log_format="jsonl", color="never"),
            run_id="run-jsonl",
        )
        context.emit(
            ConsoleEvent(
                category="state",
                message="phase transition",
                fields={"phase": "planning"},
                run_id="run-jsonl",
            )
        )
        context.close()
    payload = json.loads(stderr.getvalue().strip())
    assert payload["category"] == "state"
    assert payload["run_id"] == "run-jsonl"


def test_secret_redaction_in_console_output() -> None:
    stderr = io.StringIO()
    token = "cap-abc123.deadbeef0123456789abcdef0123456789abcdef0123456789"
    with patch("core_tools.observability.console.sys.stderr", stderr):
        context = build_observability_context(
            options=ObservabilityOptions(color="never", log_level="trace"),
            run_id="run-secret",
        )
        context.emit(
            ConsoleEvent(
                category="tool:start",
                message="plan_apply @r0 1 ops",
                fields={"token": token},
                run_id="run-secret",
            )
        )
        context.close()
    assert token not in stderr.getvalue()
    assert "[REDACTED]" in stderr.getvalue()
