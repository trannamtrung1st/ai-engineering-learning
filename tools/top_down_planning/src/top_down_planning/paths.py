"""Path validation helpers for the planning tool."""

from __future__ import annotations

from pathlib import Path


def validate_relative_path(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty relative path")
    normalized = value.replace("\\", "/").strip()
    if normalized.startswith("/"):
        raise ValueError(f"{label} must be relative, not absolute: {value}")
    parts = Path(normalized).parts
    if ".." in parts:
        raise ValueError(f"{label} must not contain '..': {value}")
    return normalized


def resolve_within_workspace(workspace: Path, relative: str) -> Path:
    rel = validate_relative_path(relative, label="path")
    base_resolved = workspace.resolve()
    resolved = (base_resolved / rel).resolve()
    if resolved != base_resolved and base_resolved not in resolved.parents:
        raise ValueError(f"path escapes workspace root: {relative}")
    return resolved
