"""Audit events for provider session lifecycle (start/resume)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from top_down_planning.persistence.interface import RunStore
from core_tools.provider import Provider

_PRIMARY_ROLES = frozenset({"planner", "producer"})


def session_model_from_provider(provider: Provider, session_id: str) -> str:
    """Return the provider-resolved model label for an active session."""

    model = provider.get_session_reference(session_id).get("model")
    if not isinstance(model, str) or not model:
        raise ValueError(f"provider session {session_id} is missing a model label")
    return model


def _session_model_fields(provider: Provider, session_id: str) -> dict[str, str]:
    return {"model": session_model_from_provider(provider, session_id)}


def emit_primary_session_started(
    append_event: Callable[..., None],
    provider: Provider,
    *,
    role: str,
    phase: str,
    session_id: str,
    **fields: Any,
) -> None:
    if role not in _PRIMARY_ROLES:
        raise ValueError(f"unsupported primary session role: {role}")
    append_event(
        f"{role}_session_started",
        session_id=session_id,
        role=role,
        phase=phase,
        **_session_model_fields(provider, session_id),
        **fields,
    )


def emit_primary_session_resumed(
    append_event: Callable[..., None],
    provider: Provider,
    *,
    role: str,
    phase: str,
    session_id: str,
    **fields: Any,
) -> None:
    if role not in _PRIMARY_ROLES:
        raise ValueError(f"unsupported primary session role: {role}")
    append_event(
        f"{role}_session_resumed",
        session_id=session_id,
        role=role,
        phase=phase,
        **_session_model_fields(provider, session_id),
        **fields,
    )


def emit_reviewer_session_started(
    append_event: Callable[..., None],
    provider: Provider,
    *,
    phase: str,
    session_id: str,
    **fields: Any,
) -> None:
    append_event(
        "reviewer_session_started",
        session_id=session_id,
        role="reviewer",
        phase=phase,
        **_session_model_fields(provider, session_id),
        **fields,
    )


def emit_reviewer_session_resumed(
    append_event: Callable[..., None],
    provider: Provider,
    *,
    phase: str,
    session_id: str,
    **fields: Any,
) -> None:
    append_event(
        "reviewer_session_resumed",
        session_id=session_id,
        role="reviewer",
        phase=phase,
        **_session_model_fields(provider, session_id),
        **fields,
    )


def resume_primary_session_with_audit(
    append_event: Callable[..., None],
    provider: Provider,
    *,
    role: str,
    phase: str,
    session_id: str,
    request: dict[str, Any],
    model: str | None,
    **fields: Any,
) -> None:
    provider.resume_primary_session(session_id, request, model=model)
    emit_primary_session_resumed(
        append_event,
        provider,
        role=role,
        phase=phase,
        session_id=session_id,
        **fields,
    )


def send_reviewer_session_with_audit(
    append_event: Callable[..., None],
    provider: Provider,
    *,
    phase: str,
    session_id: str,
    request: dict[str, Any],
    model: str | None,
    **fields: Any,
) -> None:
    provider.send(session_id, request, model=model)
    emit_reviewer_session_resumed(
        append_event,
        provider,
        phase=phase,
        session_id=session_id,
        **fields,
    )


def sync_persisted_session_id(
    provider: Provider,
    store: RunStore,
    run_id: str,
    session_id: str,
    *,
    field: str,
) -> str:
    """Persist the provider-native session id when it differs from the stored ref."""

    resolved = provider.canonical_session_id(session_id)
    run = store.load_run(run_id)
    sessions = dict(run.get("sessions") or {})
    if sessions.get(field) == resolved:
        return resolved

    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    sessions[field] = resolved
    run["sessions"] = sessions
    store.save_run(run_id, run, expected_revision)
    return resolved


def sync_reviewer_loop_session_id(
    provider: Provider,
    store: RunStore,
    run_id: str,
    loop_id: str,
    session_id: str,
) -> str:
    """Persist the provider canonical reviewer session id on the review loop record."""

    resolved = provider.canonical_session_id(session_id)
    if resolved == session_id:
        return resolved

    review = dict(store.load_review(run_id, loop_id))
    review["reviewer_session_id"] = resolved
    store.save_review(run_id, review)
    return resolved
