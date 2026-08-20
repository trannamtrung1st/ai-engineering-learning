"""Colorized stderr console renderer.

Discrete events print ``[category]`` once per block (optional ``[timestamp]`` when
enabled). Multi-line discrete messages omit the prefix on continuation lines.

``thinking`` and ``response`` events are incremental text deltas: characters are
written without trailing newlines until the category changes or a discrete event
interrupts the stream. Explicit ``\\n`` in agent text produces line breaks within
the block.
"""

from __future__ import annotations

import sys
from datetime import datetime
from typing import Any, TextIO

from rich.console import Console
from rich.text import Text

from core_tools.observability.color import ColorMode, resolve_color_mode
from core_tools.observability.events import ConsoleEvent, category_tag
from core_tools.observability.redaction import (
    RedactionPolicy,
    StreamingRedactor,
    redact_event,
)

_STREAMING_CATEGORIES = frozenset({"thinking", "response"})

_CATEGORY_STYLES: dict[str, str] = {
    "phase:start": "cyan",
    "phase:end": "cyan",
    "run:start": "blue",
    "run:resume": "blue",
    "session:start": "blue",
    "session:end": "blue",
    "session:resume": "blue",
    "session:cancel": "bold yellow",
    "thinking": "dim",
    "response": "",
    "tool:start": "yellow",
    "tool:end": "green",
    "review": "magenta",
    "review:start": "magenta",
    "review:stage": "magenta",
    "state": "cyan",
    "artifact": "cyan",
    "retry": "yellow",
    "warning": "yellow",
    "error": "bold red",
    "done": "bold green",
}


class ColorizedConsoleSink:
    """Render ``ConsoleEvent`` values to stderr with optional Rich styling."""

    def __init__(
        self,
        *,
        stream: TextIO | None = None,
        color: ColorMode = "auto",
        show_timestamps: bool = False,
        policy: RedactionPolicy | None = None,
        environ: dict[str, str] | None = None,
    ) -> None:
        self._stream = stream or sys.stderr
        self._show_timestamps = show_timestamps
        self._policy = policy or RedactionPolicy()
        self._use_color = resolve_color_mode(
            color=color,
            stream=self._stream,
            environ=environ,
        )
        self._console = Console(
            file=self._stream,
            no_color=not self._use_color,
            highlight=False,
            force_terminal=self._use_color,
            color_system="standard" if self._use_color else None,
        )
        self._streaming_line_open = False
        self._streaming_block_category: str | None = None
        self._streaming_session_id: str | None = None
        self._stream_redactor = StreamingRedactor(max_len=self._policy.max_message_length)

    def emit(self, event: ConsoleEvent) -> None:
        if event.category in _STREAMING_CATEGORIES:
            self._emit_stream_delta(event)
            return

        self._end_streaming_line()
        safe = redact_event(event, policy=self._policy)
        tag = category_tag(safe.category)
        body = _format_message(safe)
        prefix = _build_prefix(safe.ts, tag, show_timestamps=self._show_timestamps)
        lines = body.splitlines() or [""]
        style = _CATEGORY_STYLES.get(safe.category, "")

        for index, line in enumerate(lines):
            content = f"{prefix}{line}" if index == 0 else line
            text = Text(content)
            if self._use_color and style:
                text.stylize(style)
            self._console.print(text, soft_wrap=True)

    def _emit_stream_delta(self, event: ConsoleEvent) -> None:
        if not event.message:
            return

        if self._streaming_block_category is not None and (
            self._streaming_block_category != event.category
            or self._streaming_session_id != event.session_id
        ):
            self._end_streaming_line()

        piece = self._stream_redactor.ingest(event.message)
        if not piece:
            if self._streaming_block_category is None:
                self._streaming_block_category = event.category
                self._streaming_session_id = event.session_id
            return
        self._write_stream_piece(event, piece)

    def _write_stream_piece(self, event: ConsoleEvent, piece: str) -> None:
        tag = category_tag(event.category)
        show_prefix = not self._streaming_line_open
        style = _CATEGORY_STYLES.get(event.category, "")

        if show_prefix:
            prefix = _build_prefix(event.ts, tag, show_timestamps=self._show_timestamps)
            prefix_text = Text(prefix)
            if self._use_color and style:
                prefix_text.stylize(style)
            self._console.print(prefix_text, end="", soft_wrap=True)
        delta_text = Text(piece)
        if self._use_color and style:
            delta_text.stylize(style)
        self._console.print(delta_text, end="", soft_wrap=True)

        self._streaming_line_open = True
        self._streaming_block_category = event.category
        self._streaming_session_id = event.session_id

    def flush_stream(self) -> None:
        self._end_streaming_line()

    def _end_streaming_line(self) -> None:
        rest = self._stream_redactor.flush()
        if rest:
            event = ConsoleEvent(
                category=self._streaming_block_category or "response",
                message=rest,
                session_id=self._streaming_session_id,
            )
            self._write_stream_piece(event, rest)
        self._stream_redactor.reset()
        if self._streaming_line_open:
            self._stream.write("\n")
            self._streaming_line_open = False
        self._streaming_block_category = None
        self._streaming_session_id = None


def _build_prefix(ts: datetime, tag: str, *, show_timestamps: bool) -> str:
    parts: list[str] = []
    if show_timestamps:
        parts.append(f"[{ts.strftime('%H:%M:%S')}]")
    parts.append(f"[{tag}]")
    return " ".join(parts) + " "


def _format_message(event: ConsoleEvent) -> str:
    extras = _format_fields(event.fields)
    if extras:
        if event.message:
            return f"{event.message} {extras}"
        return extras
    return event.message


def _format_fields(fields: dict[str, Any]) -> str:
    if not fields:
        return ""
    parts: list[str] = []
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, bool):
            parts.append(f"{key}={'ok' if value else 'fail'}")
        else:
            parts.append(f"{key}={value}")
    return " ".join(parts)
