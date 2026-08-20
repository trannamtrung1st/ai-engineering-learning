"""Event sink protocol and composable wrappers."""

from __future__ import annotations

from typing import Protocol

from core_tools.observability.events import ConsoleEvent, LogLevel, level_allows


class EventSink(Protocol):
    """Consumer for structured console events."""

    def emit(self, event: ConsoleEvent) -> None:
        """Handle a single event."""

    def flush_stream(self, session_id: str | None = None) -> None:
        """Close an open streaming block; omit session_id to flush every session."""


def flush_stream(sink: EventSink, session_id: str | None = None) -> None:
    """Flush buffered streaming output when the sink supports it."""

    flusher = getattr(sink, "flush_stream", None)
    if flusher is not None:
        flusher(session_id)


class NullSink:
    """No-op sink for tests and disabled observability."""

    def emit(self, event: ConsoleEvent) -> None:
        return None

    def flush_stream(self, session_id: str | None = None) -> None:
        return None


class CompositeSink:
    """Fan-out to multiple sinks."""

    def __init__(self, *sinks: EventSink) -> None:
        self._sinks = list(sinks)

    def emit(self, event: ConsoleEvent) -> None:
        for sink in self._sinks:
            sink.emit(event)

    def flush_stream(self, session_id: str | None = None) -> None:
        for sink in self._sinks:
            flush_stream(sink, session_id)


class FilteredSink:
    """Apply log-level and optional category filters before forwarding."""

    def __init__(
        self,
        sink: EventSink,
        *,
        log_level: LogLevel = "normal",
        no_agent_text: bool = False,
        allowed_categories: frozenset[str] | None = None,
    ) -> None:
        self._sink = sink
        self._log_level = log_level
        self._no_agent_text = no_agent_text
        self._allowed_categories = allowed_categories

    def emit(self, event: ConsoleEvent) -> None:
        if self._allowed_categories is not None and event.category not in self._allowed_categories:
            return
        if not level_allows(event.category, self._log_level):
            return
        if self._no_agent_text and event.category in {"thinking", "response"}:
            return
        self._sink.emit(event)

    def flush_stream(self, session_id: str | None = None) -> None:
        flush_stream(self._sink, session_id)
