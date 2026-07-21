"""Incremental UTF-8 / NDJSON stream parser for Cursor stream-json output.

Adapted from tools/implement_todos/src/todos_tool/stream_parser.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParseResult:
    events: list[dict[str, Any]] = field(default_factory=list)
    malformed: list[str] = field(default_factory=list)
    parse_errors: int = 0


class NdjsonStreamParser:
    """Decode UTF-8 incrementally and parse complete NDJSON lines."""

    def __init__(self, *, parse_error_threshold: int = 20) -> None:
        self._byte_buffer = bytearray()
        self._text_buffer = ""
        self.parse_error_threshold = parse_error_threshold
        self.parse_errors = 0
        self.malformed: list[str] = []
        self.events: list[dict[str, Any]] = []

    def feed(self, data: bytes) -> list[dict[str, Any]]:
        if not data:
            return []
        self._byte_buffer.extend(data)
        try:
            text = self._byte_buffer.decode("utf-8")
            self._byte_buffer.clear()
        except UnicodeDecodeError as exc:
            if exc.start > 0:
                text = self._byte_buffer[: exc.start].decode("utf-8")
                del self._byte_buffer[: exc.start]
            else:
                return []
        self._text_buffer += text
        return self._consume_lines()

    def finish(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        if self._byte_buffer:
            try:
                self._text_buffer += self._byte_buffer.decode("utf-8")
            except UnicodeDecodeError:
                self._record_malformed(self._byte_buffer.decode("utf-8", errors="replace"))
            self._byte_buffer.clear()
        if self._text_buffer.strip():
            events.extend(self._parse_line(self._text_buffer))
            self._text_buffer = ""
        return events

    def threshold_exceeded(self) -> bool:
        return self.parse_errors >= self.parse_error_threshold

    def _consume_lines(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        while True:
            idx = self._text_buffer.find("\n")
            if idx < 0:
                break
            line = self._text_buffer[:idx]
            self._text_buffer = self._text_buffer[idx + 1 :]
            events.extend(self._parse_line(line))
        return events

    def _parse_line(self, line: str) -> list[dict[str, Any]]:
        stripped = line.strip()
        if not stripped:
            return []
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            self._record_malformed(stripped)
            return []
        if not isinstance(obj, dict):
            self._record_malformed(stripped)
            return []
        self.events.append(obj)
        return [obj]

    def _record_malformed(self, line: str) -> None:
        self.parse_errors += 1
        self.malformed.append(line[:500])
