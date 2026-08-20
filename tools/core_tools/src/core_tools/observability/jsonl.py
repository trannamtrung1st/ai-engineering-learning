"""JSONL event sink."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from core_tools.observability.events import ConsoleEvent
from core_tools.observability.redaction import RedactionPolicy, redact_event

_STREAMING_CATEGORIES = frozenset({"thinking", "response"})


@dataclass
class _StreamBuffer:
    category: str
    message: str
    event: ConsoleEvent


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
        self._streams: dict[str, _StreamBuffer] = {}

    def emit(self, event: ConsoleEvent) -> None:
        key = _session_key(event.session_id)
        if event.category in _STREAMING_CATEGORIES:
            buffered = self._streams.get(key)
            if buffered is not None and buffered.category != event.category:
                self._flush_key(key)
                buffered = None
            if buffered is None:
                self._streams[key] = _StreamBuffer(event.category, event.message, event)
            else:
                buffered.message += event.message
                buffered.event = event
            return

        self._flush_key(key)
        self._write_event(event)

    def flush_stream(self, session_id: str | None = None) -> None:
        if session_id is None:
            for key in list(self._streams):
                self._flush_key(key)
            return
        self._flush_key(_session_key(session_id))

    def close(self) -> None:
        self.flush_stream()
        if self._owns_handle:
            self._handle.close()

    def _flush_key(self, key: str) -> None:
        buffered = self._streams.pop(key, None)
        if buffered is None:
            return
        self._write_event(
            ConsoleEvent(
                category=buffered.category,
                message=buffered.message,
                ts=buffered.event.ts,
                fields=dict(buffered.event.fields),
                level=buffered.event.level,
                run_id=buffered.event.run_id,
                session_id=buffered.event.session_id,
            )
        )

    def _write_event(self, event: ConsoleEvent) -> None:
        safe = redact_event(event, policy=self._policy)
        self._handle.write(json.dumps(safe.to_dict(), sort_keys=True) + "\n")
        self._handle.flush()


def _session_key(session_id: str | None) -> str:
    return session_id or ""
