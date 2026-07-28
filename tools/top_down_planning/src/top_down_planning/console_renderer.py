"""Colorized console rendering for normalized Cursor events."""

from __future__ import annotations

import os
from pathlib import Path

from rich.console import Console
from rich.text import Text

from top_down_planning.event_normalizer import EventCategory, NormalizedEvent

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

_STREAM_CATEGORIES = frozenset({"assistant", "thinking"})


class ConsoleRenderer:
    def __init__(
        self,
        *,
        no_color: bool = False,
        log_path: Path | None = None,
        file_log_path: Path | None = None,
    ) -> None:
        force_no_color = no_color or bool(os.environ.get("NO_COLOR"))
        self.console = Console(
            force_terminal=not force_no_color,
            no_color=force_no_color,
            highlight=False,
            stderr=True,
        )
        self.log_path = log_path or file_log_path
        self._file_log_path = file_log_path
        self._stream_category: EventCategory | None = None
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def with_file_logging(
        cls,
        renderer: ConsoleRenderer,
        log_path: Path,
    ) -> ConsoleRenderer:
        if renderer.log_path == log_path:
            return renderer
        tee = cls(no_color=renderer.console.no_color, file_log_path=log_path)
        tee.console = renderer.console
        tee._stream_category = renderer._stream_category
        tee._delegate = renderer
        return tee

    def _primary(self) -> ConsoleRenderer:
        return getattr(self, "_delegate", self)

    def render(self, event: NormalizedEvent) -> None:
        primary = self._primary()
        if primary is not self:
            primary.render(event)
            if event.category in _STREAM_CATEGORIES:
                self._render_stream_to_log(event)
            else:
                label = f"[{event.category}]"
                self._log(f"{label} {event.text}\n")
            return

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

    def _render_stream_to_log(self, event: NormalizedEvent) -> None:
        if self._file_log_path is None:
            return
        if event.category == "thinking" and self._stream_category != event.category:
            self._log("[thinking] ")
        self._log(event.text)
        self._stream_category = event.category

    def flush(self) -> None:
        primary = self._primary()
        if primary is not self:
            primary.flush()
            if self._stream_category is not None:
                self._log("\n")
                self._stream_category = None
            return
        self._close_stream()

    def info(self, message: str) -> None:
        primary = self._primary()
        if primary is not self:
            primary.info(message)
            self._log(f"[info] {message}\n")
            return
        self._close_stream()
        self.console.print(f"[bold blue][info][/] {message}")
        self._log(f"[info] {message}\n")

    def warn(self, message: str) -> None:
        primary = self._primary()
        if primary is not self:
            primary.warn(message)
            self._log(f"[warning] {message}\n")
            return
        self._close_stream()
        self.console.print(f"[bold yellow][warning][/] {message}")
        self._log(f"[warning] {message}\n")

    def error(self, message: str) -> None:
        primary = self._primary()
        if primary is not self:
            primary.error(message)
            self._log(f"[error] {message}\n")
            return
        self._close_stream()
        self.console.print(f"[bold red][error][/] {message}")
        self._log(f"[error] {message}\n")

    def rule(self, title: str) -> None:
        primary = self._primary()
        if primary is not self:
            primary.rule(title)
            self._log(f"--- {title} ---\n")
            return
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
        log_path = self._file_log_path or self.log_path
        if log_path is None:
            return
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(text)
