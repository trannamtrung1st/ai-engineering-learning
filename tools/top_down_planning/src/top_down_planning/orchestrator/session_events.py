"""Audit events for provider session lifecycle (start/resume)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from top_down_planning.persistence.interface import RunStore
from core_tools.provider import Provider

_PRIMARY_ROLES = frozenset({"planner", "producer"})


def emit_primary_session_started(
    append_event: Callable[..., None],
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
        **fields,
    )


def emit_primary_session_resumed(
    append_event: Callable[..., None],
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
        **fields,
    )


def emit_reviewer_session_started(
    append_event: Callable[..., None],
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
        **fields,
    )


def emit_reviewer_session_resumed(
    append_event: Callable[..., None],
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
