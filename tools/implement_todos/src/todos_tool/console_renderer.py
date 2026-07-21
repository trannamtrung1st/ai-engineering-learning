"""Colorized console rendering for normalized Cursor events."""

from __future__ import annotations

import os
from pathlib import Path

from rich.console import Console
from rich.text import Text

from todos_tool.event_normalizer import EventCategory, NormalizedEvent

CATEGORY_STYLES = {
    "assistant": "white",
    "thinking": "dim italic cyan",
    "tool:start": "yellow",
    "tool:output": "dim yellow",
    "tool:end": "green",
    "status": "cyan",
    "warning": "bold yellow",
    "error": "bold red",
    "unknown": "magenta",
}

# Stream these categories as continuous blocks (prefix once, then deltas).
_STREAM_CATEGORIES = frozenset({"assistant", "thinking"})


class ConsoleRenderer:
    def __init__(self, *, no_color: bool = False, log_path: Path | None = None) -> None:
        force_no_color = no_color or bool(os.environ.get("NO_COLOR"))
        self.console = Console(
            force_terminal=not force_no_color,
            no_color=force_no_color,
            highlight=False,
        )
        self.log_path = log_path
        self._stream_category: EventCategory | None = None
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)

    def render(self, event: NormalizedEvent) -> None:
        if event.category in _STREAM_CATEGORIES:
            self._render_stream(event)
            return

        self._close_stream()
        label = f"[{event.category}]"
        style = CATEGORY_STYLES.get(event.category, "white")
        text = Text()
        text.append(label + " ", style=style)
        text.append(event.text)
        self.console.print(text)
        self._log(f"{label} {event.text}\n")

    def flush(self) -> None:
        """Ensure any open streamed block ends with a newline."""
        self._close_stream()

    def info(self, message: str) -> None:
        self._close_stream()
        self.console.print(f"[bold blue][info][/] {message}")
        self._log(f"[info] {message}\n")

    def warn(self, message: str) -> None:
        self._close_stream()
        self.console.print(f"[bold yellow][warning][/] {message}")
        self._log(f"[warning] {message}\n")

    def error(self, message: str) -> None:
        self._close_stream()
        self.console.print(f"[bold red][error][/] {message}")
        self._log(f"[error] {message}\n")

    def rule(self, title: str) -> None:
        self._close_stream()
        self.console.rule(title)
        self._log(f"--- {title} ---\n")

    def _render_stream(self, event: NormalizedEvent) -> None:
        style = CATEGORY_STYLES.get(event.category, "white")
        if self._stream_category != event.category:
            self._close_stream()
            self._stream_category = event.category
            if event.category == "thinking":
                prefix = Text()
                prefix.append("[thinking] ", style=style)
                self.console.print(prefix, end="")
                self._log("[thinking] ")
            # Assistant text streams without a per-chunk / block prefix.

        styled = Text(event.text, style=style) if event.category == "thinking" else event.text
        self.console.print(styled, end="", soft_wrap=True)
        self._log(event.text)

    def _close_stream(self) -> None:
        if self._stream_category is None:
            return
        self.console.print()
        self._log("\n")
        self._stream_category = None

    def _log(self, text: str) -> None:
        if self.log_path is None:
            return
        # Persisted logs must not contain terminal color codes
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(text)
