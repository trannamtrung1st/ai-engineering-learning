"""Configuration resolution errors (proposal §14)."""

from __future__ import annotations


class ConfigError(Exception):
    """Raised when configuration loading or override application fails."""

    def __init__(self, message: str, *, path: str | None = None) -> None:
        self.path = path
        super().__init__(message)
