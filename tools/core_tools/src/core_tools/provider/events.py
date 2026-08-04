"""Normalized provider event types (proposal §16)."""

from __future__ import annotations

import json
from typing import Any, Literal

ProviderEventType = Literal[
    "system",
    "user",
    "assistant",
    "thinking",
    "tool_call",
    "error",
    "done",
    "retry",
]

_ASSISTANT_TYPES = frozenset({"assistant"})
_THINKING_TYPES = frozenset({"thinking"})
_DONE_TYPES = frozenset({"result"})
_ERROR_TYPES = frozenset({"error"})

_TOOL_LABELS: dict[str, str] = {
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

_TOOL_DETAIL_KEYS = (
    "path",
    "targetDirectory",
    "globPattern",
    "glob_pattern",
    "pattern",
    "query",
    "searchTerm",
    "command",
)


def _format_protocol_instructions(protocol: Any) -> str | None:
    if protocol is None:
        return None
    if not isinstance(protocol, str):
        raise TypeError("protocol_instructions must be a Markdown string")
    stripped = protocol.strip()
    return stripped or None


def _format_advisory_guidance(payload: dict[str, Any]) -> str | None:
    """Render agent_context.guidance as an advisory section (not protocol)."""

    agent_context = payload.get("agent_context")
    if not isinstance(agent_context, dict):
        return None
    guidance = agent_context.get("guidance")
    if not isinstance(guidance, list):
        return None
    lines = [f"- {str(item).strip()}" for item in guidance if str(item).strip()]
    return "\n".join(lines) if lines else None


def _resolve_prompt_role(payload: dict[str, Any], *, role: str | None = None) -> str | None:
    if role is not None and str(role).strip():
        return str(role).strip()
    agent_context = payload.get("agent_context")
    if isinstance(agent_context, dict):
        candidate = agent_context.get("role")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def format_provider_payload_prompt(
    payload: dict[str, Any],
    *,
    role: str | None = None,
    body_label: str,
) -> str:
    """Serialize a provider payload with optional role and protocol sections."""

    parts: list[str] = []
    resolved_role = _resolve_prompt_role(payload, role=role)
    if resolved_role:
        parts.append(f"Role: {resolved_role}")
    protocol = _format_protocol_instructions(payload.get("protocol_instructions"))
    if protocol:
        parts.append(f"\nProtocol:\n{protocol}")
    advisory = _format_advisory_guidance(payload)
    if advisory:
        parts.append(f"\nAdvisory role guidance:\n{advisory}")
    body = json.dumps(payload, indent=2, sort_keys=True)
    parts.append(f"\n{body_label}:\n{body}")
    return "\n".join(parts)


def format_manifest_prompt(role: str, manifest: dict[str, Any]) -> str:
    """Serialize a context manifest into a provider prompt."""

    return format_provider_payload_prompt(
        manifest,
        role=role,
        body_label="Context manifest",
    )


def format_request_prompt(request: dict[str, Any]) -> str:
    """Serialize a follow-up request into a provider prompt."""

    return format_provider_payload_prompt(request, body_label="Request")


def is_tool_call_start(event: dict[str, Any]) -> bool:
    """Return True when a normalized tool_call event begins a tool invocation."""

    return (
        str(event.get("type") or "") == "tool_call"
        and str(event.get("subtype") or "") == "started"
    )


def is_tool_call_end(event: dict[str, Any]) -> bool:
    """Return True when a normalized tool_call event completes a tool invocation."""

    return (
        str(event.get("type") or "") == "tool_call"
        and str(event.get("subtype") or "") == "completed"
    )


def format_tool_call_summary(event: dict[str, Any]) -> str:
    """Return a concise human-readable summary for a tool invocation."""

    request = event.get("request")
    tool = event.get("tool")
    if isinstance(request, dict) and isinstance(tool, str) and tool:
        return _format_structured_tool_summary(tool, request)

    raw = event.get("raw")
    if isinstance(raw, dict):
        summary = _format_cursor_tool_call_summary(raw)
        if summary:
            return summary

    if isinstance(tool, str) and tool:
        return tool
    return "tool"


def normalize_cursor_event(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Map a Cursor stream-json line to the minimum orchestrator event shape."""

    event_type = str(raw.get("type") or "")
    session_id = raw.get("session_id")
    normalized: dict[str, Any] = {
        "type": event_type,
        "session_id": session_id,
        "raw": raw,
    }

    if event_type == "system":
        normalized["subtype"] = raw.get("subtype")
        return normalized

    if event_type == "user":
        normalized["text"] = _extract_text(raw.get("message"))
        return normalized

    if event_type in _ASSISTANT_TYPES:
        normalized["text"] = _provider_event_text(raw) or ""
        return normalized

    if event_type in _THINKING_TYPES:
        text = _provider_event_text(raw)
        if not text:
            return None
        normalized["text"] = text
        return normalized

    if event_type in _DONE_TYPES:
        normalized["type"] = "done"
        normalized["subtype"] = raw.get("subtype")
        normalized["text"] = raw.get("result")
        normalized["is_error"] = bool(raw.get("is_error"))
        if raw.get("signal") is not None:
            normalized["signal"] = raw["signal"]
        return normalized

    if event_type in _ERROR_TYPES:
        normalized["type"] = "error"
        normalized["text"] = raw.get("message") or raw.get("result") or raw.get("text")
        return normalized

    if event_type == "done":
        normalized["subtype"] = raw.get("subtype")
        normalized["text"] = raw.get("text") or raw.get("result")
        normalized["is_error"] = bool(raw.get("is_error"))
        if raw.get("signal") is not None:
            normalized["signal"] = raw["signal"]
        return normalized

    if event_type == "tool_result":
        return None

    if event_type == "tool_call":
        _enrich_tool_event(normalized, raw)
        if str(normalized.get("subtype") or "") not in {"started", "completed"}:
            return None
        return normalized

    return None


def _enrich_tool_event(normalized: dict[str, Any], raw: dict[str, Any]) -> None:
    request = raw.get("request")
    if not isinstance(request, dict):
        request = None

    tool = raw.get("tool")
    if tool is None:
        tool = _cursor_tool_name(raw)
    if tool is not None:
        normalized["tool"] = str(tool)

    subtype = raw.get("subtype")
    if subtype is None and tool is not None and request is not None:
        subtype = "started"
    if subtype is not None:
        normalized["subtype"] = subtype

    if request is not None:
        normalized["request"] = request

    call_id = _resolve_call_id(raw)
    if call_id is not None:
        normalized["call_id"] = call_id

    normalized["summary"] = format_tool_call_summary(normalized)


def _resolve_call_id(raw: dict[str, Any]) -> str | None:
    for key in ("call_id", "tool_call_id"):
        call_id = _normalize_call_id(raw.get(key))
        if call_id is not None:
            return call_id
    tool_call = raw.get("tool_call")
    if isinstance(tool_call, dict):
        call_id = _normalize_call_id(tool_call.get("id"))
        if call_id is not None:
            return call_id
    return _normalize_call_id(raw.get("id"))


def _normalize_call_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for part in text.split():
        if part.startswith("call_"):
            return part
    first_line = text.splitlines()[0].strip()
    if first_line.startswith("call_"):
        return first_line
    return None


def _format_structured_tool_summary(tool: str, request: dict[str, Any]) -> str:
    parts = [tool]
    if "base_revision" in request:
        parts.append(f"@r{request['base_revision']}")
    operations = request.get("operations")
    if isinstance(operations, list) and operations:
        parts.append(f"{len(operations)} ops")
    if "loop_id" in request:
        parts.append(f"loop={request['loop_id']}")
    if "review_type" in request:
        parts.append(str(request["review_type"]))
    return " ".join(parts)


def _format_cursor_tool_call_summary(raw: dict[str, Any]) -> str | None:
    tool_call = raw.get("tool_call")
    if not isinstance(tool_call, dict):
        return None

    if "shellToolCall" in tool_call:
        shell = tool_call.get("shellToolCall") or {}
        args = shell.get("args") or {}
        result = shell.get("result") or {}
        success = result.get("success") or {}
        if not isinstance(args, dict):
            args = {}
        if not isinstance(success, dict):
            success = {}
        command = args.get("command") or success.get("command") or "shell"
        return f"shell: {str(command)}"

    for key, label in _TOOL_LABELS.items():
        if key not in tool_call:
            continue
        payload = tool_call.get(key) or {}
        args = payload.get("args") or {}
        if not isinstance(args, dict):
            args = {}
        detail = _first_str(args, *_TOOL_DETAIL_KEYS)
        if detail:
            return f"{label} {detail}"
        return label

    function = tool_call.get("function")
    if isinstance(function, dict):
        name = function.get("name")
        if isinstance(name, str) and name:
            return name

    keys = list(tool_call.keys())
    if keys:
        return keys[0].replace("ToolCall", "")
    return None


def _cursor_tool_name(raw: dict[str, Any]) -> str | None:
    tool_call = raw.get("tool_call")
    if not isinstance(tool_call, dict):
        return None
    if "shellToolCall" in tool_call:
        return "shell"
    for key, label in _TOOL_LABELS.items():
        if key in tool_call:
            return label
    function = tool_call.get("function")
    if isinstance(function, dict) and function.get("name"):
        return str(function["name"])
    keys = list(tool_call.keys())
    if keys:
        return keys[0].replace("ToolCall", "").lower()
    return None


def _first_str(mapping: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _provider_event_text(raw: dict[str, Any]) -> str | None:
    direct = raw.get("text")
    if isinstance(direct, str) and direct:
        return direct
    return _extract_text(raw.get("message"))


def _extract_text(message: Any) -> str | None:
    if isinstance(message, str):
        return message
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and block.get("text"):
            parts.append(str(block["text"]))
    if not parts:
        return None
    return "\n".join(parts)
