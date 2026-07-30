"""Colorized stderr console renderer.

Category blocks group consecutive events with the same category (and
multi-line bodies). The ``[timestamp] [category]`` prefix is printed on the
first line of each block only; continuation lines omit the prefix but keep the
category style when color is enabled.
"""

from __future__ import annotations

import sys
from datetime import datetime
from typing import Any, TextIO

from rich.console import Console
from rich.text import Text

from core_tools.observability.color import ColorMode, resolve_color_mode
from core_tools.observability.events import ConsoleEvent, category_tag
from core_tools.observability.redaction import RedactionPolicy, redact_event

_STREAMING_CATEGORIES = frozenset({"thinking", "response"})

_CATEGORY_STYLES: dict[str, str] = {
    "phase:start": "cyan",
    "phase:end": "cyan",
    "session:start": "blue",
    "session:resume": "blue",
    "session:cancel": "bold yellow",
    "thinking": "dim",
    "response": "",
    "tool:start": "yellow",
    "tool:end": "green",
    "review": "magenta",
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
        show_timestamps: bool = True,
        log_level: str = "normal",
        policy: RedactionPolicy | None = None,
        environ: dict[str, str] | None = None,
    ) -> None:
        self._stream = stream or sys.stderr
        self._show_timestamps = show_timestamps
        self._log_level = log_level
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
        self._last_category: str | None = None

    def emit(self, event: ConsoleEvent) -> None:
        safe = redact_event(
            event,
            policy=self._policy,
            output_level=self._log_level,  # type: ignore[arg-type]
        )
        tag = category_tag(safe.category)
        body = _format_message(safe)
        if safe.category in _STREAMING_CATEGORIES:
            show_prefix = safe.category != self._last_category
        else:
            show_prefix = True
        prefix = (
            _build_prefix(safe.ts, tag, show_timestamps=self._show_timestamps)
            if show_prefix
            else ""
        )
        lines = body.splitlines() or [""]
        style = _CATEGORY_STYLES.get(safe.category, "")

        for index, line in enumerate(lines):
            content = f"{prefix}{line}" if index == 0 else line
            text = Text(content)
            if self._use_color and style:
                text.stylize(style)
            self._console.print(text, soft_wrap=True)

        self._last_category = safe.category


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
