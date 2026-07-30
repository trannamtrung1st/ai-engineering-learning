"""Strict identifier validation for run-store paths."""

from __future__ import annotations

import re

from core_tools.persistence import PersistenceError

_STORE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def validate_store_id(value: str, *, label: str = "id") -> str:
    """Validate a user- or agent-supplied store identifier."""

    if not isinstance(value, str):
        raise PersistenceError(f"{label} must be a string")
    stripped = value.strip()
    if not stripped:
        raise PersistenceError(f"{label} must not be empty")
    if stripped != value:
        raise PersistenceError(f"{label} must not contain leading or trailing whitespace")
    if "/" in stripped or "\\" in stripped or ".." in stripped:
        raise PersistenceError(f"{label} must not contain path separators or '..'")
    if any(ord(char) < 32 for char in stripped):
        raise PersistenceError(f"{label} must not contain control characters")
    if not _STORE_ID_PATTERN.fullmatch(stripped):
        raise PersistenceError(
            f"{label} must match [A-Za-z0-9][A-Za-z0-9._-]{{0,127}}"
        )
    return stripped
