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
    truncate_text,
)

_STREAMING_CATEGORIES = frozenset({"thinking", "response"})
_PRESERVED_CONSOLE_CHARS = frozenset({"\n", "\t"})

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
        self._display_category: str | None = None
        self._display_session: str | None = None
        self._redactors: dict[tuple[str, str], StreamingRedactor] = {}

    def emit(self, event: ConsoleEvent) -> None:
        if event.category in _STREAMING_CATEGORIES:
            self._emit_stream_delta(event)
            return

        if event.session_id is None:
            self.flush_stream()
        else:
            self._flush_session_blocks(_session_key(event.session_id), close_line=True)
            self._close_display_line()
        safe = redact_event(event, policy=RedactionPolicy())
        tag = category_tag(safe.category)
        body = truncate_text(
            sanitize_terminal_text(_format_message(safe)),
            self._policy.max_message_length,
        )
        prefix = _build_prefix(safe.ts, tag, show_timestamps=self._show_timestamps)
        lines = body.splitlines() or [""]
        style = _CATEGORY_STYLES.get(safe.category, "")

        for index, line in enumerate(lines):
            content = f"{prefix}{line}" if index == 0 else line
            self._print_preserving_tabs(content, style, end="\n")

    def _print_preserving_tabs(self, content: str, style: str, *, end: str = "") -> None:
        segments = content.split("\t")
        for index, segment in enumerate(segments):
            if index:
                self._stream.write("\t")
            if not segment:
                continue
            text = Text(segment)
            if self._use_color and style:
                text.stylize(style)
            self._console.print(text, end="", soft_wrap=True)
        if end:
            self._stream.write(end)

    def _emit_stream_delta(self, event: ConsoleEvent) -> None:
        if not event.message:
            return
        session = _session_key(event.session_id)
        block = (session, event.category)
        current = (self._display_session or "", self._display_category or "")
        if self._streaming_line_open and current != block:
            current_session, current_category = current
            if current_session == session and current_category != event.category:
                self._flush_block(current, close_line=True)
            else:
                self._close_display_line()
        redactor = self._redactors.setdefault(
            block,
            StreamingRedactor(max_len=self._policy.max_message_length),
        )
        piece = redactor.ingest(sanitize_terminal_text(event.message))
        if not piece:
            return
        self._write_stream_piece(event, piece)

    def _write_stream_piece(self, event: ConsoleEvent, piece: str) -> None:
        tag = category_tag(event.category)
        show_prefix = not self._streaming_line_open
        style = _CATEGORY_STYLES.get(event.category, "")

        if show_prefix:
            prefix = _build_prefix(event.ts, tag, show_timestamps=self._show_timestamps)
            self._print_preserving_tabs(prefix, style, end="")
        self._print_preserving_tabs(piece, style, end="")

        self._streaming_line_open = True
        self._display_category = event.category
        self._display_session = _session_key(event.session_id)

    def flush_stream(self, session_id: str | None = None) -> None:
        if session_id is None:
            for block in list(self._redactors):
                self._flush_block(block, close_line=True)
            self._close_display_line()
            return
        self._flush_session_blocks(_session_key(session_id), close_line=True)

    def _close_display_line(self) -> None:
        if not self._streaming_line_open:
            return
        self._stream.write("\n")
        self._streaming_line_open = False
        self._display_category = None
        self._display_session = None

    def _flush_session_blocks(self, session: str, *, close_line: bool) -> None:
        for block in list(self._redactors):
            if block[0] == session:
                self._flush_block(block, close_line=close_line)

    def _flush_block(self, block: tuple[str, str], *, close_line: bool) -> None:
        session, category = block
        redactor = self._redactors.get(block)
        if redactor is None:
            if close_line and self._streaming_line_open and (
                self._display_session == session and self._display_category == category
            ):
                self._stream.write("\n")
                self._streaming_line_open = False
                self._display_category = None
                self._display_session = None
            return
        rest = redactor.flush()
        redactor.reset()
        if rest:
            event = ConsoleEvent(
                category=category or "response",
                message=rest,
                session_id=session or None,
            )
            if self._streaming_line_open and (
                self._display_session != session or self._display_category != category
            ):
                self._stream.write("\n")
                self._streaming_line_open = False
            self._write_stream_piece(event, rest)
        if close_line and self._streaming_line_open and (
            self._display_session == session and self._display_category == category
        ):
            self._stream.write("\n")
            self._streaming_line_open = False
            self._display_category = None
            self._display_session = None


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


def _session_key(session_id: str | None) -> str:
    return session_id or ""


def sanitize_terminal_text(text: str) -> str:
    """Escape C0/C1 controls except newline and tab so they cannot drive the TTY."""

    rendered: list[str] = []
    for char in text:
        code = ord(char)
        if char in _PRESERVED_CONSOLE_CHARS:
            rendered.append(char)
        elif code < 32 or code == 127 or 0x80 <= code <= 0x9F:
            rendered.append(f"\\x{code:02x}")
        else:
            rendered.append(char)
    return "".join(rendered)
