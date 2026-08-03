"""Audit events for provider session lifecycle (start, resume, end)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from top_down_planning.domain.reviews import ReviewLoop, is_mandatory_review_loop
from top_down_planning.domain.session_bindings import (
    is_transient_provider_session_id,
)
from top_down_planning.orchestrator.capability import (
    rebind_primary_session_capability,
    rebind_reviewer_session_capability,
)
from top_down_planning.orchestrator.session_lineage import emit_session_provider_id_bound
from top_down_planning.persistence.interface import RunStore
from top_down_planning.persistence.review_commit import (
    review_record_revision,
    save_review_with_expected_revision,
)
from top_down_planning.persistence.session_bindings import (
    get_primary_binding,
    update_primary_binding,
)
from core_tools.persistence import RunNotFoundError
from core_tools.provider import Provider

_PRIMARY_ROLES = frozenset({"planner", "producer"})


def reviewer_session_audit_fields(loop: ReviewLoop) -> dict[str, Any]:
    """Standard loop context fields for reviewer session audit events."""

    fields: dict[str, Any] = {"loop_id": loop.id, "review_type": loop.type}
    if is_mandatory_review_loop(loop):
        fields["stage"] = loop.active_stage or "initial_review"
    return fields


def _merge_reviewer_session_fields(
    loop: ReviewLoop | None,
    fields: dict[str, Any],
) -> dict[str, Any]:
    if loop is None:
        return fields
    return {**reviewer_session_audit_fields(loop), **fields}


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
    loop: ReviewLoop | None = None,
    **fields: Any,
) -> None:
    merged = _merge_reviewer_session_fields(loop, fields)
    append_event(
        "reviewer_session_started",
        session_id=session_id,
        role="reviewer",
        phase=phase,
        **_session_model_fields(provider, session_id),
        **merged,
    )


def emit_reviewer_session_resumed(
    append_event: Callable[..., None],
    provider: Provider,
    *,
    phase: str,
    session_id: str,
    loop: ReviewLoop | None = None,
    **fields: Any,
) -> None:
    merged = _merge_reviewer_session_fields(loop, fields)
    append_event(
        "reviewer_session_resumed",
        session_id=session_id,
        role="reviewer",
        phase=phase,
        **_session_model_fields(provider, session_id),
        **merged,
    )


def _reviewer_session_is_active(provider: Provider, session_id: str) -> bool:
    canonical_session_id = provider.canonical_session_id(session_id)
    active_ids = {
        str(session["session_id"])
        for session in provider.list_active_sessions()
    }
    return canonical_session_id in active_ids or session_id in active_ids


def end_reviewer_session_with_audit(
    append_event: Callable[..., None],
    provider: Provider,
    *,
    phase: str,
    session_id: str,
    **fields: Any,
) -> str:
    """Terminate a bounded reviewer session and record reviewer_session_ended.

    Idempotent: when the session is already absent from the provider registry,
    termination and the durable audit event are skipped.
    """

    canonical_session_id = provider.canonical_session_id(session_id)
    if not _reviewer_session_is_active(provider, session_id):
        return canonical_session_id

    model_fields = _session_model_fields(provider, canonical_session_id)

    try:
        provider.terminate_session(canonical_session_id)
    except Exception:
        pass

    append_event(
        "reviewer_session_ended",
        session_id=canonical_session_id,
        role="reviewer",
        phase=phase,
        **model_fields,
        **fields,
    )
    return canonical_session_id


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
    loop: ReviewLoop | None = None,
    **fields: Any,
) -> None:
    provider.send(session_id, request, model=model)
    emit_reviewer_session_resumed(
        append_event,
        provider,
        phase=phase,
        session_id=session_id,
        loop=loop,
        **fields,
    )


def commit_primary_provider_session_binding(
    store: RunStore,
    run_id: str,
    *,
    role: str,
    provider_session_id: str,
    provider: str | None = "cursor",
    phase_action_id: str | None = None,
) -> dict[str, Any]:
    """Persist a provider session id on the primary binding.

    Transient ``cursor-pending-*`` ids are stored in ``state: starting``; durable
    ids are promoted to ``state: bound`` during provider turn drain and emit
    ``session_provider_id_bound`` lineage events when first persisted.
    """

    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    phase = str(run.get("phase") or "")
    existing = get_primary_binding(run, role)
    if (
        existing is not None
        and existing.provider_session_id == provider_session_id
        and existing.state in {"bound", "starting"}
    ):
        return run

    run = dict(run)
    run["revision"] = expected_revision + 1
    run["sessions"] = update_primary_binding(
        dict(run.get("sessions") or {}),
        role=role,
        provider_session_id=provider_session_id,
        provider=provider,
    )
    store.save_run(run_id, run, expected_revision)
    saved = store.load_run(run_id)
    binding = get_primary_binding(saved, role)
    if (
        binding is not None
        and binding.provider_session_id
        and not is_transient_provider_session_id(binding.provider_session_id)
    ):
        emit_session_provider_id_bound(
            store,
            run_id,
            phase=phase,
            role=role,
            session_instance_id=binding.session_instance_id,
            generation=binding.generation,
            provider_session_id=binding.provider_session_id,
            provider=binding.provider,
            phase_action_id=phase_action_id,
        )
    return store.load_run(run_id)


def sync_persisted_session_id(
    provider: Provider,
    store: RunStore,
    run_id: str,
    session_id: str,
    *,
    role: str,
) -> str:
    """Persist the provider-native session id when it differs from the stored ref.

    Called during provider turn drain so durable ids are written before the
    turn finishes; orchestrators must not duplicate this after turn completion.
    """

    if role not in _PRIMARY_ROLES:
        raise ValueError(f"unsupported primary session role: {role}")
    resolved = provider.canonical_session_id(session_id)
    run = store.load_run(run_id)
    existing = get_primary_binding(run, role)
    current = existing.provider_session_id if existing is not None else None
    if current == resolved:
        return resolved
    if is_transient_provider_session_id(resolved):
        return resolved

    commit_primary_provider_session_binding(
        store,
        run_id,
        role=role,
        provider_session_id=resolved,
        provider="cursor",
    )
    rebind_primary_session_capability(store, run_id, provider, role=role)
    return resolved


def _emit_reviewer_provider_id_bound(
    store: RunStore,
    run_id: str,
    loop: ReviewLoop,
    *,
    phase_action_id: str | None = None,
) -> None:
    binding = loop.reviewer_binding
    if binding is None or not binding.provider_session_id:
        return
    if is_transient_provider_session_id(binding.provider_session_id):
        return
    run = store.load_run(run_id)
    phase = str(run.get("phase") or "")
    emit_session_provider_id_bound(
        store,
        run_id,
        phase=phase,
        role="reviewer",
        session_instance_id=binding.session_instance_id,
        generation=binding.generation,
        provider_session_id=binding.provider_session_id,
        provider=binding.provider,
        loop_id=loop.id,
        phase_action_id=phase_action_id,
    )


def sync_reviewer_loop_session_id(
    provider: Provider,
    store: RunStore,
    run_id: str,
    loop_id: str,
    session_id: str,
) -> str:
    """Persist the canonical durable reviewer session id on the review loop record.

    Called during provider turn drain. Transient ``cursor-pending-*`` ids are
    ignored. When a durable id is known, the binding is promoted to
    ``state: bound``.
    """

    resolved = provider.canonical_session_id(session_id)
    if is_transient_provider_session_id(resolved):
        return resolved

    review = dict(store.load_review(run_id, loop_id))
    loop = ReviewLoop.from_dict(review)
    binding = loop.reviewer_binding
    prior_provider_id = binding.provider_session_id if binding is not None else None
    if (
        prior_provider_id == resolved
        and binding is not None
        and binding.state == "bound"
    ):
        return resolved

    updated = loop.with_reviewer_provider_session_id(resolved, provider="cursor")
    store.save_review(run_id, updated.to_dict())
    _emit_reviewer_provider_id_bound(store, run_id, updated)
    rebind_reviewer_session_capability(store, run_id, provider, loop_id=loop_id)
    return resolved


def release_reviewer_session_after_decision(
    append_event: Callable[..., None],
    provider: Provider,
    store: RunStore,
    run_id: str,
    *,
    phase: str,
    loop_id: str,
    session_id: str,
) -> str | None:
    """Return the review decision and release the reviewer session when terminal.

    Releases only when ``review_decision_from_store`` returns a non-pending
    decision (approved, changes_requested, etc.). Pending reviews keep the
    session registered for follow-up turns.
    """

    from top_down_planning.orchestrator.provider_turns import review_decision_from_store

    decision = review_decision_from_store(store, run_id, loop_id)
    if decision is not None:
        loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
        end_reviewer_session_with_audit(
            append_event,
            provider,
            phase=phase,
            session_id=provider.canonical_session_id(session_id),
            **reviewer_session_audit_fields(loop),
        )
    return decision


def commit_reviewer_loop_provider_session(
    store: RunStore,
    run_id: str,
    loop: ReviewLoop,
    *,
    phase_action_id: str | None = None,
    expected_revision: int | None = None,
) -> ReviewLoop:
    """Persist reviewer loop binding and emit session_provider_id_bound when durable."""

    if expected_revision is None:
        try:
            review_record = store.load_review(run_id, loop.id)
        except RunNotFoundError:
            expected_revision = 0
        else:
            expected_revision = review_record_revision(review_record)
    save_review_with_expected_revision(
        store,
        run_id,
        loop,
        expected_revision=int(expected_revision),
    )
    _emit_reviewer_provider_id_bound(
        store,
        run_id,
        loop,
        phase_action_id=phase_action_id,
    )
    return loop
