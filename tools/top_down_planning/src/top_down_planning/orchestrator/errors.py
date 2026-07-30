"""Orchestrator-level errors."""

from __future__ import annotations


class OrchestratorError(Exception):
    """Base orchestrator error."""

    def __init__(self, message: str, *, code: str = "orchestrator_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ProviderRunError(OrchestratorError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="provider_run_error")
