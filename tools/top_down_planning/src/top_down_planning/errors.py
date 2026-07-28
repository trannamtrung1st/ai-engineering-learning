"""Domain errors for the top-down planning tool."""


class PlanningToolError(Exception):
    """Base error for the planning tool."""


class ValidationError(PlanningToolError):
    """Planning state or operation validation failed."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        message = "Validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        super().__init__(message)


class ResponseParseError(PlanningToolError):
    """Agent response missing or malformed."""


class CursorEnvironmentError(PlanningToolError):
    """Cursor CLI missing, unauthenticated, or otherwise unusable."""


class CursorSessionError(PlanningToolError):
    """A Cursor session failed recoverably (timeout, crash, stream errors)."""

    def __init__(self, message: str, *, recoverable: bool = True) -> None:
        self.recoverable = recoverable
        super().__init__(message)


class UserInterrupted(PlanningToolError):
    """Operator cancelled the tool; the Cursor agent was terminated."""

    def __init__(self, message: str, *, agent_pid: int | None = None) -> None:
        self.agent_pid = agent_pid
        super().__init__(message)


class PersistenceError(PlanningToolError):
    """Run state could not be loaded or written."""


class ResumeError(PlanningToolError):
    """Resume rejected due to incompatible or missing state."""
