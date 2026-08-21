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
_MAX_CAP_HOLD = 128
_MAX_SUBST_NEST = 8
_MAX_CASE_NEST = 8
_MAX_HEREDOC_TAG = 64
_MAX_HEREDOC_LINE = 256
_MAX_HEREDOC_QUEUE = 8
_MAX_JSON_NEST = 8
_SHELL_WORD_BREAK = frozenset(" \t;|&(){}\r\n<>")
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
        self._key_quote = ""
        self._wrap_quote = ""
        self._inner_quote = ""
        self._quote = ""
        self._cap_held = ""
        self._cap_raw = ""
        self._cap_seen_dot = False
        self._quote_dash = False
        self._cli = False
        self._auth = False
        self._dash = False
        self._value_quote = ""
        self._value_kind = "shell"
        self._json_key = False
        self._json_ctx = False
        self._json_container = False
        self._json_expect_container = False
        self._json_pos = ""
        self._json_stack: list[str] = []
        self._inner_is_json_key = False
        self._dollar = False
        self._lt = False
        self._gt = False
        self._subst_stack: list[tuple[str, str, bool]] = []
        self._subst_seen = False
        self._subst_opaque = False
        self._arith_maybe = False
        self._allow_compound = False
        self._subst_word = ""
        self._case_depth = 0
        self._case_arm = ""
        self._cmd_pos = False
        self._cmd_qualified = False
        self._case_class = False
        self._case_class_first = False
        self._case_posix = ""
        self._semi = False
        self._shell_comment = False
        self._heredoc = ""
        self._heredoc_tag = ""
        self._heredoc_line = ""
        self._heredoc_quote = ""
        self._heredoc_strip = False
        self._heredoc_escape = False
        self._heredoc_crlf = False
        self._heredoc_queue: list[tuple[str, bool]] = []
        self._heredoc_body_strip = False
        self._pending_redact = False
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
        self._key_quote = ""
        self._wrap_quote = ""
        self._inner_quote = ""
        self._quote = ""
        self._cap_held = ""
        self._cap_raw = ""
        self._cap_seen_dot = False
        self._quote_dash = False
        self._cli = False
        self._auth = False
        self._dash = False
        self._value_quote = ""
        self._value_kind = "shell"
        self._json_key = False
        self._json_ctx = False
        self._reset_shell_lex()
        self._pending_redact = False
        self._escape = False
        self._unicode_hex = None
        self._content_emitted = 0
        self._trunc_hold = ""
        self._truncated = False

    def pending_span(self) -> int:
        held = max(0, len(self._component) - self._emitted)
        unicode_len = len(self._unicode_hex) if self._unicode_hex is not None else 0
        return (
            held
            + len(self._cap_held)
            + len(self._cap_raw)
            + len(self._trunc_hold)
            + unicode_len
            + len(self._subst_stack)
            + int(self._dash)
            + int(self._escape)
            + int(self._dollar)
            + int(self._lt)
            + int(self._gt)
            + int(self._subst_seen)
            + int(self._subst_opaque)
            + int(self._arith_maybe)
            + int(self._allow_compound)
            + min(len(self._subst_word), 8)
            + self._case_depth
            + int(self._cmd_qualified)
            + int(self._case_class)
            + min(len(self._case_posix), 2)
            + int(self._shell_comment)
            + int(self._heredoc_crlf)
            + len(self._heredoc_tag)
            + len(self._heredoc_line)
            + sum(len(tag) for tag, _strip in self._heredoc_queue)
            + int(self._heredoc_body_strip)
            + int(bool(self._heredoc))
            + len(self._json_stack)
            + int(self._pending_redact)
        )

    def _reset_shell_lex(self) -> None:
        self._json_container = False
        self._json_expect_container = False
        self._json_pos = ""
        self._json_stack = []
        self._inner_is_json_key = False
        self._dollar = False
        self._lt = False
        self._gt = False
        self._subst_stack = []
        self._subst_seen = False
        self._subst_opaque = False
        self._arith_maybe = False
        self._allow_compound = False
        self._subst_word = ""
        self._case_depth = 0
        self._case_arm = ""
        self._cmd_pos = False
        self._cmd_qualified = False
        self._case_class = False
        self._case_class_first = False
        self._case_posix = ""
        self._semi = False
        self._shell_comment = False
        self._heredoc = ""
        self._heredoc_tag = ""
        self._heredoc_line = ""
        self._heredoc_quote = ""
        self._heredoc_strip = False
        self._heredoc_escape = False
        self._heredoc_crlf = False
        self._heredoc_queue = []
        self._heredoc_body_strip = False

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
        if self._state == "cap_candidate":
            return self._step_cap_candidate(char)
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
            self._wrap_quote = char
            self._json_expect_container = True
            self._json_container = False
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
        self._key_quote = ""
        self._wrap_quote = ""
        self._inner_quote = ""
        self._json_key = False
        self._json_ctx = False
        self._json_container = False
        self._json_expect_container = False
        self._json_pos = ""
        self._json_stack = []
        self._inner_is_json_key = False
        self._cli = cli
        self._auth = False
        self._unicode_hex = None
        self._escape = False

    def _start_component(self) -> None:
        self._component = ""
        self._emitted = 0
        self._component_intact = True

    def _is_cap_hyphen(self, char: str) -> bool:
        return (
            char == "-"
            and not self._cli
            and self._component_intact
            and self._component.lower() == "cap"
        )

    def _begin_cap_candidate(self) -> str:
        quoted = bool(self._key_quote or self._quote)
        prefix = f"{self._component}-"
        self._start_component()
        self._state = "cap_candidate"
        self._cap_held = "cap-"
        self._cap_raw = "-" if quoted else prefix
        self._cap_seen_dot = False
        return ""

    def _step_ident(self, char: str) -> str:
        if self._is_cap_hyphen(char):
            return self._begin_cap_candidate()
        if _is_ident_char(char):
            return self._feed_ident_char(char)
        outgoing = self._complete_component()
        if char in " \t":
            if self._sensitive and (self._cli or self._bare_credential):
                return outgoing + self._open_value(char, kind="shell")
            if self._sensitive:
                self._state = "after_ident"
                return f"{outgoing}{char}"
            self._reset_ident()
            return f"{outgoing}{char}"
        if char in "=:":
            if self._sensitive:
                return outgoing + self._open_value(char, kind=self._value_kind_for_separator(char))
            self._reset_ident()
            return f"{outgoing}{char}"
        self._reset_ident()
        return f"{outgoing}{char}"

    def _feed_ident_char(self, char: str) -> str:
        outgoing = ""
        if self._is_cap_hyphen(char):
            return outgoing + self._begin_cap_candidate()
        if char in "_-":
            outgoing += self._complete_component()
            self._start_component()
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
            return char
        self._component += char
        if len(self._component) > _MAX_ATOM:
            self._component_intact = False
            outgoing = self._component[self._emitted :]
            self._start_component()
            self._component_intact = False
            return outgoing
        return self._release_hold()

    def _release_hold(self) -> str:
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
        outgoing = self._component[self._emitted :]
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
                    self._absorb_ident_char(decoded)
            return char
        if self._escape:
            self._escape = False
            self._json_expect_container = False
            if char == "u":
                self._unicode_hex = ""
                return f"\\{char}"
            self._apply_component_sensitivity()
            self._start_component()
            self._absorb_ident_char(_SIMPLE_ESCAPES.get(char, char))
            return "\\" + char
        if char == "\\":
            self._escape = True
            return ""
        if self._json_expect_container:
            if char in " \t":
                return char
            if char in "{[":
                self._json_expect_container = False
                self._enter_json_container(char)
                return char
            self._json_expect_container = False
        if self._json_pos and not self._inner_quote:
            if char in " \t":
                return char
            if char == "{" and self._json_pos == "value":
                self._enter_json_container("{")
                return char
            if char == "[" and self._json_pos == "value":
                self._enter_json_container("[")
                return char
            if char not in "\"'":
                self._abort_json()
        if char == self._key_quote:
            self._apply_component_sensitivity()
            self._start_component()
            if self._sensitive:
                self._state = "after_ident"
                self._json_key = True
                self._key_quote = ""
                self._wrap_quote = ""
                return char
            self._reset_ident()
            return char
        if char in "\"'" and char != self._key_quote:
            self._apply_component_sensitivity()
            self._start_component()
            if self._inner_quote:
                if char == self._inner_quote:
                    if self._sensitive:
                        self._json_key = self._inner_is_json_key
                        self._json_ctx = self._inner_is_json_key
                        self._state = "after_ident"
                    self._inner_quote = ""
                    self._inner_is_json_key = False
                return char
            self._inner_quote = char
            self._inner_is_json_key = self._json_pos == "key"
            return char
        if char in "=:":
            self._apply_component_sensitivity()
            self._start_component()
            if self._sensitive:
                return self._open_value(char, kind=self._value_kind_for_separator(char))
            return char
        if char in " \t":
            self._apply_component_sensitivity()
            self._start_component()
            if self._sensitive and (self._cli or self._bare_credential):
                return self._open_value(char, kind="shell")
            if self._sensitive:
                self._state = "after_ident"
                return char
            self._quote_dash = False
            self._cli = False
            return char
        if char == "-":
            if self._quote_dash and not self._component:
                self._cli = True
                self._quote_dash = False
                return "-"
            if not self._component:
                self._quote_dash = True
                return "-"
            self._quote_dash = False
            if self._is_cap_hyphen(char):
                return self._begin_cap_candidate()
            self._absorb_ident_char(char)
            return char
        if _is_ident_char(char):
            self._quote_dash = False
            self._absorb_ident_char(char)
            return char
        self._apply_component_sensitivity()
        self._start_component()
        self._quote_dash = False
        return char

    def _absorb_ident_char(self, char: str) -> None:
        saved = self._emitted
        if _is_ident_char(char):
            self._feed_ident_char(char)
        else:
            self._apply_component_sensitivity()
            self._start_component()
        self._emitted = min(saved, len(self._component))

    def _step_after_ident(self, char: str) -> str:
        if char in " \t":
            return char
        if char in "=:":
            return self._open_value(char, kind=self._value_kind_for_separator(char))
        self._reset_ident()
        return self._step_normal(char)

    def _step_value_start(self, char: str) -> str:
        if self._pending_redact and char in " \t":
            return char
        prefix = ""
        if self._pending_redact:
            self._pending_redact = False
            prefix = _REDACTED
        if char in " \t":
            return prefix
        if char in "\"'":
            self._state = "quoted_value"
            self._value_quote = char
            self._escape = False
            return prefix
        if char == "\\":
            self._state = "unquoted_value"
            self._escape = True
            return prefix
        if self._auth:
            self._state = "line_value"
            return prefix + self._step_line_value(char)
        self._state = "unquoted_value"
        return prefix + self._step_unquoted_value(char)

    def _step_quoted_value(self, char: str) -> str:
        if self._escape:
            self._escape = False
            if self._case_class:
                self._step_case_class(char)
            elif self._subst_stack:
                self._cmd_qualified = True
            return ""
        if char == "\\":
            self._escape = True
            return ""
        if char == self._value_quote:
            self._state = "unquoted_value"
            self._value_quote = ""
            if self._subst_stack:
                self._cmd_qualified = True
            return ""
        if self._case_class:
            self._step_case_class(char)
        elif self._subst_stack:
            self._cmd_qualified = True
        return ""

    def _value_kind_for_separator(self, separator: str) -> str:
        if separator == ":" and not self._auth_key and (self._json_key or self._json_ctx):
            return "json"
        return "shell"

    def _enter_json_container(self, opener: str) -> None:
        if len(self._json_stack) >= _MAX_JSON_NEST:
            self._abort_json()
            return
        self._json_stack.append(opener)
        self._json_container = True
        self._json_pos = "key" if opener == "{" else "value"

    def _abort_json(self) -> None:
        self._json_container = False
        self._json_expect_container = False
        self._json_pos = ""
        self._json_stack = []
        self._inner_is_json_key = False

    def _push_subst(self, closer: str, kind: str = "cmd") -> None:
        self._subst_seen = True
        saved_cmd = self._cmd_pos
        self._cmd_pos = kind == "cmd"
        if self._subst_opaque:
            return
        if len(self._subst_stack) >= _MAX_SUBST_NEST:
            self._subst_opaque = True
            self._subst_stack.clear()
            return
        self._subst_stack.append((closer, kind, saved_cmd))

    def _pop_subst(self) -> None:
        _closer, _kind, saved_cmd = self._subst_stack.pop()
        self._cmd_pos = saved_cmd
        if not self._subst_stack and not self._subst_opaque:
            self._subst_seen = False

    def _subst_closer(self) -> str:
        return self._subst_stack[-1][0] if self._subst_stack else ""

    def _subst_kind(self) -> str:
        return self._subst_stack[-1][1] if self._subst_stack else ""

    def _in_cmd_grammar(self) -> bool:
        return bool(
            self._cmd_pos
            and not self._cmd_qualified
            and self._subst_stack
            and self._subst_stack[-1][1] == "cmd"
        )

    def _extend_shell_word(self, char: str) -> None:
        if char.isalnum() or char == "_":
            if len(self._subst_word) < 8:
                self._subst_word += char
            return
        self._cmd_qualified = True
        if char in "./" and len(self._subst_word) < 8:
            self._subst_word += char

    def _flush_subst_word(self) -> None:
        word = self._subst_word.lower()
        self._subst_word = ""
        if not word:
            return
        if self._in_cmd_grammar() and word == "case":
            if self._case_depth < _MAX_CASE_NEST:
                self._case_depth += 1
            else:
                self._subst_opaque = True
            self._case_arm = "word"
            self._cmd_pos = False
            self._cmd_qualified = False
            return
        if self._case_depth and self._in_cmd_grammar() and word == "esac":
            self._case_depth -= 1
            self._case_arm = "" if not self._case_depth else self._case_arm
            self._cmd_pos = False
            self._cmd_qualified = False
            return
        if self._case_arm == "word":
            self._case_arm = "in"
            self._cmd_pos = False
            self._cmd_qualified = False
            return
        if self._case_arm == "in" and word == "in":
            self._case_arm = "pattern"
            self._cmd_pos = False
            self._cmd_qualified = False
            return
        self._cmd_pos = False
        self._cmd_qualified = False

    def _note_subst_char(self, char: str) -> None:
        if char.isalnum() or char in "_./":
            if char in "./":
                self._cmd_qualified = True
            if len(self._subst_word) < 8:
                self._subst_word += char
            return
        if self._case_arm == "pattern":
            if self._case_class:
                self._step_case_class(char)
                return
            if char == "[":
                self._flush_subst_word()
                self._enter_case_class()
                return
            if char == "|":
                self._flush_subst_word()
                return
        self._flush_subst_word()
        if char == ";":
            if self._semi:
                self._semi = False
                self._cmd_pos = True
                self._cmd_qualified = False
                if self._case_depth:
                    self._case_arm = "pattern"
                    self._case_class = False
                    self._case_class_first = False
                    self._case_posix = ""
            else:
                self._semi = True
                self._cmd_pos = True
                self._cmd_qualified = False
            return
        if char == "&" and self._semi:
            self._semi = False
            self._cmd_pos = True
            self._cmd_qualified = False
            if self._case_depth:
                self._case_arm = "pattern"
                self._case_class = False
                self._case_class_first = False
                self._case_posix = ""
            return
        self._semi = False
        if char in "|&\r\n":
            self._cmd_pos = True
            self._cmd_qualified = False
        elif char == "(":
            self._cmd_pos = True
            self._cmd_qualified = False

    def _enter_case_class(self) -> None:
        self._case_class = True
        self._case_class_first = True
        self._case_posix = ""

    def _step_case_class(self, char: str) -> None:
        if self._case_posix == "open":
            if char in ":.=":
                self._case_posix = char
                return
            self._case_posix = ""
        elif self._case_posix in (":", ".", "="):
            if char == self._case_posix:
                self._case_posix = "end"
            return
        elif self._case_posix == "end":
            if char == "]":
                self._case_posix = ""
                return
            if char in ":.=":
                self._case_posix = char
                return
            self._case_posix = ""
        if self._case_class_first:
            if char in "!^":
                return
            self._case_class_first = False
            if char == "]":
                return
            if char == "[":
                self._case_posix = "open"
                return
            return
        if char == "[":
            self._case_posix = "open"
            return
        if char == "]":
            self._case_class = False
            self._case_class_first = False
            self._case_posix = ""

    def _append_heredoc_tag(self, char: str) -> None:
        if len(self._heredoc_tag) >= _MAX_HEREDOC_TAG:
            self._subst_opaque = True
            return
        self._heredoc_tag += char

    def _finish_heredoc_word(self) -> None:
        if not self._heredoc_tag:
            return
        if len(self._heredoc_queue) >= _MAX_HEREDOC_QUEUE:
            self._subst_opaque = True
            self._heredoc_tag = ""
            return
        self._heredoc_queue.append((self._heredoc_tag, self._heredoc_strip))
        self._heredoc_tag = ""
        self._heredoc_strip = False

    def _activate_heredoc(self, tag: str, strip: bool) -> None:
        self._heredoc_tag = tag
        self._heredoc_body_strip = strip
        self._heredoc = "body"
        self._heredoc_line = ""

    def _begin_heredoc_body(self) -> None:
        self._finish_heredoc_word()
        self._heredoc_quote = ""
        self._heredoc_escape = False
        if self._heredoc_queue:
            tag, strip = self._heredoc_queue.pop(0)
            self._activate_heredoc(tag, strip)
            return
        self._heredoc = ""
        self._heredoc_tag = ""
        self._heredoc_line = ""
        self._heredoc_body_strip = False

    def _step_heredoc_tag(self, char: str) -> str:
        if self._heredoc_crlf:
            self._heredoc_crlf = False
            if char == "\n":
                return ""
        if self._heredoc_escape:
            self._heredoc_escape = False
            if char == "\n":
                return ""
            if char == "\r":
                self._heredoc_crlf = True
                return ""
            self._append_heredoc_tag(char)
            return ""
        if char == "\\" and self._heredoc_quote != "'":
            self._heredoc_escape = True
            return ""
        if self._heredoc_quote:
            if char == self._heredoc_quote:
                self._heredoc_quote = ""
                return ""
            self._append_heredoc_tag(char)
            return ""
        if char in " \t":
            if self._heredoc_tag or self._heredoc_queue:
                self._finish_heredoc_word()
                self._heredoc = "rest"
            return ""
        if char == "-" and not self._heredoc_tag:
            self._heredoc_strip = True
            return ""
        if char in "\"'":
            self._heredoc_quote = char
            return ""
        if char in "\r\n":
            self._begin_heredoc_body()
            return ""
        self._append_heredoc_tag(char)
        return ""

    def _step_heredoc_rest(self, char: str) -> str:
        if self._lt:
            self._lt = False
            if char == "<":
                self._heredoc = "tag"
                self._heredoc_strip = False
                return ""
            return ""
        if char == "<":
            self._lt = True
            return ""
        if char in "\r\n":
            self._begin_heredoc_body()
            return ""
        return ""

    def _step_heredoc_body(self, char: str) -> str:
        if char in "\r\n":
            line = self._heredoc_line.lstrip("\t") if self._heredoc_body_strip else self._heredoc_line
            if line == self._heredoc_tag:
                if self._heredoc_queue:
                    tag, strip = self._heredoc_queue.pop(0)
                    self._activate_heredoc(tag, strip)
                else:
                    self._heredoc = ""
                    self._heredoc_tag = ""
                    self._heredoc_line = ""
                    self._heredoc_quote = ""
                    self._heredoc_strip = False
                    self._heredoc_body_strip = False
            else:
                self._heredoc_line = ""
            return ""
        if len(self._heredoc_line) < _MAX_HEREDOC_LINE:
            self._heredoc_line += char
        return ""

    def _step_unquoted_value(self, char: str) -> str:
        if self._heredoc == "tag":
            return self._step_heredoc_tag(char)
        if self._heredoc == "rest":
            return self._step_heredoc_rest(char)
        if self._heredoc == "body":
            return self._step_heredoc_body(char)
        if self._escape:
            self._escape = False
            self._dollar = False
            self._lt = False
            self._gt = False
            self._arith_maybe = False
            if self._case_class:
                self._step_case_class(char)
            elif self._subst_stack:
                self._cmd_qualified = True
            return ""
        if char == "\\":
            self._escape = True
            self._dollar = False
            self._lt = False
            self._gt = False
            self._arith_maybe = False
            return ""
        if self._shell_comment:
            if char in "\r\n":
                self._shell_comment = False
                if self._subst_stack:
                    self._flush_subst_word()
                    self._cmd_pos = True
                    self._cmd_qualified = False
            return ""
        dollar_consumed = False
        if self._dollar:
            self._dollar = False
            dollar_consumed = True
            self._arith_maybe = False
            if char in "({":
                if char == "(":
                    self._push_subst(")", "cmd")
                    self._arith_maybe = True
                else:
                    self._push_subst("}", "param")
                return ""
        elif self._lt:
            self._lt = False
            self._arith_maybe = False
            if char == "(":
                self._push_subst(")", "cmd")
                return ""
            if char == "<":
                self._heredoc = "tag"
                self._heredoc_tag = ""
                self._heredoc_line = ""
                self._heredoc_quote = ""
                self._heredoc_strip = False
                self._heredoc_escape = False
                return ""
            self._cmd_pos = False
            self._cmd_qualified = False
        elif self._gt:
            self._gt = False
            self._arith_maybe = False
            if char == "(":
                self._push_subst(")", "cmd")
                return ""
            self._cmd_pos = False
            self._cmd_qualified = False
        elif char == "$" and self._value_kind == "shell":
            self._arith_maybe = False
            self._dollar = True
            return ""
        elif char == "<" and self._value_kind == "shell":
            self._arith_maybe = False
            if self._subst_stack:
                self._flush_subst_word()
            self._lt = True
            return ""
        elif char == ">" and self._value_kind == "shell":
            self._arith_maybe = False
            if self._subst_stack:
                self._flush_subst_word()
            self._gt = True
            return ""
        elif self._arith_maybe and char != "(":
            self._arith_maybe = False
        if char == "#" and self._subst_stack and self._value_kind == "shell" and not dollar_consumed:
            if self._subst_word or self._cmd_qualified:
                self._cmd_qualified = True
                return ""
            self._shell_comment = True
            return ""
        if char == "`" and self._value_kind == "shell":
            self._flush_subst_word()
            if self._subst_stack and self._subst_closer() == "`":
                self._pop_subst()
            else:
                self._push_subst("`", "cmd")
            return ""
        if (
            char == "("
            and self._value_kind == "shell"
            and (self._subst_stack or self._allow_compound)
        ):
            self._flush_subst_word()
            if self._arith_maybe:
                self._arith_maybe = False
                if self._subst_stack:
                    closer, _kind, saved = self._subst_stack[-1]
                    self._subst_stack[-1] = (closer, "arith", saved)
                    self._cmd_pos = False
                self._push_subst(")", "arith")
            elif self._subst_kind() == "arith":
                self._push_subst(")", "arith")
            else:
                self._push_subst(")", "cmd")
                self._note_subst_char(char)
            self._allow_compound = False
            return ""
        if char in "\"'":
            if self._subst_stack:
                if self._subst_word:
                    self._cmd_qualified = True
                self._state = "quoted_value"
                self._value_quote = char
                return ""
            if self._quote and char == self._quote:
                return self._end_value(char)
            self._state = "quoted_value"
            self._value_quote = char
            return ""
        if self._subst_stack:
            if self._case_class:
                self._step_case_class(char)
                return ""
            if (
                self._case_arm == "pattern"
                and char == "["
                and not self._subst_word
                and not self._cmd_qualified
            ):
                self._enter_case_class()
                return ""
            if char not in _SHELL_WORD_BREAK:
                self._extend_shell_word(char)
                return ""
            self._flush_subst_word()
            if char == self._subst_closer():
                if char == ")" and self._case_depth and len(self._subst_stack) == 1:
                    if self._case_arm == "pattern":
                        self._case_arm = "body"
                        self._case_class = False
                        self._case_class_first = False
                        self._case_posix = ""
                    self._cmd_pos = True
                    self._cmd_qualified = False
                    self._note_subst_char(char)
                    return ""
                self._pop_subst()
                self._note_subst_char(char)
                return ""
            self._note_subst_char(char)
            return ""
        if self._quote and not self._subst_stack:
            if char == self._quote:
                return self._end_value(char)
            return ""
        if self._subst_opaque:
            return ""
        if self._value_kind == "json":
            if char.isspace() or char in ",;}]":
                return self._end_value(char)
            return ""
        self._allow_compound = False
        if char.isspace() or char in ";|&\r\n":
            return self._end_value(char)
        return ""

    def _end_value(self, char: str) -> str:
        self._state = "normal"
        self._quote = ""
        self._value_kind = "shell"
        self._reset_shell_lex()
        self._json_key = False
        self._json_ctx = False
        self._wrap_quote = ""
        return char

    def _step_line_value(self, char: str) -> str:
        if self._escape:
            self._escape = False
            return ""
        if char == "\\":
            self._escape = True
            return ""
        if char in "\r\n":
            self._state = "normal"
            return char
        if char == self._quote:
            self._state = "unquoted_value"
            self._quote = ""
            return char
        return ""

    def _step_cap_candidate(self, char: str) -> str:
        if self._key_quote or self._quote:
            return self._step_cap_candidate_quoted(char)
        return self._feed_cap_semantic(char, raw=char)

    def _step_cap_candidate_quoted(self, char: str) -> str:
        if self._unicode_hex is not None:
            self._cap_raw += char
            self._unicode_hex += char
            if len(self._unicode_hex) == 4:
                try:
                    decoded = chr(int(self._unicode_hex, 16))
                except ValueError:
                    decoded = ""
                self._unicode_hex = None
                if decoded:
                    return self._feed_cap_semantic(decoded, raw="")
            return ""
        if self._escape:
            self._escape = False
            if char == "u":
                self._unicode_hex = ""
                self._cap_raw += f"\\{char}"
                return ""
            self._cap_raw += f"\\{char}"
            return self._feed_cap_semantic(_SIMPLE_ESCAPES.get(char, char), raw="")
        if char == "\\":
            self._escape = True
            return ""
        return self._feed_cap_semantic(char, raw=char)

    def _feed_cap_semantic(self, decoded: str, *, raw: str) -> str:
        if decoded.isalnum() or decoded in "._-":
            if raw:
                self._cap_raw += raw
            self._cap_held += decoded
            if decoded == ".":
                self._cap_seen_dot = True
            elif self._cap_seen_dot and decoded.isalnum():
                self._cap_held = ""
                self._cap_raw = ""
                self._cap_seen_dot = False
                self._state = "cap"
                return _REDACTED
            if len(self._cap_held) >= _MAX_CAP_HOLD or len(self._cap_raw) >= _MAX_CAP_HOLD * 6:
                outgoing = self._cap_raw or self._cap_held
                self._cap_held = ""
                self._cap_raw = ""
                self._cap_seen_dot = False
                self._state = "normal"
                return outgoing
            return ""
        outgoing = self._cap_raw or self._cap_held
        closer = self._key_quote or self._quote
        self._cap_held = ""
        self._cap_raw = ""
        self._cap_seen_dot = False
        decoded_char = raw or decoded
        if closer and decoded_char == closer:
            self._reset_ident()
            return outgoing + decoded_char
        if closer:
            self._state = "quoted_key"
            return outgoing + self._step_quoted_key(decoded_char)
        self._reset_ident()
        return outgoing + self._step(decoded_char)

    def _step_cap(self, char: str) -> str:
        if char.isalnum() or char in "._-":
            return ""
        quote = self._key_quote or self._quote
        if quote and char == quote:
            self._reset_ident()
            return char
        if quote:
            self._state = "quoted_key"
            return self._step_quoted_key(char)
        self._reset_ident()
        return self._step(char)

    def _open_value(self, separator: str, *, outer_quote: str | None = None, kind: str = "shell") -> str:
        rest = "" if self._key_quote else self._component[self._emitted :]
        pending = kind == "json"
        emitted = f"{rest}{separator}"
        if not pending:
            emitted += _REDACTED
        auth = self._auth_key
        wrap = self._wrap_quote if outer_quote is None else outer_quote
        if kind != "shell":
            wrap = ""
        self._reset_ident()
        self._quote = wrap
        self._auth = auth
        self._value_kind = kind
        self._pending_redact = pending
        self._reset_shell_lex()
        self._allow_compound = kind == "shell"
        self._state = "value_start"
        return emitted

    def _reset_ident(self) -> None:
        self._state = "normal"
        self._start_component()
        self._sensitive = False
        self._prev_was_api = False
        self._bare_credential = False
        self._auth_key = False
        self._key_quote = ""
        self._wrap_quote = ""
        self._inner_quote = ""
        self._quote = ""
        self._quote_dash = False
        self._cli = False
        self._auth = False
        self._json_key = False
        self._json_ctx = False
        self._value_kind = "shell"
        self._reset_shell_lex()
        self._pending_redact = False
        self._unicode_hex = None
        self._escape = False

    def _flush_state(self) -> str:
        if self._pending_redact:
            self._pending_redact = False
            return _REDACTED
        if self._dash:
            self._dash = False
            return "-"
        if self._escape:
            self._escape = False
            if self._state == "quoted_key":
                self._reset_ident()
                return "\\"
            held = self._complete_component() if self._state == "ident" else ""
            return f"{held}\\"
        if self._state == "cap_candidate":
            outgoing = self._cap_raw or self._cap_held
            self._cap_held = ""
            self._cap_raw = ""
            self._cap_seen_dot = False
            self._reset_ident()
            return outgoing
        if self._state == "ident":
            emitted = self._complete_component()
            self._reset_ident()
            return emitted
        if self._state == "quoted_key":
            self._apply_component_sensitivity()
            self._start_component()
            self._reset_ident()
            return ""
        if self._state == "after_ident":
            emitted = self._component[self._emitted :]
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
