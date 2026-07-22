"""Stream-JSON parsing, rendering helpers, and shell-command evidence extraction."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

EventCategory = Literal[
    "assistant",
    "thinking",
    "tool:start",
    "tool:output",
    "tool:end",
    "status",
    "warning",
    "error",
    "unknown",
]

_SILENT_TYPES = frozenset({"user", "interaction_query"})

_TOOL_LABELS = {
    "readToolCall": "read",
    "writeToolCall": "write",
    "editToolCall": "edit",
    "deleteToolCall": "delete",
    "grepToolCall": "grep",
    "globToolCall": "glob",
    "lsToolCall": "ls",
    "semanticSearchToolCall": "search",
    "todoToolCall": "todo",
}


@dataclass
class NormalizedEvent:
    category: EventCategory
    text: str
    raw: dict[str, Any]


@dataclass
class ShellCommandEvidence:
    command: str
    completed: bool
    exit_code: int | None = None


class NdjsonStreamParser:
    """Decode UTF-8 incrementally and parse complete NDJSON lines."""

    def __init__(self, *, parse_error_threshold: int = 20) -> None:
        self._byte_buffer = bytearray()
        self._text_buffer = ""
        self.parse_error_threshold = parse_error_threshold
        self.parse_errors = 0
        self.malformed: list[str] = []
        self.events: list[dict[str, Any]] = []

    def feed(self, data: bytes) -> list[dict[str, Any]]:
        if not data:
            return []
        self._byte_buffer.extend(data)
        try:
            text = self._byte_buffer.decode("utf-8")
            self._byte_buffer.clear()
        except UnicodeDecodeError as exc:
            if exc.start > 0:
                text = self._byte_buffer[: exc.start].decode("utf-8")
                del self._byte_buffer[: exc.start]
            else:
                return []
        self._text_buffer += text
        return self._consume_lines()

    def finish(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        if self._byte_buffer:
            try:
                self._text_buffer += self._byte_buffer.decode("utf-8")
            except UnicodeDecodeError:
                self._record_malformed(self._byte_buffer.decode("utf-8", errors="replace"))
            self._byte_buffer.clear()
        if self._text_buffer.strip():
            events.extend(self._parse_line(self._text_buffer))
            self._text_buffer = ""
        return events

    def threshold_exceeded(self) -> bool:
        return self.parse_errors >= self.parse_error_threshold

    def _consume_lines(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        while True:
            idx = self._text_buffer.find("\n")
            if idx < 0:
                break
            line = self._text_buffer[:idx]
            self._text_buffer = self._text_buffer[idx + 1 :]
            events.extend(self._parse_line(line))
        return events

    def _parse_line(self, line: str) -> list[dict[str, Any]]:
        stripped = line.strip()
        if not stripped:
            return []
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            self._record_malformed(stripped)
            return []
        if not isinstance(obj, dict):
            self._record_malformed(stripped)
            return []
        self.events.append(obj)
        return [obj]

    def _record_malformed(self, line: str) -> None:
        self.parse_errors += 1
        self.malformed.append(line[:500])


def json_preview(event: dict[str, Any], limit: int = 200) -> str:
    text = json.dumps(event, default=str)
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def normalize_text_delta(prev: str, text: str) -> tuple[str, str]:
    if not text:
        return prev, ""
    if prev and text.startswith(prev):
        return text, text[len(prev) :]
    return prev + text, text


normalize_assistant_delta = normalize_text_delta


def _shorten(value: str, limit: int = 80) -> str:
    value = value.replace("\n", " ").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def _first_str(args: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = args.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, str) and first:
                return first
    return ""


def extract_shell_command(event: dict[str, Any]) -> str | None:
    """Return the shell command from a tool_call event, if present."""
    if event.get("type") != "tool_call":
        return None
    tool_call = event.get("tool_call") or {}
    if not isinstance(tool_call, dict) or "shellToolCall" not in tool_call:
        return None
    shell = tool_call["shellToolCall"] or {}
    args = shell.get("args") or {}
    result = shell.get("result") or {}
    success = result.get("success") or {}
    cmd = args.get("command") or success.get("command")
    if isinstance(cmd, str) and cmd.strip():
        return cmd.strip()
    return None


def _tool_label(event: dict[str, Any]) -> str:
    tool_call = event.get("tool_call") or {}
    if not isinstance(tool_call, dict):
        return "tool"

    if "shellToolCall" in tool_call:
        shell = tool_call["shellToolCall"] or {}
        args = shell.get("args") or {}
        result = shell.get("result") or {}
        success = result.get("success") or {}
        cmd = args.get("command") or success.get("command") or "shell"
        return f"shell: {_shorten(str(cmd), 100)}"

    for key, label in _TOOL_LABELS.items():
        if key not in tool_call:
            continue
        payload = tool_call[key] or {}
        args = payload.get("args") or {}
        if not isinstance(args, dict):
            args = {}
        detail = _first_str(
            args,
            "path",
            "targetDirectory",
            "globPattern",
            "glob_pattern",
            "pattern",
            "query",
            "searchTerm",
            "command",
        )
        if detail:
            return f"{label} {_shorten(detail)}"
        return label

    function = tool_call.get("function")
    if isinstance(function, dict):
        return str(function.get("name") or "tool")
    keys = list(tool_call.keys())
    if keys:
        return keys[0].replace("ToolCall", "")
    return "tool"


def _assistant_text(event: dict[str, Any]) -> str:
    message = event.get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    if isinstance(event.get("text"), str):
        return event["text"]
    return ""


def _thinking_text(event: dict[str, Any]) -> str:
    text = event.get("text")
    if isinstance(text, str) and text:
        return text
    return _assistant_text(event)


class EventNormalizer:
    """Stateful normalizer that emits assistant/thinking deltas when possible."""

    def __init__(self) -> None:
        self._turn_text = ""
        self._thinking_text = ""
        self._shell_commands: list[ShellCommandEvidence] = []

    def normalize(self, event: dict[str, Any]) -> list[NormalizedEvent]:
        self._track_shell_evidence(event)
        etype = event.get("type")
        if etype in _SILENT_TYPES:
            return []
        if etype == "assistant":
            return self._normalize_assistant(event)
        if etype == "thinking":
            return self._normalize_thinking(event)
        if etype == "tool_call":
            return self._normalize_tool(event)
        if etype == "system":
            subtype = event.get("subtype", "")
            model = event.get("model", "")
            session = event.get("session_id", "")
            text = f"session={session} model={model} subtype={subtype}".strip()
            return [NormalizedEvent("status", text, event)]
        if etype == "result":
            subtype = event.get("subtype", "")
            err = event.get("is_error")
            duration = event.get("duration_ms")
            text = f"result subtype={subtype} duration={duration}ms error={err}"
            category: EventCategory = "error" if err else "status"
            return [NormalizedEvent(category, text, event)]
        if etype == "error":
            text = str(event.get("message") or event.get("text") or event)
            return [NormalizedEvent("error", text, event)]
        if etype == "warning":
            text = str(event.get("message") or event.get("text") or event)
            return [NormalizedEvent("warning", text, event)]
        return [
            NormalizedEvent(
                "unknown",
                f"{etype or 'event'}: {json_preview(event)}",
                event,
            )
        ]

    def get_shell_commands(self) -> list[ShellCommandEvidence]:
        return list(self._shell_commands)

    def _track_shell_evidence(self, event: dict[str, Any]) -> None:
        if event.get("type") != "tool_call":
            return
        cmd = extract_shell_command(event)
        if not cmd:
            return
        subtype = event.get("subtype")
        if subtype == "started":
            self._shell_commands.append(ShellCommandEvidence(command=cmd, completed=False))
            return
        if subtype == "completed":
            tool_call = event.get("tool_call") or {}
            shell = (tool_call.get("shellToolCall") or {}) if isinstance(tool_call, dict) else {}
            result = shell.get("result") or {}
            success = result.get("success") or {}
            exit_code = success.get("exitCode")
            if exit_code is None:
                exit_code = success.get("exit_code")
            for entry in reversed(self._shell_commands):
                if entry.command == cmd and not entry.completed:
                    entry.completed = True
                    entry.exit_code = exit_code if isinstance(exit_code, int) else None
                    return
            self._shell_commands.append(
                ShellCommandEvidence(
                    command=cmd,
                    completed=True,
                    exit_code=exit_code if isinstance(exit_code, int) else None,
                )
            )

    def _normalize_assistant(self, event: dict[str, Any]) -> list[NormalizedEvent]:
        if event.get("model_call_id") is not None:
            return []
        if event.get("timestamp_ms") is None and "message" not in event:
            self._turn_text = ""
            return []
        if event.get("timestamp_ms") is None and self._turn_text:
            text = _assistant_text(event)
            if text and (
                text == self._turn_text
                or self._turn_text.startswith(text)
                or text.startswith(self._turn_text)
            ):
                return []
        text = _assistant_text(event)
        if not text:
            return []
        self._thinking_text = ""
        self._turn_text, delta = normalize_text_delta(self._turn_text, text)
        if not delta:
            return []
        return [NormalizedEvent("assistant", delta, event)]

    def _normalize_thinking(self, event: dict[str, Any]) -> list[NormalizedEvent]:
        text = _thinking_text(event)
        if not text:
            return []
        self._thinking_text, delta = normalize_text_delta(self._thinking_text, text)
        if not delta:
            return []
        return [NormalizedEvent("thinking", delta, event)]

    def _normalize_tool(self, event: dict[str, Any]) -> list[NormalizedEvent]:
        self._turn_text = ""
        self._thinking_text = ""
        subtype = event.get("subtype")
        label = _tool_label(event)
        if subtype == "started":
            return [NormalizedEvent("tool:start", label, event)]
        if subtype == "completed":
            return [NormalizedEvent("tool:end", label, event)]
        if subtype in ("output", "delta"):
            text = str(event.get("output") or event.get("text") or label)
            return [NormalizedEvent("tool:output", _shorten(text, 160), event)]
        return [NormalizedEvent("unknown", f"tool_call:{subtype} {label}", event)]
