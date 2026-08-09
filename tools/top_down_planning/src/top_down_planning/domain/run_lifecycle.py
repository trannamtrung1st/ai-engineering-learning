"""Run lifecycle status, structured stop records, and invariants (proposal §4–§5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

RunStatus = Literal["running", "paused", "completed", "failed"]
StopCategory = Literal["operational", "invariant"]

PausedStopCode = Literal[
    "limit_exhausted",
    "review_incomplete",
    "provider_unavailable",
    "provider_turn_failed",
    "user_cancelled",
    "orchestrator_interrupted",
    "amendment_pending",
    "sub_tdps_awaiting_children",
    "sub_tdp_dependency_unmet",
    "sub_tdp_child_failed",
    "sub_tdp_child_paused",
    "prepared_plan_amendment_required",
]

FailedStopCode = Literal[
    "state_integrity_failure",
    "evidence_integrity_failure",
    "unsupported_phase_state",
    "orchestrator_invariant_failure",
    "session_recovery_exhausted",
    "sub_tdp_unit_permanently_failed",
]

StopCode = PausedStopCode | FailedStopCode

PAUSED_STOP_CODES: frozenset[str] = frozenset(
    {
        "limit_exhausted",
        "review_incomplete",
        "provider_unavailable",
        "provider_turn_failed",
        "user_cancelled",
        "orchestrator_interrupted",
        "amendment_pending",
        "sub_tdps_awaiting_children",
        "sub_tdp_dependency_unmet",
        "sub_tdp_child_failed",
        "sub_tdp_child_paused",
        "prepared_plan_amendment_required",
    }
)

FAILED_STOP_CODES: frozenset[str] = frozenset(
    {
        "state_integrity_failure",
        "evidence_integrity_failure",
        "unsupported_phase_state",
        "orchestrator_invariant_failure",
        "session_recovery_exhausted",
        "sub_tdp_unit_permanently_failed",
    }
)

RUN_STATUSES: frozenset[str] = frozenset({"running", "paused", "completed", "failed"})


class RunLifecycleError(ValueError):
    """Persisted or in-memory run record violates lifecycle invariants."""


@dataclass
class StopRecord:
    code: StopCode
    category: StopCategory
    phase: str
    message: str
    role: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "category": self.category,
            "phase": self.phase,
            "message": self.message,
            "role": self.role,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StopRecord:
        code = data.get("code")
        if not isinstance(code, str) or not code:
            raise RunLifecycleError("stop.code is required")
        category = data.get("category")
        if category not in ("operational", "invariant"):
            raise RunLifecycleError("stop.category must be operational or invariant")
        phase = data.get("phase")
        if not isinstance(phase, str) or not phase.strip():
            raise RunLifecycleError("stop.phase is required")
        message = data.get("message")
        if not isinstance(message, str) or not message.strip():
            raise RunLifecycleError("stop.message is required")
        details = data.get("details")
        if details is None:
            details = {}
        if not isinstance(details, dict):
            raise RunLifecycleError("stop.details must be an object")
        role = data.get("role")
        if role is not None and (not isinstance(role, str) or not role.strip()):
            raise RunLifecycleError("stop.role must be a non-empty string when present")
        return cls(
            code=code,  # type: ignore[arg-type]
            category=category,
            phase=phase,
            message=message,
            role=role,
            details=dict(details),
        )


def validate_stop_record(data: dict[str, Any], *, expected_category: StopCategory | None = None) -> StopRecord:
    record = StopRecord.from_dict(data)
    if expected_category is not None and record.category != expected_category:
        raise RunLifecycleError(
            f"stop.category must be {expected_category!r}, got {record.category!r}"
        )
    if record.category == "operational" and record.code not in PAUSED_STOP_CODES:
        raise RunLifecycleError(f"unknown operational stop code: {record.code!r}")
    if record.category == "invariant" and record.code not in FAILED_STOP_CODES:
        raise RunLifecycleError(f"unknown invariant stop code: {record.code!r}")
    return record


def validate_phase_action_id(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise RunLifecycleError("phase_action_id must be a non-empty string or null")
    return value


def validate_run_lifecycle_invariants(run: dict[str, Any]) -> None:
    """Validate status/outcome/stop invariants for a run record payload."""

    status = run.get("status")
    if status not in RUN_STATUSES:
        raise RunLifecycleError(f"unsupported run status: {status!r}")

    if "stop" not in run:
        raise RunLifecycleError("run.stop is required (use null when inactive)")

    outcome = run.get("outcome")
    stop_raw = run.get("stop")

    if "phase_action_id" not in run:
        raise RunLifecycleError("run.phase_action_id is required (use null when unset)")
    validate_phase_action_id(run.get("phase_action_id"))

    if status == "running":
        if outcome is not None:
            raise RunLifecycleError("running run must have outcome null")
        if stop_raw is not None:
            raise RunLifecycleError("running run must have stop null")
        return

    if status == "paused":
        if outcome is not None:
            raise RunLifecycleError("paused run must have outcome null")
        if not isinstance(stop_raw, dict):
            raise RunLifecycleError("paused run requires a structured stop record")
        validate_stop_record(stop_raw, expected_category="operational")
        return

    if status == "completed":
        if outcome is None:
            raise RunLifecycleError("completed run requires a non-null outcome")
        if stop_raw is not None:
            raise RunLifecycleError("completed run must have stop null")
        return

    if status == "failed":
        if outcome is not None:
            raise RunLifecycleError("failed run must have outcome null")
        if not isinstance(stop_raw, dict):
            raise RunLifecycleError("failed run requires a structured stop record")
        validate_stop_record(stop_raw, expected_category="invariant")
        return


def continuation_ok_from_run(run: dict[str, Any]) -> bool:
    """Map durable run state to continuation/resume success semantics."""

    status = str(run.get("status") or "")
    if status == "completed":
        return str(run.get("outcome") or "") == "accepted"
    if status in {"failed", "paused"}:
        return False
    return True


__all__ = [
    "FAILED_STOP_CODES",
    "PAUSED_STOP_CODES",
    "RUN_STATUSES",
    "FailedStopCode",
    "PausedStopCode",
    "RunLifecycleError",
    "RunStatus",
    "StopCategory",
    "StopCode",
    "StopRecord",
    "continuation_ok_from_run",
    "validate_phase_action_id",
    "validate_run_lifecycle_invariants",
    "validate_stop_record",
]
