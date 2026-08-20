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
    truncate_text,
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


def test_redaction_strips_embedded_env_and_cli_secret_forms() -> None:
    payload = {
        "aws": "AWS_SECRET_ACCESS_KEY=aws-access-secret",
        "api": "--api-key cli-api-secret",
        "token": "--token cli-token-secret",
        "password": "--password cli-password-secret",
        "client": "--client-secret cli-client-secret",
        "eq": "--api-key=cli-eq-secret",
    }
    redacted = redact_value(payload)
    serialized = json.dumps(redacted)
    for secret in (
        "aws-access-secret",
        "cli-api-secret",
        "cli-token-secret",
        "cli-password-secret",
        "cli-client-secret",
        "cli-eq-secret",
    ):
        assert secret not in serialized
    assert serialized.count("[REDACTED]") >= 6


def test_redaction_strips_json_quoted_secret_keys() -> None:
    payload = {
        "curl": """curl -d '{"password":"json-pass-secret"}'""",
        "tool": """tool --json '{"api_key":"json-api-secret"}'""",
        "auth": '{"Authorization":"Bearer json-auth-secret"}',
        "escaped": r'password="abc\"def-escaped-secret"',
    }
    redacted = redact_value(payload)
    serialized = json.dumps(redacted)
    for secret in (
        "json-pass-secret",
        "json-api-secret",
        "json-auth-secret",
        "def-escaped-secret",
    ):
        assert secret not in serialized
    assert serialized.count("[REDACTED]") >= 4


def test_redaction_keeps_benign_assignment_identifiers() -> None:
    text = "tokenizer=bert-base secretary=Alice notsecret=value"
    safe = redact_value(text)
    assert "bert-base" in safe
    assert "Alice" in safe
    assert "value" in safe
    assert "[REDACTED]" not in safe


def test_redaction_strips_camelcase_secret_keys() -> None:
    payload = {
        "assign": "accessToken=camel-access-secret",
        "client": "clientSecret=camel-client-secret",
        "auth": "authToken=camel-auth-secret",
        "cli": "--accessToken camel-cli-secret",
        "json": '{"accessToken":"camel-json-secret"}',
        "unicode": r'{"pass\u0077ord":"camel-unicode-secret"}',
    }
    redacted = redact_value(payload)
    serialized = json.dumps(redacted)
    for secret in (
        "camel-access-secret",
        "camel-client-secret",
        "camel-auth-secret",
        "camel-cli-secret",
        "camel-json-secret",
        "camel-unicode-secret",
    ):
        assert secret not in serialized
    assert serialized.count("[REDACTED]") >= 6


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


@pytest.mark.parametrize("max_len", [1, 2, 3])
def test_truncate_text_respects_limits_below_ellipsis_width(max_len: int) -> None:
    safe = truncate_text("abcdef", max_len)
    assert len(safe) <= max_len
    assert safe == "abcdef"[:max_len]


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


_SPLIT_SECRET_FORMS = (
    ("token=token-split-secret", "token-split-secret"),
    ("password=password-split-secret", "password-split-secret"),
    ("secret=plain-split-secret", "plain-split-secret"),
    ("password = ws-assign-secret", "ws-assign-secret"),
    ("api_key : ws-colon-secret", "ws-colon-secret"),
    ("Authorization : Token header-ws-secret", "header-ws-secret"),
    ("Authorization: Token header-token-secret", "header-token-secret"),
    ("OPENAI_API_KEY=openai-split-secret", "openai-split-secret"),
    ("AWS_SECRET_ACCESS_KEY=aws-split-secret", "aws-split-secret"),
    ("--api-key cli-split-secret", "cli-split-secret"),
    ('password="quoted space secret"', "quoted space secret"),
    (r'password="abc\"def-escaped-secret"', "def-escaped-secret"),
    ("""{"password":"json-pass-secret"}""", "json-pass-secret"),
    ("""{"api_key":"json-api-secret"}""", "json-api-secret"),
    ('{"accessToken":"camel-json-split-secret"}', "camel-json-split-secret"),
    (r'{"pass\u0077ord":"unicode-json-split-secret"}', "unicode-json-split-secret"),
    ("accessToken=camel-assign-split-secret", "camel-assign-split-secret"),
    ("--accessToken camel-cli-split-secret", "camel-cli-split-secret"),
    ("cap-abc123.deadbeef", "deadbeef"),
    ("AWS_SECRET_ACCESS_KEY_" + ("x" * 100) + "=long-key-secret", "long-key-secret"),
)


@pytest.mark.parametrize(("form", "secret"), _SPLIT_SECRET_FORMS)
def test_streaming_redactor_redacts_every_split_position(form: str, secret: str) -> None:
    for split_at in range(1, len(form)):
        redactor = StreamingRedactor()
        output = redactor.ingest(form[:split_at]) + redactor.ingest(form[split_at:]) + redactor.flush()
        assert secret not in output, f"leaked at split {split_at}"
        assert "[REDACTED]" in output


@pytest.mark.parametrize(("form", "secret"), _SPLIT_SECRET_FORMS)
def test_console_sink_redacts_secrets_split_across_stream_deltas(
    form: str,
    secret: str,
) -> None:
    for split_at in range(1, len(form)):
        stderr = io.StringIO()
        sink = ColorizedConsoleSink(stream=stderr, color="never")
        sink.emit(ConsoleEvent(category="response", message=form[:split_at]))
        sink.emit(ConsoleEvent(category="response", message=form[split_at:]))
        sink.flush_stream()
        output = stderr.getvalue()
        assert form not in output
        assert secret not in output, f"leaked at split {split_at}"
        assert "[REDACTED]" in output


def test_console_sink_keeps_secret_context_across_other_session() -> None:
    stderr = io.StringIO()
    sink = ColorizedConsoleSink(stream=stderr, color="never")
    sink.emit(ConsoleEvent(category="response", message="tok", session_id="s1"))
    sink.emit(ConsoleEvent(category="response", message="hello", session_id="s2"))
    sink.emit(ConsoleEvent(category="response", message="en=interleave-secret", session_id="s1"))
    sink.flush_stream("s1")
    sink.flush_stream("s2")
    output = stderr.getvalue()
    assert "interleave-secret" not in output
    assert "hello" in output
    assert "[REDACTED]" in output


def test_console_sink_keeps_held_ident_after_other_session_visible_prefix() -> None:
    stderr = io.StringIO()
    sink = ColorizedConsoleSink(stream=stderr, color="never")
    sink.emit(ConsoleEvent(category="response", message="prefix tok", session_id="s1"))
    sink.emit(ConsoleEvent(category="response", message="hello", session_id="s2"))
    sink.emit(ConsoleEvent(category="response", message="en=held-interleave-secret", session_id="s1"))
    sink.flush_stream("s1")
    sink.flush_stream("s2")
    output = stderr.getvalue()
    assert "held-interleave-secret" not in output
    assert "hello" in output
    assert "[REDACTED]" in output


def test_console_sink_keeps_value_state_after_other_session_visible_prefix() -> None:
    stderr = io.StringIO()
    sink = ColorizedConsoleSink(stream=stderr, color="never")
    sink.emit(ConsoleEvent(category="response", message="prefix password=", session_id="s1"))
    sink.emit(ConsoleEvent(category="response", message="hello", session_id="s2"))
    sink.emit(ConsoleEvent(category="response", message="SUPER_SECRET", session_id="s1"))
    sink.flush_stream("s1")
    sink.flush_stream("s2")
    output = stderr.getvalue()
    assert "SUPER_SECRET" not in output
    assert "hello" in output
    assert "password=[REDACTED]" in output


def test_console_sink_done_flush_does_not_cut_other_session_secret() -> None:
    stderr = io.StringIO()
    sink = ColorizedConsoleSink(stream=stderr, color="never")
    sink.emit(ConsoleEvent(category="response", message="tok", session_id="s2"))
    sink.flush_stream("s1")
    sink.emit(ConsoleEvent(category="response", message="en=other-session-secret", session_id="s2"))
    sink.flush_stream("s2")
    output = stderr.getvalue()
    assert "other-session-secret" not in output
    assert "[REDACTED]" in output


def test_jsonl_sink_keeps_secret_context_across_other_session(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    sink = JsonlEventSink(path)
    sink.emit(ConsoleEvent(category="response", message="tok", session_id="s1"))
    sink.emit(ConsoleEvent(category="response", message="hello", session_id="s2"))
    sink.emit(ConsoleEvent(category="response", message="en=jsonl-interleave-secret", session_id="s1"))
    sink.flush_stream("s1")
    sink.close()
    raw = path.read_text(encoding="utf-8")
    assert "jsonl-interleave-secret" not in raw
    records = [json.loads(line) for line in raw.splitlines()]
    by_session = {record["session_id"]: record["message"] for record in records}
    assert by_session["s2"] == "hello"
    assert "jsonl-interleave-secret" not in by_session["s1"]
    assert "[REDACTED]" in by_session["s1"]


def test_jsonl_sink_redacts_camelcase_secret_keys(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    sink = JsonlEventSink(path)
    sink.emit(
        ConsoleEvent(
            category="response",
            message='accessToken=jsonl-camel-secret {"clientSecret":"jsonl-camel-json"}',
        )
    )
    sink.close()
    raw = path.read_text(encoding="utf-8")
    assert "jsonl-camel-secret" not in raw
    assert "jsonl-camel-json" not in raw
    assert "[REDACTED]" in raw


def test_streaming_redactor_redacts_quoted_value_after_separator_chunk() -> None:
    redactor = StreamingRedactor()
    output = (
        redactor.ingest("password=")
        + redactor.ingest('"hello world" tail')
        + redactor.flush()
    )
    assert output == "password=[REDACTED] tail"
    assert "hello" not in output
    assert "world" not in output


def test_streaming_redactor_redacts_cli_quoted_value_after_space_chunk() -> None:
    redactor = StreamingRedactor()
    output = (
        redactor.ingest("--password ")
        + redactor.ingest('"hello world" done')
        + redactor.flush()
    )
    assert "hello" not in output
    assert "world" not in output
    assert output.startswith("--password ")
    assert "[REDACTED]" in output
    assert output.endswith(" done")


def test_console_sink_keeps_thinking_and_response_streams_independent() -> None:
    stderr = io.StringIO()
    sink = ColorizedConsoleSink(stream=stderr, color="never")
    sink.emit(ConsoleEvent(category="thinking", message="I need to"))
    sink.emit(ConsoleEvent(category="response", message="do it"))
    sink.flush_stream()
    output = stderr.getvalue()
    assert "[thinking] I need to" in output
    assert "[response] do it" in output
    assert "todo it" not in output


def test_console_sink_does_not_treat_response_as_thinking_secret_value() -> None:
    stderr = io.StringIO()
    sink = ColorizedConsoleSink(stream=stderr, color="never")
    sink.emit(ConsoleEvent(category="thinking", message="password="))
    sink.emit(ConsoleEvent(category="response", message="hello world"))
    sink.flush_stream()
    output = stderr.getvalue()
    assert "hello world" in output
    assert "password=[REDACTED]" in output


def test_console_sink_replaces_surrogates_in_stream_deltas() -> None:
    stderr = io.StringIO()
    sink = ColorizedConsoleSink(stream=stderr, color="never")
    sink.emit(ConsoleEvent(category="response", message="ok" + chr(0xD800) + "bad"))
    sink.flush_stream()
    output = stderr.getvalue()
    assert not any(0xD800 <= ord(ch) <= 0xDFFF for ch in output)
    assert "ok" in output
    assert "bad" in output


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


def test_streaming_redactor_keeps_benign_tokenizer_and_secretary_assignments() -> None:
    redactor = StreamingRedactor()
    output = (
        redactor.ingest("tokenizer=")
        + redactor.ingest("bert-base secretary=Alice")
        + redactor.flush()
    )
    assert output == "tokenizer=bert-base secretary=Alice"
    assert "[REDACTED]" not in output


def test_streaming_redactor_preserves_benign_quoted_escapes() -> None:
    cases = (
        r'say "a\"b" done',
        r'say "C:\\temp\\file" done',
        'code {"foo":"bar"} done',
        'say "unclosed',
    )
    for text in cases:
        redactor = StreamingRedactor()
        output = "".join(redactor.ingest(char) for char in text) + redactor.flush()
        assert output == text
        assert redactor.pending_span() <= 32


def test_streaming_redactor_truncation_does_not_rewrite_or_exceed_cap() -> None:
    redactor = StreamingRedactor(max_len=10)
    output = redactor.ingest("abcdefgh") + redactor.ingest("xyz") + redactor.flush()
    assert output == "abcdefg..."
    assert len(output) <= 10


def test_streaming_redactor_truncation_is_chunk_invariant() -> None:
    whole = StreamingRedactor(max_len=10)
    split = StreamingRedactor(max_len=10)
    assert whole.ingest("abcdefghxyz") + whole.flush() == "abcdefg..."
    assert split.ingest("abcdefgh") + split.ingest("xyz") + split.flush() == "abcdefg..."


def test_streaming_redactor_discards_unbounded_secret_value_incrementally() -> None:
    redactor = StreamingRedactor()
    pieces = [redactor.ingest("password=")]
    for _ in range(4000):
        pieces.append(redactor.ingest("xy"))
    pieces.append(redactor.ingest(" "))
    pieces.append(redactor.ingest("ok"))
    pieces.append(redactor.flush())
    output = "".join(pieces)
    assert "xy" not in output
    assert output == "password=[REDACTED] ok"


def test_streaming_redactor_long_benign_stream_is_linear_and_exact() -> None:
    redactor = StreamingRedactor()
    pieces: list[str] = []
    for _ in range(4000):
        pieces.append(redactor.ingest("ab"))
        assert redactor.pending_span() <= 32
    pieces.append(redactor.flush())
    assert "".join(pieces) == "ab" * 4000


def test_streaming_redactor_long_quoted_prose_stays_bounded_and_exact() -> None:
    redactor = StreamingRedactor()
    text = '"' + ("ab" * 4000) + '"'
    output = "".join(redactor.ingest(char) for char in text) + redactor.flush()
    assert output == text
    assert redactor.pending_span() <= 32


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


def test_console_truncation_counts_escaped_control_characters() -> None:
    stderr = io.StringIO()
    sink = ColorizedConsoleSink(
        stream=stderr,
        color="never",
        policy=RedactionPolicy(max_message_length=10),
    )
    sink.emit(ConsoleEvent(category="error", message="\x1b" * 10))
    body = stderr.getvalue().split(" ", 1)[1]
    assert "\x1b" not in body
    assert len(body.replace("\n", "")) <= 10


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
