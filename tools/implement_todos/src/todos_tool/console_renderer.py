"""Colorized console rendering for normalized Cursor events."""

from __future__ import annotations

import os
from pathlib import Path

from rich.console import Console
from rich.text import Text

from todos_tool.event_normalizer import NormalizedEvent

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


class ConsoleRenderer:
    def __init__(self, *, no_color: bool = False, log_path: Path | None = None) -> None:
        force_no_color = no_color or bool(os.environ.get("NO_COLOR"))
        self.console = Console(
            force_terminal=not force_no_color,
            no_color=force_no_color,
            highlight=False,
        )
        self.log_path = log_path
        self._assistant_open = False
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)

    def render(self, event: NormalizedEvent) -> None:
        label = f"[{event.category}]"
        style = CATEGORY_STYLES.get(event.category, "white")
        if event.category == "assistant":
            # Stream assistant text without a prefix on every delta chunk
            self.console.print(event.text, end="", soft_wrap=True)
            self._log(event.text)
            self._assistant_open = True
            return

        if self._assistant_open:
            self.console.print()
            self._log("\n")
            self._assistant_open = False

        text = Text()
        text.append(label + " ", style=style)
        text.append(event.text)
        self.console.print(text)
        self._log(f"{label} {event.text}\n")

    def info(self, message: str) -> None:
        self.console.print(f"[bold blue][info][/] {message}")
        self._log(f"[info] {message}\n")

    def warn(self, message: str) -> None:
        self.console.print(f"[bold yellow][warning][/] {message}")
        self._log(f"[warning] {message}\n")

    def error(self, message: str) -> None:
        self.console.print(f"[bold red][error][/] {message}")
        self._log(f"[error] {message}\n")

    def rule(self, title: str) -> None:
        self.console.rule(title)
        self._log(f"--- {title} ---\n")

    def _log(self, text: str) -> None:
        if self.log_path is None:
            return
        # Persisted logs must not contain terminal color codes
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(text)
