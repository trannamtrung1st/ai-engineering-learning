"""Resolve the Cursor model for todos sessions."""

from __future__ import annotations

import os

from todos_tool.models import DEFAULT_CURSOR_MODEL


def resolve_model(
    explicit: str | None = None,
    *,
    manifest_model: str | None = None,
    workspace_loaded: bool = False,
) -> str | None:
    """Resolve the model for a Cursor session.

    Precedence: CLI ``--model`` → ``TODOS_TOOL_MODEL`` → manifest ``settings.model``
    → package default when the workspace is not loaded yet.

    When the workspace is loaded and ``settings.model`` is explicitly null, return
    ``None`` so Cursor uses its own default instead of Composer 2.5.
    """
    if explicit is not None and explicit.strip():
        return explicit.strip()
    env_model = os.environ.get("TODOS_TOOL_MODEL", "").strip()
    if env_model:
        return env_model
    if manifest_model is not None:
        return manifest_model
    if workspace_loaded:
        return None
    return DEFAULT_CURSOR_MODEL
