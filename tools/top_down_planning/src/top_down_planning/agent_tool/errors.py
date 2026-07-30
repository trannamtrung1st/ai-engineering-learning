"""Agent tool response errors (proposal §8, §17.3)."""

from __future__ import annotations

from typing import Any


class AgentToolError(Exception):
    """Base class for agent tool failures."""

    code: str = "agent_tool_error"

    def __init__(self, message: str, *, action: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.action = action

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.action:
            payload["action"] = self.action
        return payload


class RequestError(AgentToolError):
    code = "request_error"


class RevisionConflictError(AgentToolError):
    code = "revision_conflict"

    def __init__(
        self,
        message: str,
        *,
        expected: int | None = None,
        actual: int | None = None,
        action: str | None = None,
    ) -> None:
        super().__init__(
            message,
            action=action
            or "Call `tdp agent plan snapshot` and retry with the current revision.",
        )
        self.expected = expected
        self.actual = actual

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        if self.expected is not None:
            payload["expected_revision"] = self.expected
        if self.actual is not None:
            payload["actual_revision"] = self.actual
        return payload


class CapabilityDeniedError(AgentToolError):
    code = "capability_denied"

    def __init__(
        self,
        message: str,
        *,
        operation: str | None = None,
        action: str | None = None,
    ) -> None:
        super().__init__(
            message,
            action=action
            or (
                "Mutating agent commands require a valid session capability token. "
                f"Ensure {__import__('top_down_planning.persistence.capabilities', fromlist=['CAPABILITY_ENV_VAR']).CAPABILITY_ENV_VAR} "
                "is exported to the provider subprocess."
            ),
        )
        self.operation = operation

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        if self.operation is not None:
            payload["operation"] = self.operation
        return payload


class OperationError(AgentToolError):
    code = "operation_error"
