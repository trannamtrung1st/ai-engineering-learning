"""Extract structured planning operations from agent text.

Adapted from tools/implement_todos/src/todos_tool/reviewer.py.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from top_down_planning.errors import ResponseParseError
from top_down_planning.models import AgentResponse, RenderResponse


def _extract_fenced_json_objects(text: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    marker = "```"
    idx = 0
    while True:
        start = text.find(marker, idx)
        if start < 0:
            break
        content_start = start + len(marker)
        if text[content_start : content_start + 4].lower() == "json":
            content_start += 4
        newline = text.find("\n", content_start)
        if newline < 0:
            break
        end = text.find(marker, newline + 1)
        if end < 0:
            break
        block = text[newline + 1 : end].strip()
        try:
            obj = json.loads(block)
            if isinstance(obj, dict):
                candidates.append(obj)
        except json.JSONDecodeError:
            pass
        idx = end + len(marker)
    return candidates


def extract_json_objects(text: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    candidates.extend(_extract_fenced_json_objects(text))

    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(text):
        start = text.find("{", idx)
        if start < 0:
            break
        try:
            obj, end = decoder.raw_decode(text[start:])
            if isinstance(obj, dict) and (
                "operations" in obj or "artifacts" in obj
            ):
                candidates.append(obj)
            idx = start + end
        except json.JSONDecodeError:
            idx = start + 1
    return candidates


def parse_agent_response(text: str) -> AgentResponse:
    candidates = extract_json_objects(text)
    if not candidates:
        raise ResponseParseError("No JSON planning response found in session output")

    last_error: Exception | None = None
    for obj in reversed(candidates):
        if "operations" not in obj:
            continue
        try:
            return AgentResponse.model_validate(obj)
        except PydanticValidationError as exc:
            last_error = exc
            continue
    if last_error:
        raise ResponseParseError(
            f"Malformed planning response: {last_error}"
        ) from last_error
    raise ResponseParseError("No valid planning response JSON found")


def _extract_fenced_blocks(text: str) -> list[tuple[str | None, str]]:
    blocks: list[tuple[str | None, str]] = []
    marker = "```"
    idx = 0
    while True:
        start = text.find(marker, idx)
        if start < 0:
            break
        content_start = start + len(marker)
        lang_end = text.find("\n", content_start)
        if lang_end < 0:
            break
        lang_line = text[content_start:lang_end].strip().lower()
        lang = lang_line or None
        end = text.find(marker, lang_end + 1)
        if end < 0:
            break
        block = text[lang_end + 1 : end].strip()
        blocks.append((lang, block))
        idx = end + len(marker)
    return blocks


def parse_render_response(text: str) -> RenderResponse:
    """Extract structured output artifacts from a render-phase agent response."""
    candidates = extract_json_objects(text)
    render_candidates = [obj for obj in candidates if "artifacts" in obj]
    if not render_candidates:
        blocks = _extract_fenced_blocks(text)
        for lang, content in blocks:
            if lang in {None, "markdown", "md"} and content.strip():
                raise ResponseParseError(
                    "Render response must be JSON with an artifacts array, not raw Markdown"
                )
        raise ResponseParseError("No render response JSON with artifacts found")

    last_error: Exception | None = None
    for obj in reversed(render_candidates):
        try:
            return RenderResponse.model_validate(obj)
        except Exception as exc:
            last_error = exc
            continue
    if last_error:
        raise ResponseParseError(
            f"Malformed render response: {last_error}"
        ) from last_error
    raise ResponseParseError("No valid render response JSON found")
