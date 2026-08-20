"""Central redaction and truncation for observability output."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from core_tools.observability.events import ConsoleEvent

_CAPABILITY_TOKEN_RE = re.compile(r"cap-[A-Za-z0-9._-]+\.[A-Za-z0-9]+")
_SECRET_KEY_RE = re.compile(
    r"(secret|token|authorization|password|api[_-]?key|credential)",
    re.IGNORECASE,
)
_ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")
_SENSITIVE_NAME = (
    r"(?:[A-Za-z][A-Za-z0-9_-]*[_-])?(?:password|passwd|secret|token|credential|"
    r"authorization|api[_-]?key)"
)
_AUTH_HEADER_RE = re.compile(
    rf"(?i)((?:[A-Za-z][A-Za-z0-9_-]*_)?authorization\s*[=:]\s*(?:Bearer|Basic)\s+)\S+"
)
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    rf"(?i)\b({_SENSITIVE_NAME})\s*([=:])\s*(?:[\"'][^\"']+[\"']|\S+)"
)
_BARE_CREDENTIAL_RE = re.compile(
    r"\b(credential)\s+[A-Za-z0-9._\-+=/]{4,}",
    re.IGNORECASE,
)
_INCOMPLETE_CAPABILITY_RE = re.compile(
    r"(?:^|[^A-Za-z0-9._-])(cap(?:-[A-Za-z0-9._-]*)?)$",
    re.IGNORECASE,
)
_PARTIAL_CAP_RE = re.compile(
    r"(?:^|[^A-Za-z0-9._-])(c(?:a(?:p)?)?)$",
    re.IGNORECASE,
)
_INCOMPLETE_AUTH_RE = re.compile(
    rf"(?i)((?:[A-Za-z][A-Za-z0-9_-]*_)?authorization\s*[=:]\s*"
    rf"(?:Bearer|Basic)?(?:\s+\S*)?)$"
)
_INCOMPLETE_ASSIGNMENT_RE = re.compile(
    rf"(?i)({_SENSITIVE_NAME}\s*[=:]\s*(?:[\"'][^\"']*|[^\s,;]*)?)$"
)
_TRAILING_IDENT_RE = re.compile(r"([A-Za-z][A-Za-z0-9_-]*)$")
_SENSITIVE_ATOMS = (
    "authorization",
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "api_key",
    "api-key",
    "apikey",
    "bearer",
    "basic",
)

_REDACTED = "[REDACTED]"
_SURROGATE_MIN = 0xD800
_SURROGATE_MAX = 0xDFFF


@dataclass(frozen=True)
class RedactionPolicy:
    """Truncation limits applied after redaction."""

    max_message_length: int | None = None


def truncate_text(text: str, max_len: int | None) -> str:
    """Truncate *text* when *max_len* is set; otherwise return unchanged."""

    if max_len is None:
        return text
    return _truncate(text, max_len)


def redact_value(value: Any, *, max_len: int | None = None) -> Any:
    """Recursively redact and truncate a value."""

    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return truncate_text(_redact_string(value), max_len)
    if isinstance(value, list):
        return [redact_value(item, max_len=max_len) for item in value[:50]]
    if isinstance(value, dict):
        return {
            key: _redact_dict_entry(key, item, max_len=max_len)
            for key, item in list(value.items())[:100]
        }
    return truncate_text(_redact_string(str(value)), max_len)


def _redact_dict_entry(key: str, value: Any, *, max_len: int | None) -> Any:
    key_str = str(key)
    if _SECRET_KEY_RE.search(key_str):
        return _REDACTED
    if _ENV_KEY_RE.match(key_str):
        return _REDACTED
    return redact_value(value, max_len=max_len)


def _sanitize_surrogates(text: str) -> str:
    if not any(_SURROGATE_MIN <= ord(ch) <= _SURROGATE_MAX for ch in text):
        return text
    return "".join(
        ch if not (_SURROGATE_MIN <= ord(ch) <= _SURROGATE_MAX) else "\ufffd"
        for ch in text
    )


def _redact_string(text: str) -> str:
    text = _sanitize_surrogates(text)
    text = _CAPABILITY_TOKEN_RE.sub(_REDACTED, text)
    text = _AUTH_HEADER_RE.sub(rf"\1{_REDACTED}", text)
    text = _SENSITIVE_ASSIGNMENT_RE.sub(rf"\1\2{_REDACTED}", text)
    return _BARE_CREDENTIAL_RE.sub(rf"\1 {_REDACTED}", text)


def _ident_looks_sensitive(ident: str) -> bool:
    lower = ident.lower().replace("-", "_")
    for atom in _SENSITIVE_ATOMS:
        atom_n = atom.replace("-", "_")
        if len(lower) >= 3 and atom_n.startswith(lower):
            return True
        if lower.endswith(atom_n) or atom_n in lower:
            return True
    return False


def _secret_hold_length(text: str) -> int:
    """Return how many trailing characters might still complete a secret."""

    if not text:
        return 0
    starts: list[int] = []
    cap = _INCOMPLETE_CAPABILITY_RE.search(text)
    if cap and _CAPABILITY_TOKEN_RE.fullmatch(cap.group(1)) is None:
        starts.append(cap.start(1))
    partial_cap = _PARTIAL_CAP_RE.search(text)
    if partial_cap:
        starts.append(partial_cap.start(1))
    auth = _INCOMPLETE_AUTH_RE.search(text)
    if auth:
        starts.append(auth.start(1))
    assignment = _INCOMPLETE_ASSIGNMENT_RE.search(text)
    if assignment:
        starts.append(assignment.start(1))
    ident = _TRAILING_IDENT_RE.search(text)
    if ident and _ident_looks_sensitive(ident.group(1)):
        starts.append(ident.start(1))
    if not starts:
        return 0
    return len(text) - min(starts)


class StreamingRedactor:
    """Hold incomplete secret prefixes, then redact committed streaming text."""

    def __init__(self, *, max_len: int | None = None) -> None:
        self._max_len = max_len
        self._raw = ""
        self._emitted = ""

    def ingest(self, delta: str) -> str:
        if not delta:
            return ""
        self._raw += delta
        return self._release(flush=False)

    def flush(self) -> str:
        return self._release(flush=True)

    def reset(self) -> None:
        self._raw = ""
        self._emitted = ""

    def _release(self, *, flush: bool) -> str:
        hold = 0 if flush else _secret_hold_length(self._raw)
        committed = self._raw if hold == 0 else self._raw[:-hold]
        redacted = truncate_text(_redact_string(committed), self._max_len)
        if redacted.startswith(self._emitted):
            new = redacted[len(self._emitted) :]
        else:
            new = redacted
        self._emitted = redacted
        return new


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def redact_event(
    event: ConsoleEvent,
    *,
    policy: RedactionPolicy | None = None,
) -> ConsoleEvent:
    """Return a copy of *event* with redacted message and fields."""

    policy = policy or RedactionPolicy()
    max_len = policy.max_message_length
    return ConsoleEvent(
        category=event.category,
        message=redact_value(event.message, max_len=max_len),
        ts=event.ts,
        fields=redact_value(event.fields, max_len=max_len),
        level=event.level,
        run_id=event.run_id,
        session_id=event.session_id,
    )
