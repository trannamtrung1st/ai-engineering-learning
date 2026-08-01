"""Run-store session binding persistence and migration (proposal §9)."""

from __future__ import annotations

from typing import Any

from top_down_planning.domain.session_bindings import (
    LEGACY_PRIMARY_SESSION_FIELDS,
    PRIMARY_PLANNER_SLOT,
    PRIMARY_PRODUCER_SLOT,
    SessionBinding,
    SessionBindingError,
    binding_from_legacy_provider_session_id,
    binding_provider_session_id,
    is_transient_provider_session_id,
    new_session_binding,
    validate_session_binding,
)

_SLOT_ROLE_KIND: dict[str, tuple[str, str]] = {
    PRIMARY_PLANNER_SLOT: ("planner", "primary"),
    PRIMARY_PRODUCER_SLOT: ("producer", "primary"),
}

StructuredSessions = dict[str, dict[str, Any]]


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


def _binding_dict(binding: SessionBinding | dict[str, Any]) -> dict[str, Any]:
    if isinstance(binding, SessionBinding):
        return binding.to_dict()
    if not isinstance(binding, dict):
        raise SessionBindingError("session binding must be a mapping or SessionBinding")
    return SessionBinding.from_dict(binding).to_dict()


def migrate_sessions_payload(sessions: dict[str, Any] | None) -> StructuredSessions:
    raw = dict(sessions or {})
    structured: StructuredSessions = {}

    for slot, (role, kind) in _SLOT_ROLE_KIND.items():
        existing = raw.get(slot)
        legacy_field = next(
            (field for field, mapped_slot in LEGACY_PRIMARY_SESSION_FIELDS.items() if mapped_slot == slot),
            None,
        )
        legacy_value = raw.get(legacy_field) if legacy_field is not None else None
        if isinstance(existing, dict) and existing.get("session_instance_id"):
            binding = SessionBinding.from_dict(existing)
        else:
            binding = binding_from_legacy_provider_session_id(
                role=role,
                kind=kind,
                provider_session_id=(
                    str(legacy_value).strip()
                    if legacy_value is not None and str(legacy_value).strip()
                    else None
                ),
            )
        structured[slot] = binding.to_dict()

    for key, value in raw.items():
        if key in LEGACY_PRIMARY_SESSION_FIELDS or key in _SLOT_ROLE_KIND:
            continue
        if isinstance(value, dict) and value.get("session_instance_id"):
            structured[key] = SessionBinding.from_dict(value).to_dict()
    return structured


def enrich_sessions_for_runtime(sessions: dict[str, Any] | None) -> dict[str, Any]:
    structured = migrate_sessions_payload(sessions)
    runtime: dict[str, Any] = dict(structured)
    for legacy_field, slot in LEGACY_PRIMARY_SESSION_FIELDS.items():
        runtime[legacy_field] = binding_provider_session_id(structured.get(slot))
    return runtime


def sessions_for_persistence(sessions: dict[str, Any] | None) -> StructuredSessions:
    structured = migrate_sessions_payload(sessions)
    for slot, payload in structured.items():
        binding = SessionBinding.from_dict(payload)
        validate_session_binding(binding)
        structured[slot] = binding.to_dict()
    return structured


def get_primary_binding(
    run: dict[str, Any],
    role: str,
) -> SessionBinding | None:
    sessions = run.get("sessions") or {}
    slot = PRIMARY_PLANNER_SLOT if role == "planner" else PRIMARY_PRODUCER_SLOT
    payload = sessions.get(slot)
    if not isinstance(payload, dict) or not payload.get("session_instance_id"):
        legacy_field = (
            "primary_planner_session_id"
            if role == "planner"
            else "primary_producer_session_id"
        )
        legacy_value = sessions.get(legacy_field)
        if legacy_value is None or not str(legacy_value).strip():
            return None
        return binding_from_legacy_provider_session_id(
            role=role,
            kind="primary",
            provider_session_id=str(legacy_value).strip(),
        )
    return SessionBinding.from_dict(payload)


def primary_provider_session_id(run: dict[str, Any], role: str) -> str | None:
    binding = get_primary_binding(run, role)
    if binding is None:
        return None
    return binding.provider_session_id


def update_primary_binding(
    sessions: dict[str, Any],
    *,
    role: str,
    provider_session_id: str,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    slot = PRIMARY_PLANNER_SLOT if role == "planner" else PRIMARY_PRODUCER_SLOT
    migrated = migrate_sessions_payload(sessions)
    existing_payload = migrated.get(slot) or new_session_binding(
        role=role,
        kind="primary",
        state="unbound",
    ).to_dict()
    binding = SessionBinding.from_dict(existing_payload)
    if is_transient_provider_session_id(provider_session_id):
        updated = binding.with_provider_session_id(
            provider_session_id,
            provider=provider,
            model=model,
            allow_transient=True,
        )
    else:
        updated = binding.with_provider_session_id(
            provider_session_id,
            provider=provider,
            model=model,
        )
    migrated[slot] = updated.to_dict()
    return enrich_sessions_for_runtime(migrated)


def bump_primary_binding_generation(
    sessions: dict[str, Any],
    *,
    role: str,
) -> dict[str, Any]:
    from top_down_planning.domain.session_bindings import SessionBinding

    slot = PRIMARY_PLANNER_SLOT if role == "planner" else PRIMARY_PRODUCER_SLOT
    migrated = migrate_sessions_payload(sessions)
    payload = migrated.get(slot) or new_session_binding(
        role=role,
        kind="primary",
        state="unbound",
    ).to_dict()
    binding = SessionBinding.from_dict(payload).with_next_generation()
    migrated[slot] = binding.to_dict()
    return enrich_sessions_for_runtime(migrated)


def clear_stale_starting_primary_binding(
    sessions: dict[str, Any],
    *,
    role: str,
) -> dict[str, Any]:
    """Bump generation and clear provider id for a stale ``starting`` primary binding."""

    slot = PRIMARY_PLANNER_SLOT if role == "planner" else PRIMARY_PRODUCER_SLOT
    migrated = migrate_sessions_payload(sessions)
    payload = migrated.get(slot)
    if not isinstance(payload, dict) or not payload.get("session_instance_id"):
        return enrich_sessions_for_runtime(migrated)
    binding = SessionBinding.from_dict(payload)
    if binding.state != "starting":
        return enrich_sessions_for_runtime(migrated)
    migrated[slot] = binding.with_next_generation().to_dict()
    return enrich_sessions_for_runtime(migrated)


def normalize_review_record_for_runtime(review: dict[str, Any]) -> dict[str, Any]:
    payload = dict(review)
    binding_raw = payload.get("reviewer_binding")
    legacy = payload.get("reviewer_session_id")
    if isinstance(binding_raw, dict) and binding_raw.get("session_instance_id"):
        binding = SessionBinding.from_dict(binding_raw)
        payload["reviewer_binding"] = binding.to_dict()
        payload["reviewer_session_id"] = binding.provider_session_id
        return payload
    if legacy is not None and str(legacy).strip():
        from top_down_planning.domain.session_bindings import (
            reviewer_binding_from_legacy_session_id,
        )

        binding = reviewer_binding_from_legacy_session_id(str(legacy).strip())
        if binding is not None:
            payload["reviewer_binding"] = binding.to_dict()
            payload["reviewer_session_id"] = binding.provider_session_id
    return payload


def review_record_for_persistence(review: dict[str, Any]) -> dict[str, Any]:
    payload = dict(review)
    binding_raw = payload.get("reviewer_binding")
    legacy = payload.get("reviewer_session_id")
    if isinstance(binding_raw, dict) and binding_raw.get("session_instance_id"):
        binding = SessionBinding.from_dict(binding_raw)
    elif legacy is not None and str(legacy).strip():
        from top_down_planning.domain.session_bindings import (
            reviewer_binding_from_legacy_session_id,
        )

        binding = reviewer_binding_from_legacy_session_id(str(legacy).strip())
        if binding is None:
            payload.pop("reviewer_binding", None)
            payload.pop("reviewer_session_id", None)
            return payload
    else:
        payload.pop("reviewer_binding", None)
        payload.pop("reviewer_session_id", None)
        return payload
    validate_session_binding(binding)
    payload["reviewer_binding"] = binding.to_dict()
    payload.pop("reviewer_session_id", None)
    return payload


__all__ = [
    "bump_primary_binding_generation",
    "clear_stale_starting_primary_binding",
    "enrich_sessions_for_runtime",
    "get_primary_binding",
    "initial_structured_sessions",
    "migrate_sessions_payload",
    "normalize_review_record_for_runtime",
    "primary_provider_session_id",
    "review_record_for_persistence",
    "sessions_for_persistence",
    "update_primary_binding",
]
