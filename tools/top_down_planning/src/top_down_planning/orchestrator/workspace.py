"""Shared orchestrator helpers for run workspace resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def run_workspace(run: dict[str, Any], *, fallback: Path | None = None) -> Path:
    """Resolve the workspace directory for digest and provider operations."""

    workspace = run.get("workspace")
    if workspace is not None:
        return Path(str(workspace))
    if fallback is not None:
        return fallback
    raise ValueError("run workspace is not set and no fallback was provided")
