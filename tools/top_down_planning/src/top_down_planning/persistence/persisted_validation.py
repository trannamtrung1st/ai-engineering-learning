"""Strict validation for persisted current-schema records at the store boundary."""

from __future__ import annotations

from typing import Any

from core_tools.persistence import PersistenceError, parse_revision_value

from top_down_planning.domain.session_bindings import (
    PRIMARY_PLANNER_SLOT,
    PRIMARY_PRODUCER_SLOT,
    SessionBinding,
    SessionBindingError,
    validate_session_binding,
)
from top_down_planning.persistence.run_schema import (
    validate_run_digests,
    validate_run_schema_version,
)

_PROTECTED_RUN_RECORD_KEYS = frozenset(
    {
        "id",
        "schema_version",
        "revision",
        "status",
        "phase",
        "outcome",
        "stop",
        "phase_action_id",
        "session_replacement_phase_action_id",
        "phase_action_domain_committed_id",
        "digests",
        "context_snapshot_binding",
        "sessions",
        "planning",
        "production_loop",
        "created_at",
        "updated_at",
        "workspace",
    }
)

_SLOT_ROLE_KIND: dict[str, tuple[str, str]] = {
    PRIMARY_PLANNER_SLOT: ("planner", "primary"),
    PRIMARY_PRODUCER_SLOT: ("producer", "primary"),
}


def reject_protected_run_extras_keys(run_extras: dict[str, Any]) -> None:
    collisions = sorted(_PROTECTED_RUN_RECORD_KEYS.intersection(run_extras))
    if collisions:
        joined = ", ".join(collisions)
        raise PersistenceError(f"run_extras cannot overwrite protected run fields: {joined}")


def validate_persisted_sessions(sessions: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(sessions, dict):
        raise PersistenceError("sessions must be an object on schema v3 run records")

    structured: dict[str, dict[str, Any]] = {}
    for slot, (role, kind) in _SLOT_ROLE_KIND.items():
        binding_raw = sessions.get(slot)
        if not isinstance(binding_raw, dict):
            raise PersistenceError(f"sessions.{slot} must be a structured session binding")
        try:
            binding = SessionBinding.from_dict(binding_raw)
        except SessionBindingError as exc:
            raise PersistenceError(f"sessions.{slot} is invalid: {exc}") from exc
        if binding.role != role or binding.kind != kind:
            raise PersistenceError(
                f"sessions.{slot} must have role={role!r} and kind={kind!r}"
            )
        if isinstance(binding_raw.get("generation"), bool) or not isinstance(
            binding_raw.get("generation"), int
        ):
            raise PersistenceError(f"sessions.{slot}.generation must be a positive integer")
        if binding.generation < 1:
            raise PersistenceError(f"sessions.{slot}.generation must be a positive integer")
        validate_session_binding(binding)
        structured[slot] = binding.to_dict()

    for key, value in sessions.items():
        if key in _SLOT_ROLE_KIND:
            continue
        if not isinstance(value, dict) or not value.get("session_instance_id"):
            raise PersistenceError(
                f"sessions.{key} must be a structured session binding with session_instance_id"
            )
        try:
            binding = SessionBinding.from_dict(value)
        except SessionBindingError as exc:
            raise PersistenceError(f"sessions.{key} is invalid: {exc}") from exc
        validate_session_binding(binding)
        structured[key] = binding.to_dict()
    return structured


def validate_persisted_review_binding(review: dict[str, Any]) -> dict[str, Any]:
    payload = dict(review)
    if "revision" in payload:
        payload["revision"] = parse_revision_value(payload["revision"], "review")
    binding_raw = payload.get("reviewer_binding")
    if binding_raw is None:
        return payload
    if not isinstance(binding_raw, dict) or not binding_raw.get("session_instance_id"):
        raise PersistenceError("reviewer_binding must be a structured session binding")
    try:
        binding = SessionBinding.from_dict(binding_raw)
    except SessionBindingError as exc:
        raise PersistenceError(f"reviewer_binding is invalid: {exc}") from exc
    validate_session_binding(binding)
    payload["reviewer_binding"] = binding.to_dict()
    return payload


def validate_persisted_run(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    validate_run_schema_version(payload)
    validate_run_digests(payload)
    persisted_id = str(payload.get("id") or "").strip()
    if persisted_id != run_id:
        raise PersistenceError("run.id does not match run directory id")
    parse_revision_value(payload.get("revision"), "run")
    sessions = validate_persisted_sessions(payload.get("sessions"))
    normalized = dict(payload)
    normalized["sessions"] = sessions
    return normalized


__all__ = [
    "reject_protected_run_extras_keys",
    "validate_persisted_review_binding",
    "validate_persisted_run",
    "validate_persisted_sessions",
]
