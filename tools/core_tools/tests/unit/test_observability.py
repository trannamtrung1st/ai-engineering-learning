"""Unit tests for core_tools observability."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime

import pytest

from core_tools.observability.color import resolve_color_mode
from core_tools.observability.console import ColorizedConsoleSink
from core_tools.observability.events import ConsoleEvent
from core_tools.observability.format import format_multiline_body, prefix_width
from core_tools.observability.jsonl import JsonlEventSink
from core_tools.observability.redaction import RedactionPolicy, redact_event, redact_value
from core_tools.observability.sink import CompositeSink, FilteredSink, NullSink


class _CollectSink:
    def __init__(self) -> None:
        self.events: list[ConsoleEvent] = []

    def emit(self, event: ConsoleEvent) -> None:
        self.events.append(event)


def test_multiline_indent_uses_single_prefix_width() -> None:
    body = format_multiline_body(
        "Implementation and tests are complete.\nConsole logs stream to stderr.",
        prefix_width=prefix_width(show_timestamps=True, tag="response"),
    )
    lines = body.splitlines()
    assert lines[0] == "Implementation and tests are complete."
    assert lines[1].startswith(" " * (prefix_width(show_timestamps=True, tag="response") + 2))


def test_color_disabled_for_no_color_and_dumb_term() -> None:
    stream = io.StringIO()
    assert not resolve_color_mode(color="never", stream=stream)
    assert not resolve_color_mode(color="auto", environ={"NO_COLOR": "1"}, stream=stream)
    assert not resolve_color_mode(color="auto", environ={"TERM": "dumb"}, stream=stream)
    assert resolve_color_mode(color="always", stream=stream)


def test_redaction_strips_capability_tokens_and_secret_keys() -> None:
    token = "cap-abc123.deadbeef0123456789abcdef0123456789abcdef0123456789"
    redacted = redact_value(
        {
            "token": token,
            "message": f"using {token}",
            "API_KEY": "secret-value",
        }
    )
    assert redacted["token"] == "[REDACTED]"
    assert token not in redacted["message"]
    assert redacted["API_KEY"] == "[REDACTED]"


def test_redaction_truncates_oversized_strings() -> None:
    policy = RedactionPolicy(normal_max=20)
    event = ConsoleEvent(category="response", message="x" * 100)
    safe = redact_event(event, policy=policy, output_level="normal")
    assert len(safe.message) == 20
    assert safe.message.endswith("...")


def test_filtered_sink_respects_quiet_and_no_agent_text() -> None:
    collector = _CollectSink()
    sink = FilteredSink(collector, log_level="quiet", no_agent_text=True)
    sink.emit(ConsoleEvent(category="response", message="hello"))
    sink.emit(ConsoleEvent(category="error", message="boom"))
    assert [event.category for event in collector.events] == ["error"]


def test_jsonl_sink_writes_valid_redacted_json(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    sink = JsonlEventSink(path)
    sink.emit(
        ConsoleEvent(
            category="tool:start",
            message="plan.apply",
            fields={"call_id": "call-12", "token": "cap-x.y"},
        )
    )
    sink.close()
    payload = json.loads(path.read_text(encoding="utf-8").strip())
    assert payload["category"] == "tool:start"
    assert payload["fields"]["token"] == "[REDACTED]"


def test_console_sink_writes_to_stderr_not_stdout() -> None:
    stderr = io.StringIO()
    sink = ColorizedConsoleSink(stream=stderr, color="never", show_timestamps=False)
    sink.emit(ConsoleEvent(category="done", message="finished"))
    output = stderr.getvalue()
    assert "[done]" in output
    assert "finished" in output


def test_composite_sink_fanout() -> None:
    first = _CollectSink()
    second = _CollectSink()
    sink = CompositeSink(first, second)
    event = ConsoleEvent(category="state", message="phase=planning")
    sink.emit(event)
    assert first.events == [event]
    assert second.events == [event]


def test_null_sink_is_noop() -> None:
    NullSink().emit(ConsoleEvent(category="warning", message="ignored"))
