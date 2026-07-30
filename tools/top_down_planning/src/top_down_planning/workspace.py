"""Shared run workspace resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def run_workspace(run: dict[str, Any]) -> Path:
    """Resolve the workspace directory for digest and provider operations."""

    workspace = run.get("workspace")
    if workspace is None or not str(workspace).strip():
        raise ValueError("run workspace is required")
    return Path(str(workspace)).resolve()
