"""JSONL event sink."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TextIO

from core_tools.observability.events import ConsoleEvent
from core_tools.observability.redaction import RedactionPolicy, redact_event

_STREAMING_CATEGORIES = frozenset({"thinking", "response"})


class JsonlEventSink:
    """Write redacted events as one JSON object per line."""

    def __init__(
        self,
        target: TextIO | Path,
        *,
        policy: RedactionPolicy | None = None,
    ) -> None:
        self._policy = policy or RedactionPolicy()
        if isinstance(target, Path):
            target.parent.mkdir(parents=True, exist_ok=True)
            self._handle = target.open("a", encoding="utf-8")
            self._owns_handle = True
        else:
            self._handle = target
            self._owns_handle = False
        self._stream_buffer_category: str | None = None
        self._stream_buffer_message: str = ""
        self._stream_buffer_event: ConsoleEvent | None = None

    def emit(self, event: ConsoleEvent) -> None:
        if event.category in _STREAMING_CATEGORIES:
            if (
                self._stream_buffer_category is not None
                and self._stream_buffer_category != event.category
            ):
                self._flush_stream_buffer()
            self._stream_buffer_category = event.category
            self._stream_buffer_message += event.message
            self._stream_buffer_event = event
            return

        self._flush_stream_buffer()
        self._write_event(event)

    def close(self) -> None:
        self._flush_stream_buffer()
        if self._owns_handle:
            self._handle.close()

    def _flush_stream_buffer(self) -> None:
        if self._stream_buffer_event is None:
            return
        buffered = ConsoleEvent(
            category=self._stream_buffer_category or self._stream_buffer_event.category,
            message=self._stream_buffer_message,
            ts=self._stream_buffer_event.ts,
            fields=dict(self._stream_buffer_event.fields),
            level=self._stream_buffer_event.level,
            run_id=self._stream_buffer_event.run_id,
            session_id=self._stream_buffer_event.session_id,
        )
        self._stream_buffer_category = None
        self._stream_buffer_message = ""
        self._stream_buffer_event = None
        self._write_event(buffered)

    def _write_event(self, event: ConsoleEvent) -> None:
        safe = redact_event(event, policy=self._policy)
        self._handle.write(json.dumps(safe.to_dict(), sort_keys=True) + "\n")
        self._handle.flush()
