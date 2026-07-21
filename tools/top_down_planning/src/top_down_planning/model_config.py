"""Resolve the Cursor model for planning sessions."""

from __future__ import annotations

import os

from top_down_planning.models import DEFAULT_CURSOR_MODEL


def resolve_model(explicit: str | None = None) -> str:
    """CLI ``--model`` overrides ``PLANNING_TOOL_MODEL``, then the package default."""
    if explicit is not None and explicit.strip():
        return explicit.strip()
    env_model = os.environ.get("PLANNING_TOOL_MODEL", "").strip()
    if env_model:
        return env_model
    return DEFAULT_CURSOR_MODEL
