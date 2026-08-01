"""Orchestrator helpers for issuing session capability tokens."""

from __future__ import annotations

from typing import Any

from top_down_planning.domain.capability_binding import (
    CapabilitySessionBinding,
    capability_binding_from_session_binding,
    resolve_primary_capability_binding,
    resolve_reviewer_capability_binding,
)
from top_down_planning.persistence.capabilities import (
    capability_token_value,
    ops_for_session,
    parse_capability_token,
)
from top_down_planning.persistence.interface import RunStore


def revoke_capability_token(store: RunStore, run_id: str, token: str | None) -> None:
    """Revoke a serialized capability token when present."""

    if token is None or not str(token).strip():
        return
    try:
        token_id, _secret = parse_capability_token(str(token).strip())
    except ValueError:
        return
    try:
        record = store.load_capability(run_id, token_id)
    except Exception:
        return
    if record.get("revoked") is True:
        return
    store.revoke_capability(run_id, token_id)


def revoke_capabilities_for_phase(store: RunStore, run_id: str, phase: str) -> None:
    """Revoke all live capabilities issued for a run phase."""

    for record in store.list_capabilities(run_id):
        if record.get("revoked") is True:
            continue
        if str(record.get("phase") or "") != str(phase):
            continue
        capability_id = str(record.get("id") or "")
        if capability_id:
            store.revoke_capability(run_id, capability_id)


def revoke_capabilities_for_loop(store: RunStore, run_id: str, loop_id: str) -> None:
    """Revoke all live capabilities bound to a review loop."""

    normalized_loop_id = str(loop_id).strip()
    for record in store.list_capabilities(run_id):
        if record.get("revoked") is True:
            continue
        if str(record.get("loop_id") or "") != normalized_loop_id:
            continue
        capability_id = str(record.get("id") or "")
        if capability_id:
            store.revoke_capability(run_id, capability_id)


def revoke_capabilities_for_session_binding(
    store: RunStore,
    run_id: str,
    *,
    session_instance_id: str,
    generation: int,
) -> None:
    """Revoke live capabilities for stale generations of an internal session identity."""

    normalized_instance_id = str(session_instance_id).strip()
    if not normalized_instance_id:
        return
    target_generation = int(generation)
    for record in store.list_capabilities(run_id):
        if record.get("revoked") is True:
            continue
        if str(record.get("session_instance_id") or "").strip() != normalized_instance_id:
            continue
        record_generation = record.get("generation")
        if record_generation is None:
            capability_id = str(record.get("id") or "")
            if capability_id:
                store.revoke_capability(run_id, capability_id)
            continue
        if int(record_generation) == target_generation:
            continue
        capability_id = str(record.get("id") or "")
        if capability_id:
            store.revoke_capability(run_id, capability_id)


def revoke_all_capabilities_for_session_instance(
    store: RunStore,
    run_id: str,
    *,
    session_instance_id: str,
) -> None:
    """Revoke all live capabilities bound to a session instance identity."""

    normalized_instance_id = str(session_instance_id).strip()
    if not normalized_instance_id:
        return
    for record in store.list_capabilities(run_id):
        if record.get("revoked") is True:
            continue
        if str(record.get("session_instance_id") or "").strip() != normalized_instance_id:
            continue
        capability_id = str(record.get("id") or "")
        if capability_id:
            store.revoke_capability(run_id, capability_id)


def _resolve_capability_binding(
    store: RunStore,
    run_id: str,
    *,
    role: str,
    session_id: str,
    session_kind: str,
    loop_id: str | None,
) -> CapabilitySessionBinding:
    normalized_session_id = str(session_id).strip()
    if role == "reviewer" or session_kind == "reviewer":
        if loop_id is None or not str(loop_id).strip():
            raise ValueError("loop_id is required for reviewer capabilities")
        normalized_loop_id = str(loop_id).strip()
        loop = store.load_review(run_id, normalized_loop_id)
        return resolve_reviewer_capability_binding(
            loop,
            provider_session_id=normalized_session_id,
            loop_id=normalized_loop_id,
        )

    run = store.load_run(run_id)
    return resolve_primary_capability_binding(
        run,
        role,
        provider_session_id=normalized_session_id,
    )


def issue_session_capability(
    store: RunStore,
    run_id: str,
    *,
    role: str,
    phase: str,
    session_id: str,
    session_kind: str = "primary",
    loop_id: str | None = None,
    revoke_existing: bool = True,
) -> str:
    """Create and return a capability token for a provider session."""

    binding = _resolve_capability_binding(
        store,
        run_id,
        role=role,
        session_id=session_id,
        session_kind=session_kind,
        loop_id=loop_id,
    )

    if revoke_existing:
        store.revoke_capabilities_for_session(run_id, binding.provider_session_id)
        revoke_capabilities_for_session_binding(
            store,
            run_id,
            session_instance_id=binding.session_instance_id,
            generation=binding.generation,
        )

    allowed_ops = ops_for_session(role, phase, session_kind=session_kind)
    capability_id, _record, raw_secret = store.create_capability(
        run_id,
        role=role,
        phase=phase,
        allowed_ops=allowed_ops,
        session_id=binding.provider_session_id,
        session_kind=session_kind,
        loop_id=loop_id,
        session_instance_id=binding.session_instance_id,
        generation=binding.generation,
    )
    return capability_token_value(capability_id, raw_secret)


def rotate_session_capability(
    store: RunStore,
    run_id: str,
    *,
    current_token: str | None,
    role: str,
    phase: str,
    session_id: str,
    session_kind: str = "primary",
    loop_id: str | None = None,
) -> str:
    """Revoke the current token and issue a fresh one for the next turn."""

    revoke_capability_token(store, run_id, current_token)
    return issue_session_capability(
        store,
        run_id,
        role=role,
        phase=phase,
        session_id=session_id,
        session_kind=session_kind,
        loop_id=loop_id,
        revoke_existing=False,
    )


def bind_provider_capability(provider: Any, token: str | None) -> None:
    """Export a capability token to provider subprocesses when supported."""

    setter = getattr(provider, "set_capability_token", None)
    if setter is not None and token is not None:
        setter(token)


def adopt_replacement_capability(
    store: RunStore,
    run_id: str,
    *,
    current_token: str | None,
    replacement_token: str | None,
    provider: Any,
) -> str | None:
    """Revoke the orchestrator-held token and adopt the recovery-issued replacement."""

    if replacement_token is None:
        return current_token
    revoke_capability_token(store, run_id, current_token)
    bind_provider_capability(provider, replacement_token)
    return replacement_token
