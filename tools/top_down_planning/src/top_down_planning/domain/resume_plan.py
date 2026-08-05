"""Immutable resume plan model (proposal §9.1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ResumeStateTransition:
    from_status: str
    to_status: str
    prior_stop_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "from": self.from_status,
            "to": self.to_status,
        }
        if self.prior_stop_code is not None:
            payload["prior_stop_code"] = self.prior_stop_code
        return payload


@dataclass(frozen=True)
class ResumePlanValidation:
    contract_digest_valid: bool
    plan_binding_valid: bool
    approval_binding_valid: bool
    evidence_binding_valid: bool
    context_binding_valid: bool = True

    def to_dict(self) -> dict[str, bool]:
        return {
            "contract_digest_valid": self.contract_digest_valid,
            "plan_binding_valid": self.plan_binding_valid,
            "approval_binding_valid": self.approval_binding_valid,
            "evidence_binding_valid": self.evidence_binding_valid,
            "context_binding_valid": self.context_binding_valid,
        }


@dataclass(frozen=True)
class ResumePlan:
    run_id: str
    expected_run_revision: int
    state_transition: ResumeStateTransition | None
    config_changes: dict[str, dict[str, Any]]
    session_policy: dict[str, Any]
    validation: ResumePlanValidation
    effective_config: dict[str, Any] | None = None
    ignored_config_changes: dict[str, dict[str, Any]] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    allow_config_drift: bool = False
    contract_digest_may_change: bool = False
    context_spec_may_change: bool = False
    already_completed: bool = False
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "run_id": self.run_id,
            "expected_run_revision": self.expected_run_revision,
            "config_changes": dict(self.config_changes),
            "ignored_config_changes": dict(self.ignored_config_changes),
            "session_policy": dict(self.session_policy),
            "validation": self.validation.to_dict(),
            "warnings": list(self.warnings),
            "allow_config_drift": self.allow_config_drift,
            "contract_digest_may_change": self.contract_digest_may_change,
            "context_spec_may_change": self.context_spec_may_change,
            "already_completed": self.already_completed,
        }
        if self.state_transition is not None:
            payload["state_transition"] = self.state_transition.to_dict()
        if self.message is not None:
            payload["message"] = self.message
        return payload
