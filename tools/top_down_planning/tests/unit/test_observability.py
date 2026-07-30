"""Unit tests for Top Down Planning observability."""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.observability import ConsoleEvent
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


def test_provider_bridge_correlates_tool_start_and_end() -> None:
    collector = _CollectSink()
    context = ObservabilityContext(sink=collector)
    bridge = ProviderToConsoleBridge(context)
    bridge.handle(
        {
            "type": "tool_call",
            "tool": "plan_apply",
            "call_id": "call-12",
            "request": {"base_revision": 0, "operations": [{}, {}, {}]},
        }
    )
    bridge.handle(
        {
            "type": "tool_result",
            "tool": "plan_apply",
            "call_id": "call-12",
            "ok": True,
        }
    )
    assert [event.category for event in collector.events] == ["tool:start", "tool:end"]
    assert collector.events[0].fields["call_id"] == "call-12"
    assert collector.events[0].fields["operations"] == 3
    assert collector.events[1].fields["ok"] is True
    assert "duration_ms" in collector.events[1].fields


def test_provider_bridge_closes_open_tools_on_done() -> None:
    collector = _CollectSink()
    context = ObservabilityContext(sink=collector)
    bridge = ProviderToConsoleBridge(context)
    bridge.handle(
        {
            "type": "tool_call",
            "tool": "plan_apply",
            "call_id": "call-9",
            "request": {"base_revision": 0, "operations": [{}]},
        }
    )
    bridge.handle(
        {
            "type": "done",
            "subtype": "success",
            "text": "ok",
            "is_error": False,
        }
    )
    assert [event.category for event in collector.events] == ["tool:start", "tool:end"]
    assert collector.events[1].fields["call_id"] == "call-9"


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
                message="plan_apply",
                fields={"token": token},
                run_id="run-secret",
            )
        )
        context.close()
    assert token not in stderr.getvalue()
    assert "[REDACTED]" in stderr.getvalue()
