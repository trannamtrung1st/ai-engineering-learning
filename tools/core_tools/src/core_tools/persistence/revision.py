"""Optimistic revision helpers for file-backed stores."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core_tools.persistence.errors import PersistenceError


class StoreRevisionConflictError(PersistenceError):
    """Optimistic revision check failed."""

    def __init__(self, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"store revision conflict: expected {expected}, current revision is {actual}"
        )


class RunNotFoundError(PersistenceError):
    """Run directory or required artifact is missing."""

    def __init__(
        self,
        run_id: str,
        detail: str = "",
        *,
        runs_root: str | Path | None = None,
    ) -> None:
        self.run_id = run_id
        self.runs_root = Path(runs_root).resolve() if runs_root is not None else None
        message = f"run not found: {run_id}"
        if detail:
            message = f"{message} ({detail})"
        if self.runs_root is not None:
            message = f"{message} (runs root: {self.runs_root})"
        super().__init__(message)


def parse_revision_value(value: Any, label: str) -> int:
    """Return a non-negative integer revision; reject coercible non-integers."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise PersistenceError(f"{label} revision must be a non-negative integer")
    if value < 0:
        raise PersistenceError(f"{label} revision must be a non-negative integer")
    return value


def require_revision_field(payload: dict[str, Any], label: str) -> int:
    if "revision" not in payload:
        raise PersistenceError(f"{label} payload must include an explicit revision")
    return parse_revision_value(payload["revision"], label)


def assert_next_revision(expected_revision: int, next_revision: int) -> None:
    if next_revision != expected_revision + 1:
        raise StoreRevisionConflictError(expected_revision + 1, next_revision)
