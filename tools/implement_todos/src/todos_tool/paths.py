"""Path and identifier validation for todos workspaces."""

from __future__ import annotations

import re
from pathlib import Path

ITEM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def validate_item_id(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("id must not be empty")
    if not ITEM_ID_RE.match(stripped):
        raise ValueError(
            "id must be filename-safe (letters, digits, '.', '_', '-'; "
            "must start with a letter or digit)"
        )
    return stripped


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


def resolve_within(base: Path, relative: str) -> Path:
    """Resolve ``relative`` under ``base`` or raise ValueError."""
    rel = validate_relative_path(relative, label="path")
    base_resolved = base.resolve()
    resolved = (base_resolved / rel).resolve()
    if resolved != base_resolved and base_resolved not in resolved.parents:
        raise ValueError(f"path escapes configured todos directory: {relative}")
    return resolved
