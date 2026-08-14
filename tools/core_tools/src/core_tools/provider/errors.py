"""Provider adapter errors."""

from __future__ import annotations


class ProviderError(Exception):
    """Base error for provider adapter failures."""

    def __init__(self, message: str, *, session_id: str | None = None) -> None:
        super().__init__(message)
        self.session_id = session_id


class ProviderBinaryNotFoundError(ProviderError):
    """Cursor CLI binary is missing from PATH or configured path."""


class ProviderSessionError(ProviderError):
    """Session does not exist or is in an invalid state."""


class ProviderSessionTerminationError(ProviderSessionError):
    """Provider could not verify death of a session-associated agent process."""

    def __init__(
        self,
        message: str,
        *,
        session_id: str | None = None,
        surviving_pids: tuple[int, ...] = (),
    ) -> None:
        super().__init__(message, session_id=session_id)
        self.surviving_pids = surviving_pids


class ProviderSessionNotFoundError(ProviderSessionError):
    """Provider reports a persisted remote session id no longer exists."""

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        session_id: str | None = None,
    ) -> None:
        super().__init__(message, session_id=session_id)
        self.provider = str(provider).strip() or "cursor"


class ProviderTurnError(ProviderError):
    """A provider turn failed during execution or parsing."""


class ProviderTurnStalledError(ProviderTurnError):
    """A provider turn produced no stream output within the configured idle window."""


class ProviderTurnCleanupError(ProviderTurnError):
    """A provider turn completed but janitor process-group cleanup was not verified."""
