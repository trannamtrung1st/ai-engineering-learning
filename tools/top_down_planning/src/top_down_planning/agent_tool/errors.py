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
    ) -> None:
        super().__init__(
            message,
            action="Call `tdp agent plan snapshot` and retry with the current revision.",
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


class RoleDeniedError(AgentToolError):
    code = "role_denied"

    def __init__(self, role: str) -> None:
        super().__init__(
            f"role {role!r} is not allowed to mutate the plan",
            action="Only the planner role may apply plan mutations.",
        )
        self.role = role

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload["role"] = self.role
        return payload


class OperationError(AgentToolError):
    code = "operation_error"
