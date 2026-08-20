"""Central redaction and truncation for observability output."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from core_tools.observability.events import ConsoleEvent

_CAPABILITY_TOKEN_RE = re.compile(r"cap-[A-Za-z0-9._-]+\.[A-Za-z0-9]+")
_ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")
_SENSITIVE_ATOM = (
    r"(?:password|passwd|secret|token|credential|authorization|api[_-]?key)"
)
_SENSITIVE_IDENT = rf"(?:[A-Za-z][A-Za-z0-9]*[_-])*{_SENSITIVE_ATOM}(?:[_-][A-Za-z0-9]+)*"
_QUOTED_VALUE = r"(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')"
_AUTH_HEADER_RE = re.compile(
    rf"(?i)((?:[\"'])?(?:[A-Za-z][A-Za-z0-9_-]*[_-])?authorization(?:[\"'])?\s*[=:]\s*)(?:{_QUOTED_VALUE}|[^\r\n]+)"
)
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    rf"(?i)(?<![A-Za-z0-9])([\"']?)({_SENSITIVE_IDENT})\1\s*([=:])\s*(?:{_QUOTED_VALUE}|\S+)"
)
_CLI_SECRET_RE = re.compile(
    rf"(?i)(--{_SENSITIVE_IDENT})(\s+|=)(?:{_QUOTED_VALUE}|\S+)"
)
_BARE_CREDENTIAL_RE = re.compile(
    r"\b(credential)\s+[A-Za-z0-9._\-+=/]{4,}",
    re.IGNORECASE,
)
_REDACTED = "[REDACTED]"
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
    if _ident_is_sensitive(key_str) or _ENV_KEY_RE.match(key_str):
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
    text = _SENSITIVE_ASSIGNMENT_RE.sub(rf"\1\2\3{_REDACTED}", text)
    return _BARE_CREDENTIAL_RE.sub(rf"\1 {_REDACTED}", text)


_CAMEL_SPLIT_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")
_SENSITIVE_PARTS = frozenset(
    {
        "authorization",
        "password",
        "passwd",
        "secret",
        "token",
        "credential",
        "apikey",
    }
)


def _is_ident_char(char: str) -> bool:
    return char.isalnum() or char in "_-"


def _ident_components(ident: str) -> list[str]:
    parts: list[str] = []
    for chunk in ident.replace("-", "_").split("_"):
        if not chunk:
            continue
        pieces = _CAMEL_SPLIT_RE.findall(chunk)
        parts.extend(piece.lower() for piece in pieces or [chunk.lower()])
    return parts


def _ident_is_sensitive(ident: str) -> bool:
    parts = _ident_components(ident)
    if any(part in _SENSITIVE_PARTS for part in parts):
        return True
    for first, second in zip(parts, parts[1:]):
        if first == "api" and second == "key":
            return True
    return False


def _should_hold_ident(ident: str) -> bool:
    if not ident:
        return False
    if _ident_is_sensitive(ident):
        return False
    if ident.endswith(("_", "-")):
        return True
    lower = ident.lower().replace("-", "_")
    for atom in (*_SENSITIVE_ATOMS, "cap"):
        if atom.startswith(lower):
            return True
        for size in range(1, min(len(lower), len(atom)) + 1):
            if atom.startswith(lower[-size:]):
                return True
    return False


class StreamingRedactor:
    """Streaming lexer with semantic identifier state and quoted-value awareness."""

    def __init__(self, *, max_len: int | None = None) -> None:
        self._max_len = max_len
        self._state = "normal"
        self._ident = ""
        self._sensitive = False
        self._emitted_len = 0
        self._ws = ""
        self._key_quote = ""
        self._cli = False
        self._auth = False
        self._dash = False
        self._value_quote = ""
        self._escape = False
        self._content_emitted = 0
        self._trunc_hold = ""
        self._truncated = False

    def ingest(self, delta: str) -> str:
        if not delta:
            return ""
        return self._apply_truncation(self._lex(_sanitize_surrogates(delta), flush=False), flush=False)

    def flush(self) -> str:
        return self._apply_truncation(self._lex("", flush=True), flush=True)

    def reset(self) -> None:
        self._state = "normal"
        self._ident = ""
        self._sensitive = False
        self._emitted_len = 0
        self._ws = ""
        self._key_quote = ""
        self._cli = False
        self._auth = False
        self._dash = False
        self._value_quote = ""
        self._escape = False
        self._content_emitted = 0
        self._trunc_hold = ""
        self._truncated = False

    def _lex(self, incoming: str, *, flush: bool) -> str:
        outgoing = [self._step(char) for char in incoming]
        if flush:
            outgoing.append(self._flush_state())
        return "".join(outgoing)

    def _step(self, char: str) -> str:
        if self._state == "normal":
            return self._step_normal(char)
        if self._state == "ident":
            return self._step_ident(char)
        if self._state == "quoted_key":
            return self._step_quoted_key(char)
        if self._state == "after_ident":
            return self._step_after_ident(char)
        if self._state == "value_start":
            return self._step_value_start(char)
        if self._state == "quoted_value":
            return self._step_quoted_value(char)
        if self._state == "unquoted_value":
            return self._step_unquoted_value(char)
        if self._state == "line_value":
            return self._step_line_value(char)
        if self._state == "cap":
            return self._step_cap(char)
        return char

    def _step_normal(self, char: str) -> str:
        if self._dash:
            self._dash = False
            if char == "-":
                self._begin_ident(cli=True)
                return "--"
            return f"-{self._step_normal(char)}"
        if char == "-":
            self._dash = True
            return ""
        if char in "\"'":
            self._state = "quoted_key"
            self._key_quote = char
            self._ident = ""
            self._sensitive = False
            self._emitted_len = 0
            return ""
        if char.isalpha():
            self._begin_ident(cli=False)
            return self._step_ident(char)
        return char

    def _begin_ident(self, *, cli: bool) -> None:
        self._state = "ident"
        self._ident = ""
        self._sensitive = False
        self._emitted_len = 0
        self._ws = ""
        self._key_quote = ""
        self._cli = cli
        self._auth = False

    def _step_ident(self, char: str) -> str:
        if _is_ident_char(char):
            self._ident += char
            self._sensitive = self._sensitive or _ident_is_sensitive(self._ident)
            if self._ident == "cap-" and not self._cli:
                self._state = "cap"
                self._emitted_len = len(self._ident)
                return _REDACTED
            if self._sensitive or not _should_hold_ident(self._ident):
                return self._emit_ident_tail()
            return ""
        if char in " \t":
            if self._cli and self._sensitive:
                return self._open_value(char)
            if self._sensitive:
                self._ws = char
                self._state = "after_ident"
                return self._release_ident()
            emitted = self._release_ident()
            self._reset_ident()
            return f"{emitted}{char}"
        if char in "=:":
            if self._sensitive:
                return self._open_value(char)
            emitted = self._release_ident()
            self._reset_ident()
            return f"{emitted}{char}"
        emitted = self._release_ident()
        self._reset_ident()
        return f"{emitted}{char}"

    def _step_quoted_key(self, char: str) -> str:
        if self._escape:
            self._escape = False
            self._ident += char
            self._sensitive = self._sensitive or _ident_is_sensitive(self._ident)
            return ""
        if char == "\\":
            self._escape = True
            return ""
        if char == self._key_quote:
            if self._sensitive:
                self._state = "after_ident"
                self._ws = ""
                return ""
            emitted = f"{self._key_quote}{self._ident}{self._key_quote}"
            self._reset_ident()
            return emitted
        self._ident += char
        self._sensitive = self._sensitive or _ident_is_sensitive(self._ident)
        return ""

    def _step_after_ident(self, char: str) -> str:
        if char in " \t":
            self._ws += char
            return ""
        if char in "=:":
            return self._open_value(char)
        emitted = f"{self._format_key()}{self._ws}"
        self._reset_ident()
        return f"{emitted}{self._step_normal(char)}"

    def _step_value_start(self, char: str) -> str:
        if char in " \t":
            return ""
        if char in "\"'":
            self._state = "quoted_value"
            self._value_quote = char
            self._escape = False
            return ""
        if self._auth:
            self._state = "line_value"
            return self._step_line_value(char)
        self._state = "unquoted_value"
        return self._step_unquoted_value(char)

    def _step_quoted_value(self, char: str) -> str:
        if self._escape:
            self._escape = False
            return ""
        if char == "\\":
            self._escape = True
            return ""
        if char == self._value_quote:
            self._state = "normal"
            self._value_quote = ""
            return ""
        return ""

    def _step_unquoted_value(self, char: str) -> str:
        if char.isspace() or char in ",;}]":
            self._state = "normal"
            return char
        return ""

    def _step_line_value(self, char: str) -> str:
        if char in "\r\n":
            self._state = "normal"
            return char
        return ""

    def _step_cap(self, char: str) -> str:
        if char.isalnum() or char in "._-":
            return ""
        self._state = "normal"
        return char

    def _open_value(self, separator: str) -> str:
        auth = "authorization" in _ident_components(self._ident)
        emitted = f"{self._format_key()}{self._ws}{separator}{_REDACTED}"
        self._reset_ident()
        self._auth = auth
        self._state = "value_start"
        return emitted

    def _emit_ident_tail(self) -> str:
        piece = self._ident[self._emitted_len :]
        self._emitted_len = len(self._ident)
        return piece

    def _format_key(self) -> str:
        if self._cli:
            return "" if self._emitted_len else f"--{self._ident}"
        if self._key_quote:
            return f"{self._key_quote}{self._ident}{self._key_quote}"
        return "" if self._emitted_len else self._ident

    def _release_ident(self) -> str:
        if self._key_quote and not self._emitted_len:
            return f"{self._key_quote}{self._ident}{self._key_quote}"
        return self._emit_ident_tail()

    def _reset_ident(self) -> None:
        self._state = "normal"
        self._ident = ""
        self._sensitive = False
        self._emitted_len = 0
        self._ws = ""
        self._key_quote = ""
        self._cli = False
        self._auth = False

    def _flush_state(self) -> str:
        if self._dash:
            self._dash = False
            return "-"
        if self._state == "ident":
            emitted = self._release_ident()
            self._reset_ident()
            return emitted
        if self._state == "quoted_key":
            emitted = f"{self._key_quote}{self._ident}"
            self._reset_ident()
            return emitted
        if self._state == "after_ident":
            emitted = f"{self._format_key()}{self._ws}"
            self._reset_ident()
            return emitted
        self._state = "normal"
        self._value_quote = ""
        self._escape = False
        return ""

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
