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


def test_map_audit_event_maps_run_created_to_run_start() -> None:
    mapped = map_audit_event({"type": "run_created", "run_id": "run-20260101T000001-000001"})
    assert mapped is not None
    assert mapped.category == "run:start"
    assert mapped.message == "run created"
    assert mapped.run_id == "run-20260101T000001-000001"


def test_map_audit_event_maps_phase_entry_blocked() -> None:
    mapped = map_audit_event(
        {
            "type": "phase_entry_blocked",
            "phase": "whole_output_review",
            "error_code": "digest_mismatch",
            "digest_kind": "context_spec",
            "expected_digest": "abcd1234...",
            "actual_digest": "00000000...",
        }
    )
    assert mapped is not None
    assert mapped.category == "error"
    assert mapped.message == "phase entry blocked"
    assert mapped.fields["digest_kind"] == "context_spec"


def test_map_audit_event_maps_planner_session_started_with_phase_and_role() -> None:
    mapped = map_audit_event(
        {
            "type": "planner_session_started",
            "run_id": "run-20260101T000001-000001",
            "session_id": "planner-1",
            "role": "planner",
            "phase": "planning",
            "model": "reasoning-model",
        }
    )
    assert mapped is not None
    assert mapped.category == "session:start"
    assert mapped.message == "planner session started"
    assert mapped.session_id == "planner-1"
    assert mapped.fields["phase"] == "planning"
    assert mapped.fields["role"] == "planner"
    assert mapped.fields["run_id"] == "run-20260101T000001-000001"
    assert mapped.fields["model"] == "reasoning-model"


def test_map_audit_event_maps_planner_session_resumed_with_phase_and_role() -> None:
    mapped = map_audit_event(
        {
            "type": "planner_session_resumed",
            "run_id": "run-20260101T000001-000001",
            "session_id": "planner-1",
            "role": "planner",
            "phase": "planning",
        }
    )
    assert mapped is not None
    assert mapped.category == "session:resume"
    assert mapped.message == "planner session resumed"
    assert mapped.session_id == "planner-1"


def test_map_audit_event_maps_reviewer_session_ended_with_phase_and_role() -> None:
    mapped = map_audit_event(
        {
            "type": "reviewer_session_ended",
            "run_id": "run-20260101T000001-000001",
            "session_id": "reviewer-1",
            "role": "reviewer",
            "phase": "whole_plan_review",
            "model": "reasoning-model",
            "loop_id": "review-whole-plan-01",
            "review_type": "whole_plan",
            "stage": "scope_review",
        }
    )
    assert mapped is not None
    assert mapped.category == "session:end"
    assert mapped.message == "reviewer session ended"
    assert mapped.session_id == "reviewer-1"
    assert mapped.fields["phase"] == "whole_plan_review"
    assert mapped.fields["loop_id"] == "review-whole-plan-01"
    assert mapped.fields["stage"] == "scope_review"
    assert mapped.fields["review_type"] == "whole_plan"


def test_map_audit_event_maps_whole_plan_review_started_to_review_start() -> None:
    mapped = map_audit_event(
        {
            "type": "whole_plan_review_started",
            "loop_id": "review-whole-plan-01",
            "review_type": "whole_plan",
            "target_revision": 24,
        }
    )
    assert mapped is not None
    assert mapped.category == "review:start"
    assert mapped.message == "whole-plan review loop started"
    assert mapped.fields["review_type"] == "whole_plan"


def test_map_audit_event_maps_scope_review_started_to_review_stage() -> None:
    mapped = map_audit_event(
        {
            "type": "whole_plan_scope_review_started",
            "loop_id": "review-whole-plan-02",
            "review_type": "whole_plan",
            "stage": "scope_review",
            "scope_review_rounds": 1,
            "target_revision": 24,
        }
    )
    assert mapped is not None
    assert mapped.category == "review:stage"
    assert mapped.message == "scope review started"
    assert mapped.fields["stage"] == "scope_review"


def test_map_audit_event_maps_reviewer_session_started_with_stage() -> None:
    mapped = map_audit_event(
        {
            "type": "reviewer_session_started",
            "run_id": "run-20260101T000001-000001",
            "session_id": "reviewer-1",
            "role": "reviewer",
            "phase": "whole_plan_review",
            "model": "auto",
            "loop_id": "review-whole-plan-01",
            "review_type": "whole_plan",
            "stage": "initial_review",
        }
    )
    assert mapped is not None
    assert mapped.category == "session:start"
    assert mapped.fields["phase"] == "whole_plan_review"
    assert mapped.fields["stage"] == "initial_review"
    assert mapped.fields["review_type"] == "whole_plan"


def test_map_audit_event_maps_scope_review_changes_requested() -> None:
    mapped = map_audit_event(
        {
            "type": "whole_plan_scope_review_changes_requested",
            "loop_id": "review-whole-plan-01",
            "review_type": "whole_plan",
            "stage": "scope_review",
            "finding_count": 2,
        }
    )
    assert mapped is not None
    assert mapped.category == "review"
    assert mapped.message == "scope review changes requested"
    assert mapped.fields["stage"] == "scope_review"


def test_map_audit_event_requires_role_and_phase_for_session_start() -> None:
    assert map_audit_event(
        {
            "type": "planner_session_started",
            "run_id": "run-20260101T000001-000001",
            "session_id": "planner-1",
        }
    ) is None


def test_session_lifecycle_event_builds_start_and_end() -> None:
    from top_down_planning.observability import session_lifecycle_event

    started = session_lifecycle_event(
        category="session:start",
        role="planner",
        phase="planning",
        session_id="planner-1",
        run_id="run-20260101T000001-000001",
        model="reasoning-model",
    )
    ended = session_lifecycle_event(
        category="session:end",
        role="planner",
        phase="planning",
        session_id="planner-1",
        run_id="run-20260101T000001-000001",
        kind="primary",
        model="reasoning-model",
    )
    assert started.category == "session:start"
    assert started.message == "planner session started"
    assert started.fields["model"] == "reasoning-model"
    assert ended.category == "session:end"
    assert ended.message == "planner session ended"
    assert ended.fields["kind"] == "primary"
    assert ended.fields["model"] == "reasoning-model"


def test_provider_bridge_streams_thinking_deltas_not_empty_lines() -> None:
    collector = _CollectSink()
    context = ObservabilityContext(sink=collector)
    bridge = ProviderToConsoleBridge(context)

    for chunk in ("Let me inspect the config.", " I'll read the schema next"):
        bridge.handle({"type": "thinking", "text": chunk})

    thinking = [event.message for event in collector.events if event.category == "thinking"]
    assert thinking == ["Let me inspect the config.", " I'll read the schema next"]
    bridge.handle(_normalized_tool_call(tool="read", request={"path": "schema.md"}))
    thinking = [event.message for event in collector.events if event.category == "thinking"]
    assert thinking == ["Let me inspect the config.", " I'll read the schema next"]


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
    assert thinking == ["Hello", " world.", " Done."]


def test_provider_bridge_emits_tool_start_summary_only() -> None:
    collector = _CollectSink()
    context = ObservabilityContext(sink=collector)
    bridge = ProviderToConsoleBridge(context)
    event = _normalized_tool_call(
        tool="plan_apply",
        request={"base_revision": 0, "operations": [{}, {}, {}]},
        session_id="planner-1",
    )
    event["model"] = "reasoning-model"
    bridge.handle(event)
    assert [event.category for event in collector.events] == ["tool:start"]
    assert collector.events[0].message == "plan_apply @r0 3 ops"
    assert collector.events[0].fields == {"model": "reasoning-model"}


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


def test_stub_provider_events_reach_bridge_when_stream_events_drains_turn() -> None:
    collector = _CollectSink()
    context = ObservabilityContext(sink=collector)
    provider = StubProvider(on_provider_event=context.provider_callback())
    provider.script_turn(
        [
            {"type": "assistant", "text": "planning turn"},
            *done_events(signal="candidate_plan_ready"),
        ]
    )
    session_id = provider.start_primary_session(
        "planner",
        {"goal": "x"},
        model="reasoning-model",
    )
    assert any(event.category == "response" for event in collector.events)
    drained = list(provider.stream_events(session_id))
    assert len(drained) == 3
    assert any(event.get("type") == "assistant" for event in drained)
    assert drained[-1]["type"] == "done"


def test_stdout_stderr_separation_for_stream_json(tmp_path: Path) -> None:
    stderr = io.StringIO()
    with patch("core_tools.observability.console.sys.stderr", stderr):
        context = build_observability_context(
            options=ObservabilityOptions(color="never"),
            run_id="run-20260101T001001-001001",
            run_dir=tmp_path / "run-20260101T001001-001001",
        )
        context.emit(ConsoleEvent(category="done", message="finished", run_id="run-20260101T001001-001001"))
        context.close()
    assert "finished" in stderr.getvalue()


def test_jsonl_log_format_writes_valid_json_to_stderr() -> None:
    stderr = io.StringIO()
    with patch("top_down_planning.observability.sys.stderr", stderr):
        context = build_observability_context(
            options=ObservabilityOptions(log_format="jsonl", color="never"),
            run_id="run-20260101T001002-001002",
        )
        context.emit(
            ConsoleEvent(
                category="state",
                message="phase transition",
                fields={"phase": "planning"},
                run_id="run-20260101T001002-001002",
            )
        )
        context.close()
    payload = json.loads(stderr.getvalue().strip())
    assert payload["category"] == "state"
    assert payload["run_id"] == "run-20260101T001002-001002"


def test_secret_redaction_in_console_output() -> None:
    stderr = io.StringIO()
    token = "cap-abc123.deadbeef0123456789abcdef0123456789abcdef0123456789"
    with patch("core_tools.observability.console.sys.stderr", stderr):
        context = build_observability_context(
            options=ObservabilityOptions(color="never", log_level="trace"),
            run_id="run-20260101T001003-001003",
        )
        context.emit(
            ConsoleEvent(
                category="tool:start",
                message="plan_apply @r0 1 ops",
                fields={"token": token},
                run_id="run-20260101T001003-001003",
            )
        )
        context.close()
    assert token not in stderr.getvalue()
    assert "[REDACTED]" in stderr.getvalue()


def test_build_observability_context_truncates_response_when_configured(tmp_path: Path) -> None:
    stderr = io.StringIO()
    with patch("core_tools.observability.console.sys.stderr", stderr):
        context = build_observability_context(
            options=ObservabilityOptions(
                color="never",
                max_message_length=40,
            ),
            run_id="run-20260101T001004-001004",
            run_dir=tmp_path,
        )
        context.emit(
            ConsoleEvent(
                category="response",
                message="x" * 100,
                run_id="run-20260101T001004-001004",
            )
        )
        context.close()
    output = stderr.getvalue()
    assert output.endswith("...")
    assert len(output.split("[response] ", 1)[1]) == 40


def test_provider_bridge_truncates_tool_summary_when_configured() -> None:
    collector = _CollectSink()
    context = ObservabilityContext(
        sink=collector,
        options=ObservabilityOptions(max_tool_summary_length=20),
    )
    bridge = ProviderToConsoleBridge(context)
    long_command = "tdp agent review respond " + ("x" * 80)
    started = normalize_cursor_event(
        {
            "type": "tool_call",
            "subtype": "started",
            "call_id": "call-long",
            "tool_call": {"shellToolCall": {"args": {"command": long_command}}},
        }
    )
    assert started is not None
    bridge.handle(started)
    assert collector.events[0].message.endswith("...")
    assert len(collector.events[0].message) == 20


def test_provider_bridge_keeps_full_tool_summary_by_default() -> None:
    collector = _CollectSink()
    context = ObservabilityContext(sink=collector)
    bridge = ProviderToConsoleBridge(context)
    long_path = "/very/long/path/" + ("segment/" * 20) + "file.ts"
    started = normalize_cursor_event(
        {
            "type": "tool_call",
            "subtype": "started",
            "call_id": "call-path",
            "tool_call": {"readToolCall": {"args": {"path": long_path}}},
        }
    )
    assert started is not None
    bridge.handle(started)
    assert collector.events[0].message == f"read {long_path}"
