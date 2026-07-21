"""Domain errors for the todos tool."""


class TodosToolError(Exception):
    """Base error for the todos tool."""


class ValidationError(TodosToolError):
    """Workspace or schema validation failed."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        message = "Validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        super().__init__(message)


class SchedulingError(TodosToolError):
    """No eligible item or invalid scheduling state."""


class CursorEnvironmentError(TodosToolError):
    """Cursor CLI missing, unauthenticated, or otherwise unusable."""


class CursorSessionError(TodosToolError):
    """A Cursor session failed recoverably (timeout, crash, stream errors)."""

    def __init__(self, message: str, *, recoverable: bool = True) -> None:
        self.recoverable = recoverable
        super().__init__(message)


class UserInterrupted(TodosToolError):
    """Operator cancelled the tool; the Cursor agent was terminated."""

    def __init__(self, message: str, *, agent_pid: int | None = None) -> None:
        self.agent_pid = agent_pid
        super().__init__(message)


class ReviewError(TodosToolError):
    """Review decision missing, malformed, or contradictory."""


class GitError(TodosToolError):
    """Git operation failed or dirty-tree policy blocked the run."""


class PersistenceError(TodosToolError):
    """Run state could not be loaded or written."""


class RestructuringError(TodosToolError):
    """Proposed item restructuring was rejected."""
