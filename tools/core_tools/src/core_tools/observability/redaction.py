"""Central redaction and truncation for observability output."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from core_tools.observability.events import ConsoleEvent

_ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")
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
    redactor = StreamingRedactor()
    return redactor.ingest(text) + redactor.flush()


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


_HOLD_ATOMS = (
    "authorization",
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "api_key",
    "apikey",
    "cap",
)
_MAX_ATOM = max(len(atom) for atom in _HOLD_ATOMS)
_SIMPLE_ESCAPES = {
    '"': '"',
    "'": "'",
    "\\": "\\",
    "/": "/",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}


def _hold_suffix_len(component: str) -> int:
    if not component:
        return 0
    lower = component.lower()
    best = 0
    for atom in _HOLD_ATOMS:
        if atom.startswith(lower):
            return len(component)
        for size in range(1, min(len(lower), len(atom)) + 1):
            if atom.startswith(lower[-size:]):
                best = max(best, size)
    return best


class StreamingRedactor:
    """Streaming lexer with incremental identifier components and quoted-value awareness."""

    def __init__(self, *, max_len: int | None = None) -> None:
        self._max_len = max_len
        self._state = "normal"
        self._component = ""
        self._emitted = 0
        self._component_intact = True
        self._sensitive = False
        self._prev_was_api = False
        self._bare_credential = False
        self._auth_key = False
        self._ws = ""
        self._key_quote = ""
        self._cli = False
        self._auth = False
        self._dash = False
        self._value_quote = ""
        self._escape = False
        self._unicode_hex: str | None = None
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
        self._component = ""
        self._emitted = 0
        self._component_intact = True
        self._sensitive = False
        self._prev_was_api = False
        self._bare_credential = False
        self._auth_key = False
        self._ws = ""
        self._key_quote = ""
        self._cli = False
        self._auth = False
        self._dash = False
        self._value_quote = ""
        self._escape = False
        self._unicode_hex = None
        self._content_emitted = 0
        self._trunc_hold = ""
        self._truncated = False

    def pending_span(self) -> int:
        held = max(0, len(self._component) - self._emitted)
        unicode_len = len(self._unicode_hex) if self._unicode_hex is not None else 0
        return held + len(self._ws) + len(self._trunc_hold) + unicode_len + int(self._dash) + int(self._escape)

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
            self._begin_ident(cli=False)
            self._state = "quoted_key"
            self._key_quote = char
            return char
        if char.isalpha():
            self._begin_ident(cli=False)
            return self._step_ident(char)
        return char

    def _begin_ident(self, *, cli: bool) -> None:
        self._state = "ident"
        self._start_component()
        self._sensitive = False
        self._prev_was_api = False
        self._bare_credential = False
        self._auth_key = False
        self._ws = ""
        self._key_quote = ""
        self._cli = cli
        self._auth = False
        self._unicode_hex = None
        self._escape = False

    def _start_component(self) -> None:
        self._component = ""
        self._emitted = 0
        self._component_intact = True

    def _step_ident(self, char: str) -> str:
        if (
            char == "-"
            and not self._cli
            and self._component_intact
            and self._component.lower() == "cap"
        ):
            self._start_component()
            self._state = "cap"
            return _REDACTED
        if _is_ident_char(char):
            return self._feed_ident_char(char)
        outgoing = self._complete_component()
        if char in " \t":
            if self._sensitive and (self._cli or self._bare_credential):
                return outgoing + self._open_value(char)
            if self._sensitive:
                self._ws = char
                self._state = "after_ident"
                return outgoing
            self._reset_ident()
            return f"{outgoing}{char}"
        if char in "=:":
            if self._sensitive:
                return outgoing + self._open_value(char)
            self._reset_ident()
            return f"{outgoing}{char}"
        self._reset_ident()
        return f"{outgoing}{char}"

    def _feed_ident_char(self, char: str) -> str:
        outgoing = ""
        if char in "_-":
            outgoing += self._complete_component()
            self._start_component()
            if self._key_quote:
                return outgoing
            return f"{outgoing}{char}"
        if self._component:
            last = self._component[-1]
            if char.isdigit() and last.isalpha():
                outgoing += self._complete_component()
                self._start_component()
            elif char.isalpha() and last.isdigit():
                outgoing += self._complete_component()
                self._start_component()
            elif char.isupper() and any(part.islower() for part in self._component):
                outgoing += self._complete_component()
                self._start_component()
            elif (
                char.islower()
                and self._component.isupper()
                and len(self._component) >= 2
            ):
                saved = self._component[-1]
                self._component = self._component[:-1]
                if self._emitted > len(self._component):
                    self._emitted = len(self._component)
                outgoing += self._complete_component()
                self._start_component()
                outgoing += self._push_char(saved)
                outgoing += self._push_char(char)
                return outgoing
        return outgoing + self._push_char(char)

    def _push_char(self, char: str) -> str:
        if not self._component_intact:
            return "" if self._key_quote else char
        self._component += char
        if len(self._component) > _MAX_ATOM:
            self._component_intact = False
            outgoing = "" if self._key_quote else self._component[self._emitted :]
            self._start_component()
            self._component_intact = False
            return outgoing
        return self._release_hold()

    def _release_hold(self) -> str:
        if self._key_quote:
            return ""
        hold = _hold_suffix_len(self._component)
        available = len(self._component) - hold
        if available <= self._emitted:
            return ""
        outgoing = self._component[self._emitted : available]
        self._emitted = available
        return outgoing

    def _apply_component_sensitivity(self) -> None:
        if not self._component_intact:
            self._prev_was_api = False
            return
        lower = self._component.lower()
        if lower in _SENSITIVE_PARTS:
            self._sensitive = True
        if self._prev_was_api and lower == "key":
            self._sensitive = True
        if lower == "credential":
            self._bare_credential = True
        if lower == "authorization":
            self._auth_key = True
        self._prev_was_api = lower == "api"

    def _complete_component(self) -> str:
        self._apply_component_sensitivity()
        outgoing = "" if self._key_quote else self._component[self._emitted :]
        self._start_component()
        return outgoing

    def _step_quoted_key(self, char: str) -> str:
        if self._unicode_hex is not None:
            self._unicode_hex += char
            if len(self._unicode_hex) == 4:
                try:
                    decoded = chr(int(self._unicode_hex, 16))
                except ValueError:
                    decoded = ""
                self._unicode_hex = None
                if decoded:
                    self._feed_quoted_decoded(decoded)
            return char
        if self._escape:
            self._escape = False
            if char == "u":
                self._unicode_hex = ""
                return char
            self._feed_quoted_decoded(_SIMPLE_ESCAPES.get(char, char))
            return char
        if char == "\\":
            self._escape = True
            return char
        if char == self._key_quote:
            self._complete_component()
            if self._sensitive:
                self._state = "after_ident"
                self._ws = ""
                return char
            self._reset_ident()
            return char
        if not _is_ident_char(char):
            self._complete_component()
            self._reset_ident()
            return self._step_normal(char)
        self._feed_quoted_decoded(char)
        return char

    def _feed_quoted_decoded(self, char: str) -> None:
        if _is_ident_char(char):
            self._feed_ident_char(char)
            return
        self._complete_component()
        self._start_component()

    def _step_after_ident(self, char: str) -> str:
        if char in " \t":
            self._ws += char
            return ""
        if char in "=:":
            return self._open_value(char)
        emitted = f"{self._component[self._emitted :]}{self._ws}" if not self._key_quote else self._ws
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
        rest = "" if self._key_quote else self._component[self._emitted :]
        emitted = f"{rest}{self._ws}{separator}{_REDACTED}"
        auth = self._auth_key
        self._reset_ident()
        self._auth = auth
        self._state = "value_start"
        return emitted

    def _reset_ident(self) -> None:
        self._state = "normal"
        self._start_component()
        self._sensitive = False
        self._prev_was_api = False
        self._bare_credential = False
        self._auth_key = False
        self._ws = ""
        self._key_quote = ""
        self._cli = False
        self._auth = False
        self._unicode_hex = None
        self._escape = False

    def _flush_state(self) -> str:
        if self._dash:
            self._dash = False
            return "-"
        if self._state == "ident":
            emitted = self._complete_component()
            self._reset_ident()
            return emitted
        if self._state == "quoted_key":
            self._reset_ident()
            return ""
        if self._state == "after_ident":
            emitted = f"{self._component[self._emitted :]}{self._ws}" if not self._key_quote else self._ws
            self._reset_ident()
            return emitted
        self._state = "normal"
        self._value_quote = ""
        self._escape = False
        self._unicode_hex = None
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
