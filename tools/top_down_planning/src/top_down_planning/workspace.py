"""Shared run workspace resolution and integrity validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class WorkspaceIntegrityError(ValueError):
    """Run workspace no longer matches the persisted binding."""


def run_workspace(run: dict[str, Any]) -> Path:
    """Resolve the workspace directory for digest and provider operations."""

    workspace = run.get("workspace")
    if workspace is None or not str(workspace).strip():
        raise ValueError("run workspace is required")
    return Path(str(workspace)).resolve()


def validate_run_workspace_integrity(
    run: dict[str, Any],
    *,
    workspace: Path | None = None,
) -> Path:
    """Ensure the live workspace matches the persisted run binding."""

    stored = run_workspace(run)
    resolved = (workspace or stored).resolve()
    if resolved != stored:
        raise WorkspaceIntegrityError(
            f"run workspace mismatch: stored {stored} vs current {resolved}"
        )
    if not resolved.is_dir():
        raise WorkspaceIntegrityError(f"run workspace does not exist: {resolved}")
    return resolved


__all__ = [
    "WorkspaceIntegrityError",
    "run_workspace",
    "validate_run_workspace_integrity",
]
