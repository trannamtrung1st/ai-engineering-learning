"""Central redaction and truncation for observability output."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from core_tools.observability.events import ConsoleEvent, LogLevel

_CAPABILITY_TOKEN_RE = re.compile(r"cap-[A-Za-z0-9._-]+\.[A-Za-z0-9]+")
_SECRET_KEY_RE = re.compile(
    r"(secret|token|authorization|password|api[_-]?key|credential)",
    re.IGNORECASE,
)
_ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")

_REDACTED = "[REDACTED]"


@dataclass(frozen=True)
class RedactionPolicy:
    """Truncation limits applied after redaction."""

    normal_max: int = 500
    verbose_max: int = 2000
    trace_max: int = 8000

    def max_for_level(self, level: LogLevel) -> int:
        if level == "trace":
            return self.trace_max
        if level == "verbose":
            return self.verbose_max
        return self.normal_max


def redact_value(value: Any, *, max_len: int = 500) -> Any:
    """Recursively redact and truncate a value."""

    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _truncate(_redact_string(value), max_len)
    if isinstance(value, list):
        return [redact_value(item, max_len=max_len) for item in value[:50]]
    if isinstance(value, dict):
        return {
            key: _redact_dict_entry(key, item, max_len=max_len)
            for key, item in list(value.items())[:100]
        }
    return _truncate(_redact_string(str(value)), max_len)


def _redact_dict_entry(key: str, value: Any, *, max_len: int) -> Any:
    key_str = str(key)
    if _SECRET_KEY_RE.search(key_str):
        return _REDACTED
    if _ENV_KEY_RE.match(key_str):
        return _REDACTED
    return redact_value(value, max_len=max_len)


def _redact_string(text: str) -> str:
    return _CAPABILITY_TOKEN_RE.sub(_REDACTED, text)


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def redact_event(
    event: ConsoleEvent,
    *,
    policy: RedactionPolicy | None = None,
    output_level: LogLevel = "normal",
) -> ConsoleEvent:
    """Return a copy of *event* with redacted message and fields."""

    policy = policy or RedactionPolicy()
    max_len = policy.max_for_level(output_level)
    return ConsoleEvent(
        category=event.category,
        message=redact_value(event.message, max_len=max_len),
        ts=event.ts,
        fields=redact_value(event.fields, max_len=max_len),
        level=event.level,
        run_id=event.run_id,
        session_id=event.session_id,
    )
