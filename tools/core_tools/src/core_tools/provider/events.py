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
    "tool_result",
    "error",
    "done",
    "retry",
]

_ASSISTANT_TYPES = frozenset({"assistant"})
_THINKING_TYPES = frozenset({"thinking"})
_DONE_TYPES = frozenset({"result"})
_ERROR_TYPES = frozenset({"error"})


def format_manifest_prompt(role: str, manifest: dict[str, Any]) -> str:
    """Serialize a context manifest into a provider prompt."""

    payload = json.dumps(manifest, indent=2, sort_keys=True)
    return f"Role: {role}\n\nContext manifest:\n{payload}"


def format_request_prompt(request: dict[str, Any]) -> str:
    """Serialize a follow-up request into a provider prompt."""

    return json.dumps(request, indent=2, sort_keys=True)


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
        return normalized

    if event_type in _ERROR_TYPES:
        normalized["type"] = "error"
        normalized["text"] = raw.get("message") or raw.get("result")
        return normalized

    if event_type in {"tool_call", "tool_result"}:
        normalized["text"] = _extract_text(raw.get("message")) or json.dumps(
            raw, sort_keys=True
        )
        _enrich_tool_event(normalized, raw)
        return normalized

    return None


def _enrich_tool_event(normalized: dict[str, Any], raw: dict[str, Any]) -> None:
    tool = raw.get("tool") or raw.get("tool_name") or raw.get("name")
    if tool is not None:
        normalized["tool"] = str(tool)

    call_id = (
        raw.get("call_id")
        or raw.get("tool_call_id")
        or raw.get("id")
        or _nested_call_id(raw)
    )
    if call_id is not None:
        normalized["call_id"] = str(call_id)

    request = raw.get("request") or raw.get("arguments") or raw.get("input")
    if isinstance(request, dict):
        normalized["request"] = request
    elif request is not None:
        normalized["request"] = {"value": request}

    if normalized.get("type") == "tool_result":
        normalized["ok"] = not bool(raw.get("is_error"))
        if raw.get("duration_ms") is not None:
            normalized["duration_ms"] = int(raw["duration_ms"])


def _nested_call_id(raw: dict[str, Any]) -> str | None:
    for key in ("tool_call", "call"):
        nested = raw.get(key)
        if isinstance(nested, dict) and nested.get("id"):
            return str(nested["id"])
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
