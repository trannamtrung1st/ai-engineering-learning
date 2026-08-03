"""Domain-level errors for plan mutations (proposal §8.5)."""

from __future__ import annotations


class DomainError(Exception):
    """Base class for deterministic domain failures."""


class RevisionConflictError(DomainError):
    """base_revision does not match the current plan revision."""

    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(
            f"revision conflict: expected base_revision {expected}, current revision is {actual}"
        )
        self.expected = expected
        self.actual = actual


class UnknownItemError(DomainError):
    """Referenced plan item id does not exist."""

    def __init__(self, item_id: str, *, hint: str | None = None) -> None:
        super().__init__(f"unknown item id: {item_id}")
        self.item_id = item_id
        self.hint = hint


class InvalidMutationError(DomainError):
    """Mutation would corrupt structural integrity."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class DependencyCycleError(DomainError):
    """Dependency graph would contain a cycle."""

    def __init__(self, path: list[str]) -> None:
        super().__init__(f"dependency cycle: {' -> '.join(path)}")
        self.path = path


class UnsupportedPlanSchemaVersionError(DomainError):
    """Persisted plan.json uses a corrupt or unsupported schema_version."""

    code = "unsupported_plan_schema"

    def __init__(self, message: str) -> None:
        super().__init__(message)
