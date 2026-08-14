"""Session lineage audit event payloads (proposal §17.2)."""

from __future__ import annotations

from typing import Any

SESSION_PROVIDER_ID_BOUND = "session_provider_id_bound"
SESSION_REPLACED = "session_replaced"
SESSION_REPLACEMENT_STARTED = "session_replacement_started"
SESSION_REPLACEMENT_FAILED = "session_replacement_failed"
SESSION_RESUME_FAILED = "session_resume_failed"

LINEAGE_EVENT_TYPES = frozenset(
    {
        SESSION_PROVIDER_ID_BOUND,
        SESSION_REPLACED,
        SESSION_REPLACEMENT_STARTED,
        SESSION_REPLACEMENT_FAILED,
        SESSION_RESUME_FAILED,
    }
)

REASON_PROVIDER_SESSION_NOT_FOUND = "provider_session_not_found"
REASON_PROVIDER_TURN_STALLED = "provider_turn_stalled"


def _base_fields(
    *,
    run_id: str,
    phase: str,
    role: str,
    phase_action_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "",
        "run_id": str(run_id),
        "phase": str(phase),
        "role": str(role),
    }
    if phase_action_id is not None and str(phase_action_id).strip():
        payload["phase_action_id"] = str(phase_action_id).strip()
    return payload


def session_provider_id_bound_payload(
    *,
    run_id: str,
    phase: str,
    role: str,
    session_instance_id: str,
    generation: int,
    provider_session_id: str,
    provider: str | None = None,
    loop_id: str | None = None,
    phase_action_id: str | None = None,
) -> dict[str, Any]:
    payload = _base_fields(
        run_id=run_id,
        phase=phase,
        role=role,
        phase_action_id=phase_action_id,
    )
    payload["type"] = SESSION_PROVIDER_ID_BOUND
    payload["session_instance_id"] = str(session_instance_id).strip()
    payload["generation"] = int(generation)
    payload["provider_session_id"] = str(provider_session_id).strip()
    if provider is not None and str(provider).strip():
        payload["provider"] = str(provider).strip()
    if loop_id is not None and str(loop_id).strip():
        payload["loop_id"] = str(loop_id).strip()
    return payload


def session_replacement_started_payload(
    *,
    run_id: str,
    phase: str,
    role: str,
    session_instance_id: str,
    generation: int,
    reason: str,
    old_provider_session_id: str | None = None,
    phase_action_id: str | None = None,
    loop_id: str | None = None,
    old_session_instance_id: str | None = None,
    new_session_instance_id: str | None = None,
) -> dict[str, Any]:
    payload = _base_fields(
        run_id=run_id,
        phase=phase,
        role=role,
        phase_action_id=phase_action_id,
    )
    payload["type"] = SESSION_REPLACEMENT_STARTED
    payload["session_instance_id"] = str(session_instance_id).strip()
    payload["generation"] = int(generation)
    payload["reason"] = str(reason).strip()
    new_id = str(new_session_instance_id or session_instance_id).strip()
    payload["new_session_instance_id"] = new_id
    if old_session_instance_id is not None and str(old_session_instance_id).strip():
        payload["old_session_instance_id"] = str(old_session_instance_id).strip()
    if old_provider_session_id is not None and str(old_provider_session_id).strip():
        payload["old_provider_session_id"] = str(old_provider_session_id).strip()
    if loop_id is not None and str(loop_id).strip():
        payload["loop_id"] = str(loop_id).strip()
    return payload


def session_replaced_payload(
    *,
    run_id: str,
    phase: str,
    role: str,
    old_session_instance_id: str,
    new_session_instance_id: str,
    generation: int,
    reason: str,
    old_provider_session_id: str | None = None,
    new_provider_session_id: str | None = None,
    phase_action_id: str | None = None,
    loop_id: str | None = None,
) -> dict[str, Any]:
    payload = _base_fields(
        run_id=run_id,
        phase=phase,
        role=role,
        phase_action_id=phase_action_id,
    )
    payload["type"] = SESSION_REPLACED
    payload["old_session_instance_id"] = str(old_session_instance_id).strip()
    payload["new_session_instance_id"] = str(new_session_instance_id).strip()
    payload["generation"] = int(generation)
    payload["reason"] = str(reason).strip()
    if old_provider_session_id is not None and str(old_provider_session_id).strip():
        payload["old_provider_session_id"] = str(old_provider_session_id).strip()
    if new_provider_session_id is not None and str(new_provider_session_id).strip():
        payload["new_provider_session_id"] = str(new_provider_session_id).strip()
    if loop_id is not None and str(loop_id).strip():
        payload["loop_id"] = str(loop_id).strip()
    return payload


def session_resume_failed_payload(
    *,
    run_id: str,
    phase: str,
    role: str,
    session_instance_id: str,
    generation: int,
    reason: str,
    provider_session_id: str | None = None,
    phase_action_id: str | None = None,
    loop_id: str | None = None,
) -> dict[str, Any]:
    payload = _base_fields(
        run_id=run_id,
        phase=phase,
        role=role,
        phase_action_id=phase_action_id,
    )
    payload["type"] = SESSION_RESUME_FAILED
    payload["session_instance_id"] = str(session_instance_id).strip()
    payload["generation"] = int(generation)
    payload["reason"] = str(reason).strip()
    if provider_session_id is not None and str(provider_session_id).strip():
        payload["provider_session_id"] = str(provider_session_id).strip()
    if loop_id is not None and str(loop_id).strip():
        payload["loop_id"] = str(loop_id).strip()
    return payload


def session_replacement_failed_payload(
    *,
    run_id: str,
    phase: str,
    role: str,
    session_instance_id: str,
    generation: int,
    reason: str,
    provider_session_id: str | None = None,
    phase_action_id: str | None = None,
    loop_id: str | None = None,
) -> dict[str, Any]:
    payload = _base_fields(
        run_id=run_id,
        phase=phase,
        role=role,
        phase_action_id=phase_action_id,
    )
    payload["type"] = SESSION_REPLACEMENT_FAILED
    payload["session_instance_id"] = str(session_instance_id).strip()
    payload["generation"] = int(generation)
    payload["reason"] = str(reason).strip()
    if provider_session_id is not None and str(provider_session_id).strip():
        payload["provider_session_id"] = str(provider_session_id).strip()
    if loop_id is not None and str(loop_id).strip():
        payload["loop_id"] = str(loop_id).strip()
    return payload


__all__ = [
    "LINEAGE_EVENT_TYPES",
    "REASON_PROVIDER_SESSION_NOT_FOUND",
    "REASON_PROVIDER_TURN_STALLED",
    "SESSION_PROVIDER_ID_BOUND",
    "SESSION_REPLACED",
    "SESSION_REPLACEMENT_FAILED",
    "SESSION_REPLACEMENT_STARTED",
    "SESSION_RESUME_FAILED",
    "session_provider_id_bound_payload",
    "session_replaced_payload",
    "session_replacement_failed_payload",
    "session_replacement_started_payload",
    "session_resume_failed_payload",
]
