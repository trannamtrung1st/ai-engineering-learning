"""Structured request loading for agent CLI commands."""

from __future__ import annotations

from typing import Any

from core_tools.cli import load_structured_request as _load_structured_request

from top_down_planning.agent_tool.errors import RequestError


def load_structured_request(
    *,
    request_path: str | None = None,
    stdin: Any | None = None,
) -> dict[str, Any]:
    """Load a JSON or YAML request object from a file or stdin."""

    return _load_structured_request(
        request_path=request_path,
        stdin=stdin,
        error_type=RequestError,
    )
