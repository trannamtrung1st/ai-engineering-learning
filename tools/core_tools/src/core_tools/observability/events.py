"""Normalized console event model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

LogLevel = Literal["quiet", "normal", "verbose", "trace"]

EventCategory = Literal[
    "phase:start",
    "phase:end",
    "session:start",
    "session:resume",
    "thinking",
    "response",
    "tool:start",
    "tool:end",
    "tool:error",
    "review",
    "state",
    "artifact",
    "retry",
    "warning",
    "error",
    "done",
]

CATEGORY_TAGS: dict[str, str] = {
    "phase:start": "phase:start",
    "phase:end": "phase:end",
    "session:start": "session:start",
    "session:resume": "session:resume",
    "thinking": "thinking",
    "response": "response",
    "tool:start": "tool:start",
    "tool:end": "tool:end",
    "tool:error": "tool:error",
    "review": "review",
    "state": "state",
    "artifact": "artifact",
    "retry": "retry",
    "warning": "warning",
    "error": "error",
    "done": "done",
}

# Minimum log level required to show each category.
CATEGORY_MIN_LEVEL: dict[str, LogLevel] = {
    "phase:start": "normal",
    "phase:end": "normal",
    "session:start": "normal",
    "session:resume": "normal",
    "thinking": "normal",
    "response": "normal",
    "tool:start": "normal",
    "tool:end": "normal",
    "tool:error": "quiet",
    "review": "normal",
    "state": "normal",
    "artifact": "normal",
    "retry": "normal",
    "warning": "normal",
    "error": "quiet",
    "done": "quiet",
}

_LEVEL_ORDER: dict[LogLevel, int] = {
    "quiet": 0,
    "normal": 1,
    "verbose": 2,
    "trace": 3,
}


def category_tag(category: str) -> str:
    """Return the console tag for a category."""

    return CATEGORY_TAGS.get(category, category)


def level_allows(category: str, active_level: LogLevel) -> bool:
    """Return True when *active_level* is high enough for *category*."""

    required = CATEGORY_MIN_LEVEL.get(category, "normal")
    return _LEVEL_ORDER[active_level] >= _LEVEL_ORDER[required]


@dataclass(frozen=True)
class ConsoleEvent:
    """A single structured observability event."""

    category: str
    message: str
    ts: datetime = field(default_factory=lambda: datetime.now(UTC))
    fields: dict[str, Any] = field(default_factory=dict)
    level: LogLevel = "normal"
    run_id: str | None = None
    session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "category": self.category,
            "message": self.message,
            "ts": self.ts.isoformat().replace("+00:00", "Z"),
            "level": self.level,
        }
        if self.run_id is not None:
            payload["run_id"] = self.run_id
        if self.session_id is not None:
            payload["session_id"] = self.session_id
        if self.fields:
            payload["fields"] = dict(self.fields)
        return payload
