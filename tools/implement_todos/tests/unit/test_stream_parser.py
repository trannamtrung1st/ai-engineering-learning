"""Stream parser and event normalizer tests."""

from __future__ import annotations

import json
from pathlib import Path

from todos_tool.console_renderer import ConsoleRenderer
from todos_tool.event_normalizer import (
    EventNormalizer,
    NormalizedEvent,
    normalize_assistant_delta,
    normalize_text_delta,
)
from todos_tool.stream_parser import NdjsonStreamParser


def test_split_utf8_and_json_lines() -> None:
    parser = NdjsonStreamParser()
    event = {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}}
    payload = (json.dumps(event) + "\n").encode("utf-8")
    mid = len(payload) // 2
    assert parser.feed(payload[:mid]) == []
    events = parser.feed(payload[mid:])
    assert len(events) == 1
    assert events[0]["type"] == "assistant"


def test_malformed_lines_recorded() -> None:
    parser = NdjsonStreamParser(parse_error_threshold=5)
    parser.feed(b"not-json\n")
    parser.feed(b'{"type":"status"}\n')
    assert parser.parse_errors == 1
    assert len(parser.events) == 1
    assert not parser.threshold_exceeded()


def test_unknown_events_normalized() -> None:
    normalizer = EventNormalizer()
    events = normalizer.normalize({"type": "custom_mystery", "x": 1})
    assert events[0].category == "unknown"


def test_does_not_fabricate_thinking() -> None:
    normalizer = EventNormalizer()
    # Assistant events must not become thinking
    events = normalizer.normalize(
        {
            "type": "assistant",
            "timestamp_ms": 1,
            "message": {"content": [{"type": "text", "text": "hello"}]},
        }
    )
    assert events[0].category == "assistant"
    assert normalizer.normalize({"type": "thinking"}) == []


def test_assistant_delta_helper() -> None:
    turn, delta = normalize_assistant_delta("", "abc")
    assert turn == "abc" and delta == "abc"
    turn, delta = normalize_assistant_delta("abc", "abcdef")
    assert turn == "abcdef" and delta == "def"
    turn, delta = normalize_text_delta("abc", "def")
    assert turn == "abcdef" and delta == "def"


def test_thinking_chunks_coalesced() -> None:
    normalizer = EventNormalizer()
    chunks = ["Beginning work on UT-001:", " installing", " Vitest"]
    deltas = []
    for chunk in chunks:
        events = normalizer.normalize({"type": "thinking", "subtype": "extended", "text": chunk})
        assert len(events) == 1
        assert events[0].category == "thinking"
        deltas.append(events[0].text)
    assert "".join(deltas) == "Beginning work on UT-001: installing Vitest"


def test_thinking_cumulative_deduped() -> None:
    normalizer = EventNormalizer()
    first = normalizer.normalize({"type": "thinking", "text": "Hello"})
    second = normalizer.normalize({"type": "thinking", "text": "Hello world"})
    assert first[0].text == "Hello"
    assert second[0].text == " world"


def test_user_and_interaction_query_suppressed() -> None:
    normalizer = EventNormalizer()
    assert (
        normalizer.normalize(
            {
                "type": "user",
                "message": {"role": "user", "content": [{"type": "text", "text": "prompt"}]},
            }
        )
        == []
    )
    assert (
        normalizer.normalize(
            {
                "type": "interaction_query",
                "subtype": "request",
                "query_type": "webSearchRequestQuery",
            }
        )
        == []
    )


def test_assistant_skips_model_call_id_flush() -> None:
    normalizer = EventNormalizer()
    streamed = normalizer.normalize(
        {
            "type": "assistant",
            "timestamp_ms": 1,
            "message": {"content": [{"type": "text", "text": "Hi"}]},
        }
    )
    assert streamed[0].text == "Hi"
    duplicate = normalizer.normalize(
        {
            "type": "assistant",
            "timestamp_ms": 2,
            "model_call_id": "call-1",
            "message": {"content": [{"type": "text", "text": "Hi there"}]},
        }
    )
    assert duplicate == []


def test_non_partial_assistant_messages_still_emit() -> None:
    """Complete stream-json messages (no timestamp_ms) must still render."""
    normalizer = EventNormalizer()
    first = normalizer.normalize(
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "I'll read the file"}]},
        }
    )
    assert first[0].text == "I'll read the file"
    normalizer.normalize(
        {
            "type": "tool_call",
            "subtype": "started",
            "tool_call": {"readToolCall": {"args": {"path": "a.ts"}}},
        }
    )
    second = normalizer.normalize(
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Done."}]},
        }
    )
    assert second[0].text == "Done."


def test_end_of_turn_flush_deduped_after_partials() -> None:
    normalizer = EventNormalizer()
    normalizer.normalize(
        {
            "type": "assistant",
            "timestamp_ms": 1,
            "message": {"content": [{"type": "text", "text": "Hello"}]},
        }
    )
    normalizer.normalize(
        {
            "type": "assistant",
            "timestamp_ms": 2,
            "message": {"content": [{"type": "text", "text": " world"}]},
        }
    )
    # Final flush without timestamp_ms duplicates the streamed turn.
    assert (
        normalizer.normalize(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "Hello world"}]},
            }
        )
        == []
    )


def test_tool_labels_include_paths() -> None:
    normalizer = EventNormalizer()
    started = normalizer.normalize(
        {
            "type": "tool_call",
            "subtype": "started",
            "tool_call": {"readToolCall": {"args": {"path": "src/app.ts"}}},
        }
    )
    assert started[0].category == "tool:start"
    assert started[0].text == "read src/app.ts"

    globbed = normalizer.normalize(
        {
            "type": "tool_call",
            "subtype": "started",
            "tool_call": {"globToolCall": {"args": {"globPattern": "**/*.tsx"}}},
        }
    )
    assert globbed[0].text == "glob **/*.tsx"

    shelled = normalizer.normalize(
        {
            "type": "tool_call",
            "subtype": "started",
            "tool_call": {"shellToolCall": {"args": {"command": "npm test"}}},
        }
    )
    assert shelled[0].text == "shell: npm test"


def test_shell_evidence_captures_working_directory() -> None:
    from todos_tool.cursor_stream import EventNormalizer

    normalizer = EventNormalizer()
    normalizer.normalize(
        {
            "type": "tool_call",
            "subtype": "started",
            "tool_call": {
                "shellToolCall": {
                    "args": {
                        "command": "pytest",
                        "workingDirectory": "src",
                    }
                }
            },
        }
    )
    normalizer.normalize(
        {
            "type": "tool_call",
            "subtype": "completed",
            "tool_call": {
                "shellToolCall": {
                    "args": {"command": "pytest", "workingDirectory": "src"},
                    "result": {"success": {"exitCode": 0}},
                }
            },
        }
    )
    evidence = normalizer.get_shell_commands()
    assert len(evidence) == 1
    assert evidence[0].command == "pytest"
    assert evidence[0].cwd == "src"
    assert evidence[0].completed is True


def test_shell_evidence_reads_failure_exit_code() -> None:
    from todos_tool.cursor_stream import EventNormalizer

    normalizer = EventNormalizer()
    normalizer.normalize(
        {
            "type": "tool_call",
            "subtype": "started",
            "tool_call": {
                "shellToolCall": {
                    "args": {"command": "pytest"},
                }
            },
        }
    )
    normalizer.normalize(
        {
            "type": "tool_call",
            "subtype": "completed",
            "tool_call": {
                "shellToolCall": {
                    "args": {"command": "pytest"},
                    "result": {"failure": {"exitCode": 2}},
                }
            },
        }
    )
    evidence = normalizer.get_shell_commands()
    assert len(evidence) == 1
    assert evidence[0].exit_code == 2
    assert evidence[0].completed is True


def test_shell_evidence_retry_uses_last_successful_match() -> None:
    from todos_tool.evidence_matcher import ObservedShellRun, match_spec_to_observed

    result = match_spec_to_observed(
        "pytest",
        ".",
        [
            ObservedShellRun(
                command="pytest",
                cwd=".",
                completed=True,
                exit_code=1,
            ),
            ObservedShellRun(
                command="pytest",
                cwd=".",
                completed=True,
                exit_code=0,
            ),
        ],
    )
    assert result.passed is True
    assert result.match_kind == "exact"
    assert result.exit_code == 0


def test_shell_evidence_all_failed_uses_last_match() -> None:
    from todos_tool.evidence_matcher import ObservedShellRun, match_spec_to_observed

    result = match_spec_to_observed(
        "pytest",
        ".",
        [
            ObservedShellRun(
                command="pytest",
                cwd=".",
                completed=True,
                exit_code=1,
            ),
            ObservedShellRun(
                command="pytest",
                cwd=".",
                completed=True,
                exit_code=2,
            ),
        ],
    )
    assert result.passed is False
    assert result.match_kind == "failed_run"
    assert result.exit_code == 2


def test_console_renderer_streams_thinking_as_one_block(tmp_path: Path) -> None:
    log_path = tmp_path / "out.log"
    renderer = ConsoleRenderer(no_color=True, log_path=log_path)

    for text in ("Hello ", "world"):
        renderer.render(NormalizedEvent("thinking", text, {}))
    renderer.render(NormalizedEvent("tool:start", "read a.ts", {}))
    renderer.flush()

    logged = log_path.read_text(encoding="utf-8")
    assert logged.startswith("[thinking] Hello world\n")
    assert "[tool:start] read a.ts\n" in logged


def test_console_renderer_streams_assistant_without_prefix(tmp_path: Path) -> None:
    log_path = tmp_path / "assistant.log"
    renderer = ConsoleRenderer(no_color=True, log_path=log_path)

    renderer.render(NormalizedEvent("assistant", "I'll ", {}))
    renderer.render(NormalizedEvent("assistant", "start.", {}))
    renderer.flush()

    assert log_path.read_text(encoding="utf-8") == "I'll start.\n"
