"""JSONL event sink."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TextIO

from core_tools.observability.events import ConsoleEvent, LogLevel
from core_tools.observability.redaction import RedactionPolicy, redact_event


class JsonlEventSink:
    """Write redacted events as one JSON object per line."""

    def __init__(
        self,
        target: TextIO | Path,
        *,
        log_level: LogLevel = "normal",
        policy: RedactionPolicy | None = None,
    ) -> None:
        self._policy = policy or RedactionPolicy()
        self._log_level = log_level
        if isinstance(target, Path):
            target.parent.mkdir(parents=True, exist_ok=True)
            self._handle = target.open("a", encoding="utf-8")
            self._owns_handle = True
        else:
            self._handle = target
            self._owns_handle = False

    def emit(self, event: ConsoleEvent) -> None:
        safe = redact_event(
            event,
            policy=self._policy,
            output_level=self._log_level,
        )
        self._handle.write(json.dumps(safe.to_dict(), sort_keys=True) + "\n")
        self._handle.flush()

    def close(self) -> None:
        if self._owns_handle:
            self._handle.close()
