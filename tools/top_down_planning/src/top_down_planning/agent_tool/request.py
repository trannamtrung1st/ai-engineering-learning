"""Structured request loading for agent CLI commands."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from top_down_planning.agent_tool.errors import RequestError
from top_down_planning.persistence.yaml_util import load_yaml


def load_structured_request(
    *,
    request_path: str | None = None,
    stdin: Any | None = None,
) -> dict[str, Any]:
    """Load a JSON or YAML request object from a file or stdin."""

    if request_path:
        path = Path(request_path)
        if not path.exists():
            raise RequestError(f"request file not found: {path}")
        text = path.read_text(encoding="utf-8")
    else:
        stream = stdin if stdin is not None else sys.stdin
        text = stream.read()

    text = text.strip()
    if not text:
        raise RequestError("request body is empty; provide JSON or YAML via stdin or --request")

    payload = _parse_structured_text(text)
    if not isinstance(payload, dict):
        raise RequestError("request body must be a JSON or YAML object")
    return payload


def _parse_structured_text(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    try:
        return load_yaml(text)
    except ValueError as exc:
        raise RequestError(f"failed to parse request body: {exc}") from exc
