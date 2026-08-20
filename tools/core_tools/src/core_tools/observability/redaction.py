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
_SENSITIVE_IDENT = (
    r"(?:[A-Za-z][A-Za-z0-9_-]*)?(?:password|passwd|secret|token|credential|"
    r"authorization|api[_-]?key)[A-Za-z0-9_-]*"
)
_AUTH_HEADER_RE = re.compile(
    r"(?i)((?:[A-Za-z][A-Za-z0-9_-]*[_-])?authorization\s*[=:]\s*)([^\r\n]+)"
)
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    rf"(?i)\b({_SENSITIVE_IDENT})\s*([=:])\s*(?:[\"'][^\"']+[\"']|\S+)"
)
_CLI_SECRET_RE = re.compile(
    rf"(?i)(--{_SENSITIVE_IDENT})(\s+|=)(?:[\"'][^\"']+[\"']|\S+)"
)
_BARE_CREDENTIAL_RE = re.compile(
    r"\b(credential)\s+[A-Za-z0-9._\-+=/]{4,}",
    re.IGNORECASE,
)
_REDACTED = "[REDACTED]"
_LOOKBEHIND = 80
_SENSITIVE_ATOMS = (
    "authorization",
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "api_key",
    "apikey",
)
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
    text = _CLI_SECRET_RE.sub(rf"\1\2{_REDACTED}", text)
    text = _SENSITIVE_ASSIGNMENT_RE.sub(rf"\1\2{_REDACTED}", text)
    return _BARE_CREDENTIAL_RE.sub(rf"\1 {_REDACTED}", text)


def _is_ident_char(char: str) -> bool:
    return char.isalnum() or char in "_-"


def _ident_is_sensitive(ident: str) -> bool:
    lower = ident.lower().replace("-", "_")
    return any(atom in lower for atom in _SENSITIVE_ATOMS)


def _read_ident(text: str, start: int) -> str:
    index = start
    if index >= len(text) or not text[index].isalpha():
        return ""
    index += 1
    while index < len(text) and _is_ident_char(text[index]):
        index += 1
    return text[start:index]


def _has_ident_boundary(text: str, index: int) -> bool:
    return index == 0 or not text[index - 1].isalnum()


def _match_open_secret(text: str, index: int) -> tuple[str, str, int] | None:
    """Return (emitted, follow_state, consumed) when a secret construct starts at index."""

    if index >= len(text) or not _has_ident_boundary(text, index):
        return None
    if text.startswith("--", index):
        ident = _read_ident(text, index + 2)
        if not ident or not _ident_is_sensitive(ident):
            return None
        cursor = index + 2 + len(ident)
        if cursor >= len(text) or text[cursor] not in " \t=":
            return None
        separator = text[cursor]
        cursor += 1
        while cursor < len(text) and text[cursor] in " \t":
            separator += text[cursor]
            cursor += 1
        return (f"--{ident}{separator}{_REDACTED}", _follow_state(text, cursor, "ws"), cursor - index)
    if text.startswith("cap-", index):
        return (_REDACTED, "cap", 4)
    ident = _read_ident(text, index)
    if not ident or not _ident_is_sensitive(ident):
        return None
    cursor = index + len(ident)
    if cursor >= len(text) or text[cursor] not in "=:":
        return None
    separator = text[cursor]
    cursor += 1
    while cursor < len(text) and text[cursor] in " \t":
        separator += text[cursor]
        cursor += 1
    follow = "line" if "authorization" in ident.lower().replace("-", "_") else "ws"
    return (f"{ident}{separator}{_REDACTED}", _follow_state(text, cursor, follow), cursor - index)


def _follow_state(text: str, cursor: int, default: str) -> str:
    if cursor < len(text) and text[cursor] in "\"'":
        return text[cursor]
    return default


def _find_open_secret(text: str) -> tuple[int, str, str, int] | None:
    for index in range(len(text)):
        matched = _match_open_secret(text, index)
        if matched is not None:
            emitted, state, consumed = matched
            return (index, emitted, state, consumed)
    return None


def _trailing_ident(text: str) -> str:
    index = len(text)
    while index > 0 and _is_ident_char(text[index - 1]):
        index -= 1
    ident = text[index:]
    if ident and ident[0].isalpha():
        return ident
    if ident.startswith("-"):
        return ident
    return ""


def _should_hold_ident(ident: str) -> bool:
    if not ident:
        return False
    if ident.endswith(("_", "-")) or ident.startswith("-"):
        return True
    lower = ident.lower().replace("-", "_")
    if _ident_is_sensitive(ident):
        return True
    for atom in (*_SENSITIVE_ATOMS, "cap"):
        if atom.startswith(lower) or lower.startswith(atom):
            return True
        for size in range(1, min(len(lower), len(atom)) + 1):
            if atom.startswith(lower[-size:]):
                return True
    return False


def _hold_length(text: str) -> int:
    if text.endswith("--"):
        return 2
    if text.endswith("-") and _has_ident_boundary(text, len(text) - 1):
        return 1
    ident = _trailing_ident(text)
    if _should_hold_ident(ident):
        return min(len(ident), _LOOKBEHIND)
    return 0


class StreamingRedactor:
    """Session-local streaming lexer with bounded pending text and value-skip states."""

    def __init__(self, *, max_len: int | None = None) -> None:
        self._max_len = max_len
        self._pending = ""
        self._state = "normal"
        self._content_emitted = 0
        self._trunc_hold = ""
        self._truncated = False

    def ingest(self, delta: str) -> str:
        if not delta:
            return ""
        return self._apply_truncation(self._lex(delta, flush=False), flush=False)

    def flush(self) -> str:
        return self._apply_truncation(self._lex("", flush=True), flush=True)

    def reset(self) -> None:
        self._pending = ""
        self._state = "normal"
        self._content_emitted = 0
        self._trunc_hold = ""
        self._truncated = False

    def _lex(self, incoming: str, *, flush: bool) -> str:
        outgoing: list[str] = []
        data = incoming
        while True:
            if self._state != "normal":
                data = self._skip_secret(data)
                if self._state != "normal":
                    if flush:
                        self._state = "normal"
                    break
                continue
            if data:
                self._pending += data
                data = ""
            drained, leftover = self._drain_pending(flush=flush)
            if drained:
                outgoing.append(drained)
            if leftover:
                data = leftover
                continue
            break
        return "".join(outgoing)

    def _skip_secret(self, data: str) -> str:
        if not data:
            return ""
        if self._state == "line":
            for index, char in enumerate(data):
                if char in "\r\n":
                    self._state = "normal"
                    return data[index:]
            return ""
        if self._state == "cap":
            index = 0
            while index < len(data) and (data[index].isalnum() or data[index] in "._-"):
                index += 1
            if index < len(data):
                self._state = "normal"
                return data[index:]
            return ""
        if self._state in {"\"", "'"}:
            quote = self._state
            start = 1 if data[0] == quote else 0
            end = data.find(quote, start)
            if end == -1:
                return ""
            self._state = "normal"
            return data[end + 1 :]
        for index, char in enumerate(data):
            if char.isspace() or char in ",;":
                self._state = "normal"
                return data[index:]
        return ""

    def _drain_pending(self, *, flush: bool) -> tuple[str, str]:
        text = self._pending
        self._pending = ""
        outgoing: list[str] = []
        index = 0
        while index < len(text):
            remaining = text[index:]
            found = _find_open_secret(remaining)
            if found is not None:
                start, emitted, state, consumed = found
                outgoing.append(remaining[:start])
                outgoing.append(emitted)
                self._state = state
                return ("".join(outgoing), remaining[start + consumed :])
            hold = 0 if flush else _hold_length(remaining)
            if hold == len(remaining):
                self._pending = remaining
                break
            emit_count = len(remaining) - hold
            outgoing.append(remaining[:emit_count])
            index += emit_count
        if flush and self._pending:
            outgoing.append(_redact_string(self._pending))
            self._pending = ""
        return ("".join(outgoing), "")

    def _apply_truncation(self, piece: str, *, flush: bool) -> str:
        if self._max_len is None:
            return piece
        if self._truncated:
            return ""
        data = self._trunc_hold + piece
        self._trunc_hold = ""
        if not data and not flush:
            return ""
        reserve = 3 if self._max_len >= 3 else 0
        budget = self._max_len - reserve
        outgoing: list[str] = []
        if self._content_emitted < budget:
            take = min(budget - self._content_emitted, len(data))
            outgoing.append(data[:take])
            self._content_emitted += take
            data = data[take:]
        if not data:
            if flush and self._trunc_hold:
                outgoing.append(self._trunc_hold)
                self._trunc_hold = ""
            return "".join(outgoing)
        if reserve == 0:
            self._truncated = True
            return "".join(outgoing)
        if len(data) > reserve:
            outgoing.append("...")
            self._truncated = True
            return "".join(outgoing)
        if flush:
            outgoing.append(data)
            return "".join(outgoing)
        self._trunc_hold = data
        return "".join(outgoing)


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    if max_len <= 3:
        return text[:max_len]
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
