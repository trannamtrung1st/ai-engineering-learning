"""Colorized stderr console renderer."""

from __future__ import annotations

import sys
from datetime import datetime
from typing import Any, TextIO

from rich.console import Console
from rich.text import Text

from core_tools.observability.color import ColorMode, resolve_color_mode
from core_tools.observability.events import ConsoleEvent, category_tag
from core_tools.observability.redaction import RedactionPolicy, redact_event

_CATEGORY_STYLES: dict[str, str] = {
    "phase:start": "cyan",
    "phase:end": "cyan",
    "session:start": "blue",
    "session:resume": "blue",
    "thinking": "dim",
    "response": "",
    "tool:start": "yellow",
    "tool:end": "green",
    "tool:error": "bold red",
    "review": "magenta",
    "state": "cyan",
    "artifact": "cyan",
    "retry": "yellow",
    "warning": "yellow",
    "error": "bold red",
    "done": "bold green",
}


class ColorizedConsoleSink:
    """Render ConsoleEvents to stderr with Rich color."""

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
        )

    def emit(self, event: ConsoleEvent) -> None:
        safe = redact_event(
            event,
            policy=self._policy,
            output_level=self._log_level,  # type: ignore[arg-type]
        )
        tag = category_tag(safe.category)
        body = _format_message(safe)
        prefix = _build_prefix(safe.ts, tag, show_timestamps=self._show_timestamps)
        lines = body.splitlines() or [""]

        if self._use_color:
            style = _CATEGORY_STYLES.get(safe.category, "")
            first = f"{prefix}{lines[0]}"
            text = Text(first)
            if style:
                text.stylize(style)
            self._console.print(text, soft_wrap=True)
            for line in lines[1:]:
                self._console.print(line, soft_wrap=True)
        else:
            output = f"{prefix}{lines[0]}"
            if len(lines) > 1:
                output += "\n" + "\n".join(lines[1:])
            self._stream.write(output + "\n")
            self._stream.flush()


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
