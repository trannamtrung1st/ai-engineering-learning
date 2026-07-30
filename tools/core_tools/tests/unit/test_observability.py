"""Unit tests for core_tools observability."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime

import pytest

from core_tools.observability.color import resolve_color_mode
from core_tools.observability.console import ColorizedConsoleSink
from core_tools.observability.events import ConsoleEvent
from core_tools.observability.jsonl import JsonlEventSink
from core_tools.observability.redaction import RedactionPolicy, redact_event, redact_value
from core_tools.observability.sink import CompositeSink, FilteredSink, NullSink


class _CollectSink:
    def __init__(self) -> None:
        self.events: list[ConsoleEvent] = []

    def emit(self, event: ConsoleEvent) -> None:
        self.events.append(event)


def test_category_block_prefix_on_first_line_only() -> None:
    stderr = io.StringIO()
    sink = ColorizedConsoleSink(stream=stderr, color="never", show_timestamps=False)
    sink.emit(
        ConsoleEvent(
            category="session:start",
            message="Starting run.\nWorking directory: /tmp\nConfig file: /tmp/config.yaml",
        )
    )
    lines = stderr.getvalue().splitlines()
    assert lines[0].startswith("[session:start] Starting run.")
    assert lines[1] == "Working directory: /tmp"
    assert lines[2] == "Config file: /tmp/config.yaml"


def test_consecutive_streaming_category_events_share_prefix() -> None:
    stderr = io.StringIO()
    sink = ColorizedConsoleSink(stream=stderr, color="never", show_timestamps=False)
    sink.emit(ConsoleEvent(category="thinking", message="First sentence."))
    sink.emit(ConsoleEvent(category="thinking", message="Second sentence."))
    lines = stderr.getvalue().splitlines()
    assert lines[0].startswith("[thinking] First sentence.")
    assert lines[1] == "Second sentence."


def test_discrete_category_events_always_show_prefix() -> None:
    stderr = io.StringIO()
    sink = ColorizedConsoleSink(stream=stderr, color="never", show_timestamps=False)
    sink.emit(ConsoleEvent(category="tool:start", message="grep foo"))
    sink.emit(ConsoleEvent(category="tool:start", message="read bar"))
    sink.emit(ConsoleEvent(category="tool:end", message="grep foo"))
    sink.emit(ConsoleEvent(category="tool:end", message="read bar"))
    lines = stderr.getvalue().splitlines()
    assert lines[0].startswith("[tool:start] grep foo")
    assert lines[1].startswith("[tool:start] read bar")
    assert lines[2].startswith("[tool:end] grep foo")
    assert lines[3].startswith("[tool:end] read bar")


def test_category_change_resets_prefix_after_continuous_block() -> None:
    stderr = io.StringIO()
    sink = ColorizedConsoleSink(stream=stderr, color="never", show_timestamps=False)
    sink.emit(ConsoleEvent(category="thinking", message="Planning."))
    sink.emit(ConsoleEvent(category="tool:start", message="read README.md"))
    sink.emit(ConsoleEvent(category="thinking", message="Continuing."))
    lines = stderr.getvalue().splitlines()
    assert lines[0].startswith("[thinking] Planning.")
    assert lines[1].startswith("[tool:start] read README.md")
    assert lines[2].startswith("[thinking] Continuing.")


def test_multiline_and_continuation_lines_share_category_style() -> None:
    stderr = io.StringIO()
    sink = ColorizedConsoleSink(stream=stderr, color="always", show_timestamps=False)
    sink.emit(
        ConsoleEvent(
            category="session:start",
            message="Starting run.\nWorking directory: /tmp",
        )
    )
    sink.emit(ConsoleEvent(category="thinking", message="First sentence."))
    sink.emit(ConsoleEvent(category="thinking", message="Second sentence."))
    output = stderr.getvalue()
    # Rich dim style for thinking and blue for session:start.
    assert "\x1b[2m" in output
    assert "\x1b[34m" in output
    lines = output.splitlines()
    assert all("\x1b[34m" in line for line in lines[:2])
    assert all("\x1b[2m" in line for line in lines[2:])


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
