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
from top_down_planning.persistence import FileRunStore
from tests.conftest import run_cli
from tests.helpers import apply_plan, done_events, only_run_id, with_root_contract, write_config


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


def test_map_audit_event_maps_planner_session_ended_with_phase_and_role() -> None:
    mapped = map_audit_event(
        {
            "type": "planner_session_ended",
            "run_id": "run-20260101T000001-000001",
            "session_id": "planner-1",
            "role": "planner",
            "phase": "planning",
            "model": "auto",
        }
    )
    assert mapped is not None
    assert mapped.category == "session:end"
    assert mapped.message == "planner session ended"
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


def test_map_audit_event_maps_session_resume_failed_reason() -> None:
    mapped = map_audit_event(
        {
            "type": "session_resume_failed",
            "run_id": "run-20260101T000001-000001",
            "phase": "planning",
            "role": "planner",
            "session_instance_id": "planner-inst-1",
            "generation": 1,
            "reason": "provider_turn_stalled",
            "provider_session_id": "chat-old",
            "phase_action_id": "action-01",
        }
    )
    assert mapped is not None
    assert mapped.category == "session:lineage"
    assert mapped.message == "session resume failed (provider_turn_stalled)"


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


def test_free_form_secrets_are_redacted_in_console_jsonl_and_transcript(
    tmp_path: Path,
) -> None:
    token = "cap-abc123.deadbeef0123456789abcdef0123456789abcdef0123456789"
    stderr = io.StringIO()
    run_dir = tmp_path / "run-20260101T001010-001010"
    with patch("top_down_planning.observability.sys.stderr", stderr):
        context = build_observability_context(
            options=ObservabilityOptions(
                log_format="jsonl",
                color="never",
                agent_transcript=True,
            ),
            run_id="run-20260101T001010-001010",
            run_dir=run_dir,
        )
        context.emit(
            ConsoleEvent(
                category="error",
                message="Authorization: Bearer SUPER_SECRET_BEARER",
                run_id="run-20260101T001010-001010",
            )
        )
        context.emit(
            ConsoleEvent(
                category="response",
                message=f"password=hunter2-password token={token}",
                run_id="run-20260101T001010-001010",
            )
        )
        context.emit(
            ConsoleEvent(
                category="tool:start",
                message="shell api_key=sk-example-key OPENAI_API_KEY=sk-openai-secret",
                run_id="run-20260101T001010-001010",
            )
        )
        context.emit(
            ConsoleEvent(
                category="error",
                message=(
                    "access_token=access-token-secret client_secret=client-secret-value "
                    "authorization=Bearer authz-bearer-secret"
                ),
                run_id="run-20260101T001010-001010",
            )
        )
        context.close()

    stderr_text = stderr.getvalue()
    transcript = (run_dir / "agent-transcript.jsonl").read_text(encoding="utf-8")
    for secret in (
        "SUPER_SECRET_BEARER",
        "hunter2-password",
        token,
        "sk-example-key",
        "sk-openai-secret",
        "access-token-secret",
        "client-secret-value",
        "authz-bearer-secret",
    ):
        assert secret not in stderr_text
        assert secret not in transcript


def test_no_agent_text_still_persists_redacted_transcript(tmp_path: Path) -> None:
    stderr = io.StringIO()
    run_dir = tmp_path / "run-20260101T001011-001011"
    with patch("core_tools.observability.console.sys.stderr", stderr):
        context = build_observability_context(
            options=ObservabilityOptions(
                color="never",
                no_agent_text=True,
                agent_transcript=True,
            ),
            run_id="run-20260101T001011-001011",
            run_dir=run_dir,
        )
        context.emit(ConsoleEvent(category="thinking", message="private reasoning"))
        context.emit(
            ConsoleEvent(
                category="response",
                message="Authorization: Bearer SUPER_SECRET_BEARER",
            )
        )
        context.emit(ConsoleEvent(category="tool:start", message="read README.md"))
        context.close()

    stderr_text = stderr.getvalue()
    assert "private reasoning" not in stderr_text
    assert "SUPER_SECRET_BEARER" not in stderr_text
    assert "[response]" not in stderr_text
    assert "[tool:start] read README.md" in stderr_text

    records = [
        json.loads(line)
        for line in (run_dir / "agent-transcript.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    categories = [record["category"] for record in records]
    assert "thinking" in categories
    assert "response" in categories
    transcript = json.dumps(records)
    assert "private reasoning" in transcript
    assert "SUPER_SECRET_BEARER" not in transcript
    assert "[REDACTED]" in transcript


def test_quiet_log_level_does_not_drop_agent_transcript(tmp_path: Path) -> None:
    stderr = io.StringIO()
    run_dir = tmp_path / "run-20260101T001012-001012"
    with patch("core_tools.observability.console.sys.stderr", stderr):
        context = build_observability_context(
            options=ObservabilityOptions(
                color="never",
                log_level="quiet",
                agent_transcript=True,
            ),
            run_id="run-20260101T001012-001012",
            run_dir=run_dir,
        )
        context.emit(ConsoleEvent(category="response", message="keep this prose"))
        context.emit(ConsoleEvent(category="error", message="boom"))
        context.close()

    stderr_text = stderr.getvalue()
    assert "keep this prose" not in stderr_text
    assert "boom" in stderr_text
    records = [
        json.loads(line)
        for line in (run_dir / "agent-transcript.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(record["category"] == "response" and "keep this prose" in record["message"] for record in records)


def test_provider_done_creates_separate_jsonl_turn_records(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-20260101T001013-001013"
    stderr = io.StringIO()
    with patch("top_down_planning.observability.sys.stderr", stderr):
        context = build_observability_context(
            options=ObservabilityOptions(
                log_format="jsonl",
                color="never",
                agent_transcript=True,
            ),
            run_id="run-20260101T001013-001013",
            run_dir=run_dir,
        )
        bridge = ProviderToConsoleBridge(context)
        bridge.handle({"type": "assistant", "text": "turn one", "session_id": "s1"})
        bridge.handle({"type": "done", "subtype": "success", "is_error": False, "session_id": "s1"})
        bridge.handle({"type": "assistant", "text": "turn two", "session_id": "s1"})
        bridge.handle({"type": "done", "subtype": "success", "is_error": False, "session_id": "s1"})
        bridge.handle({"type": "thinking", "text": "think one", "session_id": "s1"})
        bridge.handle({"type": "done", "subtype": "success", "is_error": False, "session_id": "s1"})
        bridge.handle({"type": "thinking", "text": "think two", "session_id": "s1"})
        bridge.handle({"type": "done", "subtype": "success", "is_error": False, "session_id": "s1"})
        bridge.handle({"type": "assistant", "text": "session one", "session_id": "s1"})
        bridge.handle({"type": "done", "subtype": "success", "is_error": False, "session_id": "s1"})
        bridge.handle({"type": "assistant", "text": "session two", "session_id": "s2"})
        context.close()

    records = [
        json.loads(line)
        for line in (run_dir / "agent-transcript.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    messages = [record["message"] for record in records]
    assert "turn one" in messages
    assert "turn two" in messages
    assert "think one" in messages
    assert "think two" in messages
    assert "session one" in messages
    assert "session two" in messages
    assert "turn oneturn two" not in messages
    sessions = [record["session_id"] for record in records if record["message"].startswith("session ")]
    assert sessions == ["s1", "s2"]


def test_provider_bridge_drops_exact_duplicate_assistant_text() -> None:
    collector = _CollectSink()
    context = ObservabilityContext(sink=collector)
    bridge = ProviderToConsoleBridge(context)
    bridge.handle({"type": "assistant", "text": "same reply"})
    bridge.handle({"type": "assistant", "text": "same reply"})
    responses = [event.message for event in collector.events if event.category == "response"]
    assert responses == ["same reply"]


def test_provider_bridge_isolates_cumulative_text_across_sessions() -> None:
    collector = _CollectSink()
    context = ObservabilityContext(sink=collector)
    bridge = ProviderToConsoleBridge(context)
    bridge.handle({"type": "assistant", "text": "Hello", "session_id": "s1"})
    bridge.handle({"type": "assistant", "text": "Hello world", "session_id": "s2"})
    responses = [
        (event.session_id, event.message)
        for event in collector.events
        if event.category == "response"
    ]
    assert responses == [("s1", "Hello"), ("s2", "Hello world")]


def test_provider_bridge_emits_identical_responses_on_separate_sessions() -> None:
    collector = _CollectSink()
    context = ObservabilityContext(sink=collector)
    bridge = ProviderToConsoleBridge(context)
    bridge.handle({"type": "assistant", "text": "Hello", "session_id": "s1"})
    bridge.handle({"type": "assistant", "text": "Hello", "session_id": "s2"})
    responses = [
        (event.session_id, event.message)
        for event in collector.events
        if event.category == "response"
    ]
    assert responses == [("s1", "Hello"), ("s2", "Hello")]


def test_provider_bridge_normalizes_interleaved_cumulative_updates_per_session() -> None:
    collector = _CollectSink()
    context = ObservabilityContext(sink=collector)
    bridge = ProviderToConsoleBridge(context)
    bridge.handle({"type": "assistant", "text": "Hello", "session_id": "s1"})
    bridge.handle({"type": "assistant", "text": "Hi", "session_id": "s2"})
    bridge.handle({"type": "assistant", "text": "Hello there", "session_id": "s1"})
    bridge.handle({"type": "assistant", "text": "Hi world", "session_id": "s2"})
    responses = [
        (event.session_id, event.message)
        for event in collector.events
        if event.category == "response"
    ]
    assert responses == [
        ("s1", "Hello"),
        ("s2", "Hi"),
        ("s1", " there"),
        ("s2", " world"),
    ]


def test_provider_bridge_isolates_thinking_and_done_across_sessions() -> None:
    collector = _CollectSink()
    context = ObservabilityContext(sink=collector)
    bridge = ProviderToConsoleBridge(context)
    bridge.handle({"type": "thinking", "text": "plan A", "session_id": "s1"})
    bridge.handle({"type": "thinking", "text": "plan A extra", "session_id": "s2"})
    bridge.handle({"type": "assistant", "text": "Hello", "session_id": "s1"})
    bridge.handle(
        {"type": "done", "subtype": "success", "is_error": False, "session_id": "s1"}
    )
    bridge.handle({"type": "assistant", "text": "Hello", "session_id": "s2"})
    thinking = [
        (event.session_id, event.message)
        for event in collector.events
        if event.category == "thinking"
    ]
    responses = [
        (event.session_id, event.message)
        for event in collector.events
        if event.category == "response"
    ]
    assert thinking == [("s1", "plan A"), ("s2", "plan A extra")]
    assert responses == [("s1", "Hello"), ("s2", "Hello")]


def test_provider_bridge_redacts_capability_token_split_across_chunks() -> None:
    stderr = io.StringIO()
    token = "cap-abc123.deadbeef"
    with patch("core_tools.observability.console.sys.stderr", stderr):
        context = build_observability_context(
            options=ObservabilityOptions(color="never"),
            run_id="run-20260101T001016-001016",
        )
        bridge = ProviderToConsoleBridge(context)
        bridge.handle({"type": "assistant", "text": token[:12]})
        bridge.handle({"type": "assistant", "text": token})
        context.close()
    output = stderr.getvalue()
    assert token not in output
    assert "deadbeef" not in output
    assert "[REDACTED]" in output


def test_provider_bridge_keeps_transcript_boundaries_after_retry_and_error(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run-20260101T001014-001014"
    stderr = io.StringIO()
    with patch("top_down_planning.observability.sys.stderr", stderr):
        context = build_observability_context(
            options=ObservabilityOptions(
                log_format="jsonl",
                color="never",
                agent_transcript=True,
            ),
            run_id="run-20260101T001014-001014",
            run_dir=run_dir,
        )
        bridge = ProviderToConsoleBridge(context)
        bridge.handle({"type": "assistant", "text": "before retry"})
        bridge.handle({"type": "retry", "text": "provider retry", "attempt": 1})
        bridge.handle({"type": "assistant", "text": "after retry"})
        bridge.handle({"type": "error", "text": "provider error"})
        context.close()

    records = [
        json.loads(line)
        for line in (run_dir / "agent-transcript.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [record["category"] for record in records] == [
        "response",
        "retry",
        "response",
        "error",
    ]
    assert records[0]["message"] == "before retry"
    assert records[2]["message"] == "after retry"


def test_provider_bridge_resets_text_normalization_on_retry() -> None:
    collector = _CollectSink()
    context = ObservabilityContext(sink=collector)
    bridge = ProviderToConsoleBridge(context)
    bridge.handle({"type": "assistant", "text": "draft"})
    bridge.handle({"type": "retry", "text": "provider retry", "attempt": 1})
    bridge.handle({"type": "assistant", "text": "draft fixed"})
    responses = [event.message for event in collector.events if event.category == "response"]
    assert responses == ["draft", "draft fixed"]


def test_provider_bridge_emits_full_identical_response_after_retry() -> None:
    collector = _CollectSink()
    context = ObservabilityContext(sink=collector)
    bridge = ProviderToConsoleBridge(context)
    bridge.handle({"type": "assistant", "text": "same draft"})
    bridge.handle({"type": "retry", "text": "provider retry", "attempt": 2})
    bridge.handle({"type": "assistant", "text": "same draft"})
    responses = [event.message for event in collector.events if event.category == "response"]
    assert responses == ["same draft", "same draft"]


def test_provider_bridge_keeps_distinct_secret_tool_calls_without_call_id() -> None:
    collector = _CollectSink()
    context = ObservabilityContext(sink=collector)
    bridge = ProviderToConsoleBridge(context)
    bridge.handle(
        {
            "type": "tool_call",
            "subtype": "started",
            "summary": "shell: token=alpha-secret-value",
        }
    )
    bridge.handle(
        {
            "type": "tool_call",
            "subtype": "started",
            "summary": "shell: token=beta-secret-value",
        }
    )
    starts = [event for event in collector.events if event.category == "tool:start"]
    assert len(starts) == 2
    combined = " ".join(event.message for event in starts)
    assert "alpha-secret-value" not in combined
    assert "beta-secret-value" not in combined
    assert combined.count("[REDACTED]") == 2


def test_provider_bridge_redacts_secret_in_truncated_tool_summary() -> None:
    collector = _CollectSink()
    context = ObservabilityContext(
        sink=collector,
        options=ObservabilityOptions(max_tool_summary_length=40),
    )
    bridge = ProviderToConsoleBridge(context)
    started = normalize_cursor_event(
        {
            "type": "tool_call",
            "subtype": "started",
            "call_id": "call-secret",
            "tool_call": {
                "shellToolCall": {
                    "args": {"command": "curl -H api_key=SUPER_SECRET_TOOL_VALUE " + ("x" * 80)}
                }
            },
        }
    )
    assert started is not None
    bridge.handle(started)
    summary = collector.events[0].message
    assert "SUPER_SECRET_TOOL_VALUE" not in summary
    assert "[REDACTED]" in summary


def test_cancel_event_closes_open_response_stream() -> None:
    stderr = io.StringIO()
    with patch("core_tools.observability.console.sys.stderr", stderr):
        context = build_observability_context(
            options=ObservabilityOptions(color="never"),
            run_id="run-20260101T001015-001015",
        )
        context.emit(ConsoleEvent(category="response", message="still streaming"))
        from top_down_planning.observability import cancel_console_event

        context.emit(cancel_console_event(run_id="run-20260101T001015-001015", phase="planning"))
        context.close()
    lines = [line for line in stderr.getvalue().splitlines() if line]
    assert lines[0].startswith("[response] still streaming")
    assert lines[1].startswith("[session:cancel]")


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
    response_text = output.split("[response] ", 1)[1].rstrip("\n")
    assert response_text.endswith("...")
    assert len(response_text) == 40


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


def test_stream_json_stdout_stays_parseable_with_noisy_provider_text(
    tmp_path: Path,
) -> None:
    config_path = write_config(
        tmp_path / "run.yaml",
        """
run:
  output_goal: Deliver the sample output.
provider:
  name: stub
planning:
  max_depth: 4
""",
    )
    runs_dir = tmp_path / "runs"
    store = FileRunStore(runs_dir)
    operations = with_root_contract(
        [
            {
                "op": "add_item",
                "temp_id": "item-api",
                "parent_id": "item-root",
                "placement": {"last_child": True},
                "item": {"kind": "work", "title": "API", "outcome": "API exists."},
            },
        ]
    )
    provider = StubProvider()
    noisy = "not a json payload\n{broken\r\ttab"
    provider.script_turn(
        done_events(signal="candidate_plan_ready", text=noisy),
        mutate_store=lambda: apply_plan(
            store,
            only_run_id(store),
            base_revision=0,
            operations=operations,
        )(),
    )

    with patch("top_down_planning.cli.user.create_provider", return_value=provider):
        result = run_cli(
            [
                "run",
                "--config",
                str(config_path),
                "--runs-dir",
                str(runs_dir),
                "--stream-json",
            ]
        )

    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    assert "run_id" in payload
    assert noisy not in result.stdout
