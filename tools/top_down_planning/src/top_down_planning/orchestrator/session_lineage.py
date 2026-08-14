"""Session lineage audit event writers (proposal §17, §18.2 audit emission)."""

from __future__ import annotations

from typing import Any

from top_down_planning.domain.session_lineage import (
    session_provider_id_bound_payload,
    session_replaced_payload,
    session_replacement_failed_payload,
    session_replacement_started_payload,
    session_resume_failed_payload,
)
from top_down_planning.persistence.interface import RunStore


def append_session_lineage_event(
    store: RunStore,
    run_id: str,
    payload: dict[str, Any],
) -> None:
    event = dict(payload)
    event.setdefault("run_id", run_id)
    store.append_event(run_id, event)


def emit_session_provider_id_bound(
    store: RunStore,
    run_id: str,
    *,
    phase: str,
    role: str,
    session_instance_id: str,
    generation: int,
    provider_session_id: str,
    provider: str | None = None,
    loop_id: str | None = None,
    phase_action_id: str | None = None,
) -> None:
    append_session_lineage_event(
        store,
        run_id,
        session_provider_id_bound_payload(
            run_id=run_id,
            phase=phase,
            role=role,
            session_instance_id=session_instance_id,
            generation=generation,
            provider_session_id=provider_session_id,
            provider=provider,
            loop_id=loop_id,
            phase_action_id=phase_action_id,
        ),
    )


def emit_session_replacement_started(
    store: RunStore,
    run_id: str,
    *,
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
) -> None:
    append_session_lineage_event(
        store,
        run_id,
        session_replacement_started_payload(
            run_id=run_id,
            phase=phase,
            role=role,
            session_instance_id=session_instance_id,
            generation=generation,
            reason=reason,
            old_provider_session_id=old_provider_session_id,
            phase_action_id=phase_action_id,
            loop_id=loop_id,
            old_session_instance_id=old_session_instance_id,
            new_session_instance_id=new_session_instance_id,
        ),
    )


def emit_session_replaced(
    store: RunStore,
    run_id: str,
    *,
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
) -> None:
    append_session_lineage_event(
        store,
        run_id,
        session_replaced_payload(
            run_id=run_id,
            phase=phase,
            role=role,
            old_session_instance_id=old_session_instance_id,
            new_session_instance_id=new_session_instance_id,
            generation=generation,
            reason=reason,
            old_provider_session_id=old_provider_session_id,
            new_provider_session_id=new_provider_session_id,
            phase_action_id=phase_action_id,
            loop_id=loop_id,
        ),
    )


def emit_session_resume_failed(
    store: RunStore,
    run_id: str,
    *,
    phase: str,
    role: str,
    session_instance_id: str,
    generation: int,
    reason: str,
    provider_session_id: str | None = None,
    phase_action_id: str | None = None,
    loop_id: str | None = None,
) -> None:
    append_session_lineage_event(
        store,
        run_id,
        session_resume_failed_payload(
            run_id=run_id,
            phase=phase,
            role=role,
            session_instance_id=session_instance_id,
            generation=generation,
            reason=reason,
            provider_session_id=provider_session_id,
            phase_action_id=phase_action_id,
            loop_id=loop_id,
        ),
    )


def emit_session_replacement_failed(
    store: RunStore,
    run_id: str,
    *,
    phase: str,
    role: str,
    session_instance_id: str,
    generation: int,
    reason: str,
    provider_session_id: str | None = None,
    phase_action_id: str | None = None,
    loop_id: str | None = None,
) -> None:
    append_session_lineage_event(
        store,
        run_id,
        session_replacement_failed_payload(
            run_id=run_id,
            phase=phase,
            role=role,
            session_instance_id=session_instance_id,
            generation=generation,
            reason=reason,
            provider_session_id=provider_session_id,
            phase_action_id=phase_action_id,
            loop_id=loop_id,
        ),
    )


__all__ = [
    "append_session_lineage_event",
    "emit_session_provider_id_bound",
    "emit_session_replaced",
    "emit_session_replacement_failed",
    "emit_session_replacement_started",
    "emit_session_resume_failed",
]
