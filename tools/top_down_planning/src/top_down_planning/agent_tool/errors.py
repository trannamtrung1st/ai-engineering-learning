"""Agent tool response errors."""

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

    def __init__(
        self,
        message: str,
        *,
        action: str | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(message, action=action)
        self.hint = hint

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        if self.hint:
            payload["hint"] = self.hint
        return payload


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

    def __init__(self, message: str, *, action: str | None = None, hint: str | None = None) -> None:
        super().__init__(message, action=action)
        self.hint = hint

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        if self.hint:
            payload["hint"] = self.hint
        return payload


class ProductionEvidenceIncompleteError(RequestError):
    code = "production_evidence_incomplete"

    def __init__(
        self,
        message: str,
        *,
        unauthorized_paths: tuple[str, ...],
        production_revision: int,
        changed_snapshot_paths: int | None = None,
        authorized_changed_paths: int | None = None,
        action: str | None = None,
    ) -> None:
        super().__init__(
            message,
            action=action
            or (
                "Include every changed snapshot-bound workspace path in outputs and retry "
                f"with production_revision={production_revision}."
            ),
        )
        self.unauthorized_paths = unauthorized_paths
        self.production_revision = production_revision
        self.retryable = True
        self.changed_snapshot_paths = changed_snapshot_paths
        self.authorized_changed_paths = authorized_changed_paths

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload["unauthorized_paths"] = list(self.unauthorized_paths)
        payload["production_revision"] = self.production_revision
        payload["retryable"] = self.retryable
        if self.changed_snapshot_paths is not None:
            payload["changed_snapshot_paths"] = self.changed_snapshot_paths
        if self.authorized_changed_paths is not None:
            payload["authorized_changed_paths"] = self.authorized_changed_paths
        if self.changed_snapshot_paths is not None:
            payload["unauthorized_changed_paths"] = list(self.unauthorized_paths)
        return payload


class ProductionContextMutationError(RequestError):
    code = "production_context_mutation_unauthorized"

    def __init__(
        self,
        message: str,
        *,
        context_mutation_paths: tuple[str, ...],
        production_revision: int,
        changed_snapshot_paths: int | None = None,
        authorized_changed_paths: int | None = None,
        unauthorized_changed_paths: tuple[str, ...] | None = None,
        evidence_gap_paths: tuple[str, ...] | None = None,
        action: str | None = None,
    ) -> None:
        super().__init__(
            message,
            action=action
            or (
                "Revert or reconcile unauthorized snapshot-bound context changes. "
                "Skills, file or inline guidance, and similar binding keys cannot "
                f"be authorized through production outputs (production_revision="
                f"{production_revision})."
            ),
        )
        self.context_mutation_paths = context_mutation_paths
        self.production_revision = production_revision
        self.retryable = False
        self.changed_snapshot_paths = changed_snapshot_paths
        self.authorized_changed_paths = authorized_changed_paths
        self.unauthorized_changed_paths = (
            unauthorized_changed_paths or context_mutation_paths
        )
        self.evidence_gap_paths = evidence_gap_paths or ()

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload["context_mutation_paths"] = list(self.context_mutation_paths)
        payload["production_revision"] = self.production_revision
        payload["retryable"] = self.retryable
        if self.changed_snapshot_paths is not None:
            payload["changed_snapshot_paths"] = self.changed_snapshot_paths
        if self.authorized_changed_paths is not None:
            payload["authorized_changed_paths"] = self.authorized_changed_paths
        payload["unauthorized_changed_paths"] = list(self.unauthorized_changed_paths)
        if self.evidence_gap_paths:
            payload["evidence_gap_paths"] = list(self.evidence_gap_paths)
        return payload
