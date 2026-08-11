"""Primary session rotation and ensure helpers for activity-aware bindings."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from core_tools.provider import Provider

from top_down_planning.config import EffectiveActivityContext
from top_down_planning.domain.session_bindings import new_session_binding
from top_down_planning.orchestrator.activity_context import session_continuation_decision
from top_down_planning.orchestrator.session_events import (
    commit_primary_provider_session_binding,
    emit_primary_session_started,
    end_primary_session_with_audit,
    resume_primary_session_with_audit,
)
from top_down_planning.persistence.interface import RunStore
from top_down_planning.persistence.session_bindings import (
    bump_primary_binding_generation,
    get_primary_binding,
)

PrimarySessionRole = Literal["planner", "producer"]


def rotate_primary_session(
    store: RunStore,
    run_id: str,
    provider: Provider,
    *,
    role: PrimarySessionRole,
    phase: str,
    old_provider_session_id: str,
    requested: EffectiveActivityContext,
    manifest: dict[str, Any],
    append_event: Callable[..., None],
    phase_action_id: str | None = None,
    handoff_request: dict[str, Any] | None = None,
) -> str:
    """Terminate the old primary session, bump binding generation, and start fresh."""

    end_primary_session_with_audit(
        append_event,
        provider,
        role=role,
        phase=phase,
        session_id=old_provider_session_id,
    )

    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    updated_sessions = bump_primary_binding_generation(
        dict(run.get("sessions") or {}),
        role=role,
    )
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["sessions"] = updated_sessions
    store.save_run(run_id, run, expected_revision)

    fresh_manifest = (
        {**manifest, **handoff_request} if handoff_request is not None else manifest
    )
    new_session_id = provider.start_primary_session(
        role,
        fresh_manifest,
        model=requested.model,
    )
    emit_primary_session_started(
        append_event,
        provider,
        role=role,
        phase=phase,
        session_id=new_session_id,
        activity=requested.activity,
        context_digest=requested.context_digest,
    )

    commit_primary_provider_session_binding(
        store,
        run_id,
        role=role,
        provider_session_id=new_session_id,
        provider="cursor",
        phase_action_id=phase_action_id,
        activity=requested.activity,
        context_digest=requested.context_digest,
    )
    return new_session_id


def _start_fresh_primary_session(
    store: RunStore,
    run_id: str,
    provider: Provider,
    *,
    role: PrimarySessionRole,
    phase: str,
    requested: EffectiveActivityContext,
    manifest: dict[str, Any],
    append_event: Callable[..., None],
    phase_action_id: str | None = None,
) -> str:
    session_id = provider.start_primary_session(
        role,
        manifest,
        model=requested.model,
    )
    emit_primary_session_started(
        append_event,
        provider,
        role=role,
        phase=phase,
        session_id=session_id,
        activity=requested.activity,
        context_digest=requested.context_digest,
    )
    commit_primary_provider_session_binding(
        store,
        run_id,
        role=role,
        provider_session_id=session_id,
        provider="cursor",
        phase_action_id=phase_action_id,
        activity=requested.activity,
        context_digest=requested.context_digest,
    )
    return session_id


def ensure_primary_session(
    store: RunStore,
    run_id: str,
    provider: Provider,
    *,
    role: PrimarySessionRole,
    phase: str,
    requested: EffectiveActivityContext,
    manifest: dict[str, Any],
    append_event: Callable[..., None],
    resume_request: dict[str, Any],
    phase_action_id: str | None = None,
) -> str:
    """Resume or rotate the primary session to match the requested activity context."""

    run = store.load_run(run_id)
    binding = get_primary_binding(run, role)
    decision_source = binding or new_session_binding(role=role, kind="primary", state="unbound")
    decision = session_continuation_decision(decision_source, requested)

    if binding is not None and decision == "resume":
        session_id = binding.provider_session_id
        if session_id is None:
            raise ValueError(f"bound {role} session is missing provider_session_id")
        resume_primary_session_with_audit(
            append_event,
            provider,
            role=role,
            phase=phase,
            session_id=session_id,
            request=resume_request,
            model=requested.model,
            activity=requested.activity,
            context_digest=requested.context_digest,
        )
        return session_id

    if (
        binding is not None
        and binding.state == "bound"
        and binding.provider_session_id is not None
    ):
        return rotate_primary_session(
            store,
            run_id,
            provider,
            role=role,
            phase=phase,
            old_provider_session_id=binding.provider_session_id,
            requested=requested,
            manifest=manifest,
            append_event=append_event,
            phase_action_id=phase_action_id,
        )

    return _start_fresh_primary_session(
        store,
        run_id,
        provider,
        role=role,
        phase=phase,
        requested=requested,
        manifest=manifest,
        append_event=append_event,
        phase_action_id=phase_action_id,
    )


__all__ = [
    "ensure_primary_session",
    "rotate_primary_session",
]
