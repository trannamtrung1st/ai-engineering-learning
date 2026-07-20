"""Stream parser and event normalizer tests."""

from __future__ import annotations

import json

from todos_tool.event_normalizer import EventNormalizer, normalize_assistant_delta
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
