"""Run-store structured session binding persistence (proposal §11)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from top_down_planning.domain.session_bindings import (
    PRIMARY_PLANNER_SLOT,
    PRIMARY_PRODUCER_SLOT,
    SessionBinding,
    SessionBindingError,
    binding_provider_session_id,
    new_session_binding,
    resumable_binding_provider_session_id,
    validate_session_binding,
)
from top_down_planning.persistence.path_ids import validate_store_id
from top_down_planning.persistence.persisted_validation import (
    canonicalize_persisted_review,
    validate_persisted_sessions,
)

_SLOT_ROLE_KIND: dict[str, tuple[str, str]] = {
    PRIMARY_PLANNER_SLOT: ("planner", "primary"),
    PRIMARY_PRODUCER_SLOT: ("producer", "primary"),
}

_REJECTED_LEGACY_SESSION_FIELDS = frozenset(
    {
        "primary_planner_session_id",
        "primary_producer_session_id",
    }
)

_REJECTED_LEGACY_REVIEW_FIELDS = frozenset({"reviewer_session_id"})

StructuredSessions = dict[str, dict[str, Any]]


class LegacySessionFieldError(SessionBindingError):
    """Persisted session payload uses a removed flat session-id field."""


def _reject_legacy_session_fields(sessions: dict[str, Any]) -> None:
    for field in _REJECTED_LEGACY_SESSION_FIELDS:
        if field in sessions:
            raise LegacySessionFieldError(
                f"legacy session field {field!r} is not accepted; "
                "use structured sessions.{primary_planner,primary_producer}; recreate the run"
            )


def initial_structured_sessions() -> StructuredSessions:
    return {
        PRIMARY_PLANNER_SLOT: new_session_binding(
            role="planner",
            kind="primary",
            state="unbound",
        ).to_dict(),
        PRIMARY_PRODUCER_SLOT: new_session_binding(
            role="producer",
            kind="primary",
            state="unbound",
        ).to_dict(),
    }


def coerce_structured_sessions(sessions: dict[str, Any] | None) -> StructuredSessions:
    """Fill in-memory session maps for orchestration mutations only.

    Persisted load and save use ``validate_persisted_sessions`` instead.
    """

    raw = dict(sessions or {})
    _reject_legacy_session_fields(raw)
    structured: StructuredSessions = {}

    for slot, (role, kind) in _SLOT_ROLE_KIND.items():
        existing = raw.get(slot)
        if isinstance(existing, dict) and existing.get("session_instance_id"):
            binding = SessionBinding.from_dict(existing)
        else:
            binding = new_session_binding(role=role, kind=kind, state="unbound")
        structured[slot] = binding.to_dict()

    for key, value in raw.items():
        if key in _SLOT_ROLE_KIND:
            continue
        if isinstance(value, dict) and value.get("session_instance_id"):
            structured[key] = SessionBinding.from_dict(value).to_dict()
    return structured


def sessions_for_persistence(sessions: dict[str, Any] | None) -> StructuredSessions:
    _reject_legacy_session_fields(dict(sessions or {}))
    return validate_persisted_sessions(sessions)


def get_primary_binding(
    run: dict[str, Any],
    role: str,
) -> SessionBinding | None:
    sessions = run.get("sessions") or {}
    slot = PRIMARY_PLANNER_SLOT if role == "planner" else PRIMARY_PRODUCER_SLOT
    payload = sessions.get(slot)
    if not isinstance(payload, dict) or not payload.get("session_instance_id"):
        return None
    return SessionBinding.from_dict(payload)


def primary_provider_session_id(run: dict[str, Any], role: str) -> str | None:
    return resumable_binding_provider_session_id(get_primary_binding(run, role))


def update_primary_binding(
    sessions: dict[str, Any],
    *,
    role: str,
    provider_session_id: str,
    provider: str | None = None,
    model: str | None = None,
    activity: str | None = None,
    context_digest: str | None = None,
) -> StructuredSessions:
    slot = PRIMARY_PLANNER_SLOT if role == "planner" else PRIMARY_PRODUCER_SLOT
    structured = coerce_structured_sessions(sessions)
    existing_payload = structured.get(slot) or new_session_binding(
        role=role,
        kind="primary",
        state="unbound",
    ).to_dict()
    binding = SessionBinding.from_dict(existing_payload)
    updated = binding.with_provider_session_id(
        provider_session_id,
        provider=provider,
        model=model,
    )
    if activity is not None:
        activity_text = str(activity).strip() or None
        updated = replace(updated, activity=activity_text)
    if context_digest is not None:
        digest_text = str(context_digest).strip() or None
        updated = replace(updated, context_digest=digest_text)
    structured[slot] = updated.to_dict()
    return structured


def bump_primary_binding_generation(
    sessions: dict[str, Any],
    *,
    role: str,
) -> StructuredSessions:
    slot = PRIMARY_PLANNER_SLOT if role == "planner" else PRIMARY_PRODUCER_SLOT
    structured = coerce_structured_sessions(sessions)
    payload = structured.get(slot) or new_session_binding(
        role=role,
        kind="primary",
        state="unbound",
    ).to_dict()
    binding = SessionBinding.from_dict(payload).with_next_generation()
    structured[slot] = binding.to_dict()
    return structured


def clear_stale_starting_primary_binding(
    sessions: dict[str, Any],
    *,
    role: str,
) -> StructuredSessions:
    """Bump generation and clear provider id for a stale ``starting`` primary binding."""

    slot = PRIMARY_PLANNER_SLOT if role == "planner" else PRIMARY_PRODUCER_SLOT
    structured = coerce_structured_sessions(sessions)
    payload = structured.get(slot)
    if not isinstance(payload, dict) or not payload.get("session_instance_id"):
        return structured
    binding = SessionBinding.from_dict(payload)
    if binding.state != "starting" or not binding.provider_session_id:
        return structured
    structured[slot] = binding.released_for_reallocation().to_dict()
    return structured


def review_record_for_persistence(review: dict[str, Any]) -> dict[str, Any]:
    payload = dict(review)
    for field in _REJECTED_LEGACY_REVIEW_FIELDS:
        if field in payload:
            raise LegacySessionFieldError(
                f"legacy review field {field!r} is not accepted; "
                "use reviewer_binding; recreate the run"
            )
    review_id = validate_store_id(str(payload.get("id") or ""), label="review_id")
    return canonicalize_persisted_review(review_id, payload)


__all__ = [
    "LegacySessionFieldError",
    "bump_primary_binding_generation",
    "clear_stale_starting_primary_binding",
    "coerce_structured_sessions",
    "get_primary_binding",
    "initial_structured_sessions",
    "primary_provider_session_id",
    "review_record_for_persistence",
    "sessions_for_persistence",
    "update_primary_binding",
]
