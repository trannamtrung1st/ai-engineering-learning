"""Persistence-layer errors (proposal §18)."""

from __future__ import annotations

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

    def __init__(self, run_id: str, detail: str = "") -> None:
        self.run_id = run_id
        message = f"run not found: {run_id}"
        if detail:
            message = f"{message} ({detail})"
        super().__init__(message)


__all__ = ["PersistenceError", "RunNotFoundError", "StoreRevisionConflictError"]
