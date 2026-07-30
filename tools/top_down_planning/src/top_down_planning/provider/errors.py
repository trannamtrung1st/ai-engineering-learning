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

class ProviderTurnError(ProviderError):
    """A provider turn failed during execution or parsing."""
