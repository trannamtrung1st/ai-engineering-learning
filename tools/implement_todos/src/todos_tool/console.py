"""Optional color console output with plain-text fallback."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from todos_tool.cursor_stream import EventCategory, NormalizedEvent

CATEGORY_STYLES = {
    "assistant": "",
    "thinking": "\033[2;36m",
    "tool:start": "\033[33m",
    "tool:output": "\033[2;33m",
    "tool:end": "\033[32m",
    "status": "\033[36m",
    "warning": "\033[1;33m",
    "error": "\033[1;31m",
    "unknown": "\033[35m",
}

_STREAM_CATEGORIES = frozenset({"assistant", "thinking"})
_RESET = "\033[0m"


class ConsoleRenderer:
    def __init__(
        self,
        *,
        no_color: bool = False,
        log_path: Path | None = None,
        file_log_path: Path | None = None,
    ) -> None:
        force_no_color = no_color or bool(os.environ.get("NO_COLOR"))
        self.no_color = force_no_color
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
        tee = cls(no_color=renderer.no_color, file_log_path=log_path)
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
                self._log(f"[{event.category}] {event.text}\n")
            return

        if event.category in _STREAM_CATEGORIES:
            self._render_stream(event)
            return

        self._close_stream()
        style = "" if self.no_color else CATEGORY_STYLES.get(event.category, "")
        label = f"[{event.category}] "
        text = f"{style}{label}{event.text}{_RESET if style else ''}"
        self._print(text)
        self._log(f"{label}{event.text}\n")

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
        prefix = "[info] "
        styled = f"\033[1;34m{prefix}{message}{_RESET}" if not self.no_color else prefix + message
        self._print(styled)
        self._log(f"{prefix}{message}\n")

    def warn(self, message: str) -> None:
        primary = self._primary()
        if primary is not self:
            primary.warn(message)
            self._log(f"[warning] {message}\n")
            return
        self._close_stream()
        prefix = "[warning] "
        styled = f"\033[1;33m{prefix}{message}{_RESET}" if not self.no_color else prefix + message
        self._print(styled)
        self._log(f"{prefix}{message}\n")

    def error(self, message: str) -> None:
        primary = self._primary()
        if primary is not self:
            primary.error(message)
            self._log(f"[error] {message}\n")
            return
        self._close_stream()
        prefix = "[error] "
        styled = f"\033[1;31m{prefix}{message}{_RESET}" if not self.no_color else prefix + message
        self._print(styled)
        self._log(f"{prefix}{message}\n")

    def rule(self, title: str) -> None:
        primary = self._primary()
        if primary is not self:
            primary.rule(title)
            self._log(f"--- {title} ---\n")
            return
        self._close_stream()
        line = f"--- {title} ---"
        self._print(line)
        self._log(f"{line}\n")

    def _render_stream(self, event: NormalizedEvent) -> None:
        if self._stream_category != event.category:
            self._close_stream()
            self._stream_category = event.category
            if event.category == "thinking":
                prefix = "[thinking] "
                styled = f"\033[2;36m{prefix}{_RESET}" if not self.no_color else prefix
                sys.stdout.write(styled)
                sys.stdout.flush()
                self._log(prefix)

        if event.category == "thinking" and not self.no_color:
            sys.stdout.write(f"\033[2;36m{event.text}{_RESET}")
        else:
            sys.stdout.write(event.text)
        sys.stdout.flush()
        self._log(event.text)

    def _close_stream(self) -> None:
        if self._stream_category is None:
            return
        sys.stdout.write("\n")
        sys.stdout.flush()
        self._log("\n")
        self._stream_category = None

    def _print(self, text: str) -> None:
        print(text, file=sys.stdout)

    def _log(self, text: str) -> None:
        log_path = self._file_log_path or self.log_path
        if log_path is None:
            return
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(text)
