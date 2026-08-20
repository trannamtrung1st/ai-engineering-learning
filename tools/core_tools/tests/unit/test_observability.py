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
from core_tools.observability.redaction import (
    RedactionPolicy,
    StreamingRedactor,
    redact_event,
    redact_value,
)
from core_tools.observability.sink import CompositeSink, FilteredSink, NullSink


class _CollectSink:
    def __init__(self) -> None:
        self.events: list[ConsoleEvent] = []

    def emit(self, event: ConsoleEvent) -> None:
        self.events.append(event)


def test_session_end_category_renders() -> None:
    stderr = io.StringIO()
    sink = ColorizedConsoleSink(stream=stderr, color="never")
    sink.emit(
        ConsoleEvent(
            category="session:end",
            message="planner session ended",
            fields={"phase": "planning", "role": "planner"},
        )
    )
    assert "[session:end]" in stderr.getvalue()
    assert "planner session ended" in stderr.getvalue()


def test_review_start_and_stage_categories_render() -> None:
    stderr = io.StringIO()
    sink = ColorizedConsoleSink(stream=stderr, color="never")
    sink.emit(
        ConsoleEvent(
            category="review:start",
            message="whole-plan review loop started",
            fields={"loop_id": "review-whole-plan-01", "review_type": "whole_plan"},
        )
    )
    sink.emit(
        ConsoleEvent(
            category="review:stage",
            message="scope review started",
            fields={"stage": "scope_review", "review_type": "whole_plan"},
        )
    )
    output = stderr.getvalue()
    assert "[review:start]" in output
    assert "whole-plan review loop started" in output
    assert "[review:stage]" in output
    assert "scope review started" in output


def test_category_block_prefix_on_first_line_only() -> None:
    stderr = io.StringIO()
    sink = ColorizedConsoleSink(stream=stderr, color="never")
    sink.emit(
        ConsoleEvent(
            category="run:start",
            message="Starting run.\nWorking directory: /tmp\nConfig file: /tmp/config.yaml",
        )
    )
    lines = stderr.getvalue().splitlines()
    assert lines[0].startswith("[run:start] Starting run.")
    assert lines[1] == "Working directory: /tmp"
    assert lines[2] == "Config file: /tmp/config.yaml"


def test_consecutive_streaming_category_events_share_prefix() -> None:
    stderr = io.StringIO()
    sink = ColorizedConsoleSink(stream=stderr, color="never")
    sink.emit(ConsoleEvent(category="thinking", message="First sentence."))
    sink.emit(ConsoleEvent(category="thinking", message=" Second sentence."))
    lines = stderr.getvalue().splitlines()
    assert lines == ["[thinking] First sentence. Second sentence."]


def test_show_timestamps_prefix_when_enabled() -> None:
    stderr = io.StringIO()
    ts = datetime(2026, 7, 30, 14, 30, 45, tzinfo=UTC)
    sink = ColorizedConsoleSink(stream=stderr, color="never", show_timestamps=True)
    sink.emit(ConsoleEvent(category="done", message="finished", ts=ts))
    assert stderr.getvalue().startswith("[14:30:45] [done] finished")


def test_discrete_category_events_always_show_prefix() -> None:
    stderr = io.StringIO()
    sink = ColorizedConsoleSink(stream=stderr, color="never")
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
    sink = ColorizedConsoleSink(stream=stderr, color="never")
    sink.emit(ConsoleEvent(category="thinking", message="Planning."))
    sink.emit(ConsoleEvent(category="tool:start", message="read README.md"))
    sink.emit(ConsoleEvent(category="thinking", message="Continuing."))
    lines = stderr.getvalue().splitlines()
    assert lines[0].startswith("[thinking] Planning.")
    assert lines[1].startswith("[tool:start] read README.md")
    assert lines[2].startswith("[thinking] Continuing.")


def test_multiline_and_continuation_lines_share_category_style() -> None:
    stderr = io.StringIO()
    sink = ColorizedConsoleSink(stream=stderr, color="always")
    sink.emit(
        ConsoleEvent(
            category="run:start",
            message="Starting run.\nWorking directory: /tmp",
        )
    )
    sink.emit(ConsoleEvent(category="thinking", message="First sentence."))
    sink.emit(ConsoleEvent(category="thinking", message=" Second sentence."))
    output = stderr.getvalue()
    # Rich dim style for thinking and blue for run:start.
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


def test_redaction_strips_free_form_secrets_in_strings() -> None:
    token = "cap-abc123.deadbeef0123456789abcdef0123456789abcdef0123456789"
    payload = {
        "auth": "Authorization: Bearer SUPER_SECRET_BEARER",
        "login": "password=hunter2-password",
        "provider": "api_key=sk-example-key",
        "error": "request failed: credential credential-abc123 rejected",
        "prose": f"resume with {token} please",
        "nested": {"inner": {"note": "api-key=nested-secret-value"}},
    }
    redacted = redact_value(payload)
    serialized = json.dumps(redacted)
    assert "SUPER_SECRET_BEARER" not in serialized
    assert "hunter2-password" not in serialized
    assert "sk-example-key" not in serialized
    assert "credential-abc123" not in serialized
    assert "nested-secret-value" not in serialized
    assert token not in serialized
    assert serialized.count("[REDACTED]") >= 5


def test_redaction_strips_prefixed_credential_assignments() -> None:
    payload = {
        "openai": "OPENAI_API_KEY=sk-openai-secret",
        "anthropic": "export ANTHROPIC_API_KEY=sk-anthropic-secret",
        "access": "access_token=access-token-secret",
        "refresh": "refresh_token=refresh-token-secret",
        "client": "client_secret=client-secret-value",
        "auth_token": "auth_token=auth-token-secret",
        "authorization": "authorization=Bearer authz-bearer-secret",
    }
    redacted = redact_value(payload)
    serialized = json.dumps(redacted)
    for secret in (
        "sk-openai-secret",
        "sk-anthropic-secret",
        "access-token-secret",
        "refresh-token-secret",
        "client-secret-value",
        "auth-token-secret",
        "authz-bearer-secret",
    ):
        assert secret not in serialized
    assert serialized.count("[REDACTED]") >= 7


def test_redaction_strips_authorization_header_regardless_of_scheme() -> None:
    headers = [
        "Authorization: Token token-scheme-secret",
        'Authorization: Digest username="u", nonce="digest-secret"',
        "Authorization: Negotiate negotiate-secret",
        "Proxy-Authorization: Basic proxy-basic-secret",
        "Authorization: Acme custom-scheme-secret",
    ]
    redacted = [redact_value(header) for header in headers]
    serialized = json.dumps(redacted)
    for secret in (
        "token-scheme-secret",
        "digest-secret",
        "negotiate-secret",
        "proxy-basic-secret",
        "custom-scheme-secret",
    ):
        assert secret not in serialized
    assert all(item.endswith("[REDACTED]") for item in redacted)
    assert serialized.count("[REDACTED]") == 5


def test_redaction_happens_before_truncation_near_secret() -> None:
    secret = "VISIBLE_SECRET_FRAGMENT"
    text = "prefix api_key=" + secret + ("x" * 40)
    safe = redact_value(text, max_len=30)
    assert secret not in safe
    assert "api_key=" in safe
    assert "[REDACTED]" in safe


def test_redaction_replaces_lone_unicode_surrogates() -> None:
    text = "ok" + chr(0xD800) + "bad"
    safe = redact_value(text)
    assert not any(0xD800 <= ord(ch) <= 0xDFFF for ch in safe)
    json.dumps(safe)


def test_redaction_truncates_oversized_strings() -> None:
    policy = RedactionPolicy(max_message_length=20)
    event = ConsoleEvent(category="response", message="x" * 100)
    safe = redact_event(event, policy=policy)
    assert len(safe.message) == 20
    assert safe.message.endswith("...")


def test_redaction_unlimited_by_default() -> None:
    event = ConsoleEvent(category="response", message="x" * 1000)
    safe = redact_event(event, policy=RedactionPolicy())
    assert safe.message == "x" * 1000


def test_filtered_sink_respects_quiet_and_no_agent_text() -> None:
    collector = _CollectSink()
    sink = FilteredSink(collector, log_level="quiet", no_agent_text=True)
    sink.emit(ConsoleEvent(category="response", message="hello"))
    sink.emit(ConsoleEvent(category="error", message="boom"))
    assert [event.category for event in collector.events] == ["error"]


def test_jsonl_sink_aggregates_thinking_and_response_deltas(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    sink = JsonlEventSink(path)
    sink.emit(ConsoleEvent(category="thinking", message="Hello"))
    sink.emit(ConsoleEvent(category="thinking", message=" world."))
    sink.emit(ConsoleEvent(category="tool:start", message="read README.md"))
    sink.close()
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    thinking = json.loads(lines[0])
    assert thinking["category"] == "thinking"
    assert thinking["message"] == "Hello world."


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


def test_jsonl_sink_flushes_stream_on_explicit_boundary(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    sink = JsonlEventSink(path)
    sink.emit(ConsoleEvent(category="response", message="turn one", session_id="s1"))
    sink.flush_stream()
    sink.emit(ConsoleEvent(category="response", message="turn two", session_id="s1"))
    sink.close()
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [record["message"] for record in records] == ["turn one", "turn two"]


def test_jsonl_sink_splits_records_when_session_id_changes(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    sink = JsonlEventSink(path)
    sink.emit(ConsoleEvent(category="response", message="from session one", session_id="s1"))
    sink.emit(ConsoleEvent(category="response", message="from session two", session_id="s2"))
    sink.close()
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 2
    assert records[0]["session_id"] == "s1"
    assert records[0]["message"] == "from session one"
    assert records[1]["session_id"] == "s2"
    assert records[1]["message"] == "from session two"


def test_jsonl_sink_persists_multiline_and_control_chars_as_one_line(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    sink = JsonlEventSink(path)
    message = "line one\nline two\r\ttab\x1besc\x00nul"
    sink.emit(ConsoleEvent(category="response", message=message))
    sink.close()
    raw = path.read_text(encoding="utf-8")
    assert raw.count("\n") == 1
    payload = json.loads(raw)
    assert payload["message"] == message


def test_jsonl_sink_persists_surrogate_input_as_valid_json(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    sink = JsonlEventSink(path)
    sink.emit(ConsoleEvent(category="response", message="bad" + chr(0xD800) + "text"))
    sink.close()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["message"].startswith("bad")
    assert payload["message"].endswith("text")
    assert not any(0xD800 <= ord(ch) <= 0xDFFF for ch in payload["message"])


def test_console_sink_redacts_bearer_secret() -> None:
    stderr = io.StringIO()
    sink = ColorizedConsoleSink(stream=stderr, color="never")
    sink.emit(
        ConsoleEvent(
            category="error",
            message="Authorization: Bearer SUPER_SECRET_BEARER",
        )
    )
    output = stderr.getvalue()
    assert "SUPER_SECRET_BEARER" not in output
    assert "[REDACTED]" in output


def test_console_sink_flushes_stream_between_same_category_turns() -> None:
    stderr = io.StringIO()
    sink = ColorizedConsoleSink(stream=stderr, color="never")
    sink.emit(ConsoleEvent(category="thinking", message="first turn"))
    sink.flush_stream()
    sink.emit(ConsoleEvent(category="thinking", message="second turn"))
    lines = [line for line in stderr.getvalue().splitlines() if line]
    assert lines[0].startswith("[thinking] first turn")
    assert lines[1].startswith("[thinking] second turn")


def test_console_sink_ends_open_stream_before_cancel() -> None:
    stderr = io.StringIO()
    sink = ColorizedConsoleSink(stream=stderr, color="never")
    sink.emit(ConsoleEvent(category="response", message="partial reply"))
    sink.emit(ConsoleEvent(category="session:cancel", message="cancelled by user"))
    lines = [line for line in stderr.getvalue().splitlines() if line]
    assert lines[0].startswith("[response] partial reply")
    assert lines[1].startswith("[session:cancel] cancelled by user")


@pytest.mark.parametrize(
    ("secret", "split_at"),
    [
        ("cap-abc123.deadbeef", 4),
        ("cap-abc123.deadbeef", 11),
        ("cap-abc123.deadbeef", 12),
        ("Authorization: Bearer SUPER_SECRET_BEARER", 22),
        ("Authorization: Bearer SUPER_SECRET_BEARER", 28),
        ("OPENAI_API_KEY=sk-openai-secret", 15),
        ("OPENAI_API_KEY=sk-openai-secret", 16),
        ("access_token=access-token-secret", 13),
        ("client_secret=client-secret-value", 14),
        ("authorization=Bearer authz-bearer-secret", 14),
        ("authorization=Bearer authz-bearer-secret", 21),
    ],
)
def test_console_sink_redacts_secrets_split_across_stream_deltas(
    secret: str,
    split_at: int,
) -> None:
    stderr = io.StringIO()
    sink = ColorizedConsoleSink(stream=stderr, color="never")
    sink.emit(ConsoleEvent(category="response", message=secret[:split_at]))
    sink.emit(ConsoleEvent(category="response", message=secret[split_at:]))
    sink.flush_stream()
    output = stderr.getvalue()
    assert secret not in output
    for fragment in (
        "deadbeef",
        "SUPER_SECRET_BEARER",
        "sk-openai-secret",
        "access-token-secret",
        "client-secret-value",
        "authz-bearer-secret",
    ):
        if fragment in secret:
            assert fragment not in output
    assert "[REDACTED]" in output


def test_streaming_redactor_emits_exact_sanitized_assignment_without_duplication() -> None:
    redactor = StreamingRedactor()
    output = (
        redactor.ingest("OPENAI_")
        + redactor.ingest("API_KEY=sk-secret")
        + redactor.flush()
    )
    assert output == "OPENAI_API_KEY=[REDACTED]"
    assert "sk-secret" not in output


def test_streaming_redactor_does_not_duplicate_benign_secretary() -> None:
    redactor = StreamingRedactor()
    output = redactor.ingest("se") + redactor.ingest("cretary") + redactor.flush()
    assert output == "secretary"


def test_streaming_redactor_truncation_does_not_rewrite_or_exceed_cap() -> None:
    redactor = StreamingRedactor(max_len=10)
    output = redactor.ingest("abcdefgh") + redactor.ingest("xyz") + redactor.flush()
    assert "abcdefghabcdefg" not in output
    assert output.startswith("abcdefgh")
    assert len(output) <= 10


def test_streaming_redactor_long_benign_stream_is_linear_and_exact() -> None:
    redactor = StreamingRedactor()
    pieces: list[str] = []
    for _ in range(4000):
        pieces.append(redactor.ingest("ab"))
    pieces.append(redactor.flush())
    assert "".join(pieces) == "ab" * 4000


def test_console_sink_neutralizes_terminal_control_characters() -> None:
    stderr = io.StringIO()
    sink = ColorizedConsoleSink(stream=stderr, color="never")
    sink.emit(
        ConsoleEvent(
            category="error",
            message="alert\x07ansi\x1b[31mred\x1b]0;title\x07nul\x00cr\rover\ttab\nnext",
        )
    )
    output = stderr.getvalue()
    assert "\x1b" not in output
    assert "\x07" not in output
    assert "\x00" not in output
    assert "\r" not in output
    assert "\\x1b" in output
    assert "\\x07" in output
    assert "\\x00" in output
    assert "\\x0d" in output
    assert "\t" in output
    assert "\n" in output


def test_console_sink_neutralizes_control_characters_in_stream_deltas() -> None:
    stderr = io.StringIO()
    sink = ColorizedConsoleSink(stream=stderr, color="never")
    sink.emit(ConsoleEvent(category="response", message="ok\x1b[0m"))
    sink.emit(ConsoleEvent(category="response", message="\x07done"))
    sink.flush_stream()
    output = stderr.getvalue()
    assert "\x1b" not in output
    assert "\x07" not in output
    assert "\\x1b" in output
    assert "\\x07" in output


def test_jsonl_sink_keeps_control_characters_as_valid_json(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    sink = JsonlEventSink(path)
    message = "ansi\x1b[0m\x07\x00\rover\ttab\nnext"
    sink.emit(ConsoleEvent(category="response", message=message))
    sink.close()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["message"] == message


def test_console_sink_writes_to_stderr_not_stdout() -> None:
    stderr = io.StringIO()
    sink = ColorizedConsoleSink(stream=stderr, color="never")
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
