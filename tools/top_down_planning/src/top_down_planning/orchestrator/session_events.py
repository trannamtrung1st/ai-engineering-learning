"""Audit events for provider session lifecycle (start, resume, end)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from top_down_planning.domain.reviews import ReviewLoop, is_mandatory_review_loop
from top_down_planning.domain.session_bindings import (
    is_transient_provider_session_id,
)
from top_down_planning.orchestrator.capability import (
    rebind_primary_session_capability,
    rebind_reviewer_session_capability,
)
from top_down_planning.domain.session_lineage import (
    SESSION_PROVIDER_ID_BOUND,
    SESSION_REPLACED,
    SESSION_REPLACEMENT_FAILED,
    SESSION_REPLACEMENT_STARTED,
    session_provider_id_bound_payload,
)
from top_down_planning.orchestrator.session_lineage import (
    emit_session_provider_id_bound,
    emit_session_replaced,
)
from top_down_planning.persistence.commit import CommitSpec
from top_down_planning.persistence.interface import RunStore
from top_down_planning.persistence.review_commit import (
    review_record_revision,
)
from top_down_planning.persistence.session_bindings import (
    get_primary_binding,
    review_record_for_persistence,
    update_primary_binding,
)
from core_tools.persistence import PersistenceError, RunNotFoundError
from core_tools.provider import Provider
from core_tools.provider.errors import ProviderReplacementIdentityError, ProviderSessionError

_PRIMARY_ROLES = frozenset({"planner", "producer"})
DEFAULT_PROVIDER_LIFECYCLE_TIMEOUT_SECONDS = 2.0


class PublicationState(str, Enum):
    PUBLISHED = "published"
    UNPUBLISHED = "unpublished"
    UNKNOWN = "unknown"


def _require_owned_provider_session(
    provider: Provider,
    session_id: str,
    *,
    role: str,
    kind: str,
) -> str:
    canonical_session_id = provider.canonical_session_id(session_id)
    reference = provider.get_session_reference(canonical_session_id)
    reported_role = str(reference.get("role") or "")
    reported_kind = str(reference.get("kind") or "")
    if reported_role != role or reported_kind != kind:
        raise ProviderSessionError(
            (
                f"refusing to terminate provider session {canonical_session_id}: "
                f"expected {role}/{kind}, provider reports "
                f"{reported_role}/{reported_kind}"
            ),
            session_id=canonical_session_id,
        )
    return canonical_session_id


def resolve_and_assert_session_owner(
    provider: Provider,
    session_id: str,
    *,
    role: str,
    kind: str,
) -> str:
    return _require_owned_provider_session(
        provider,
        session_id,
        role=role,
        kind=kind,
    )


def terminate_owned_session(
    provider: Provider,
    session_id: str,
    *,
    role: str,
    kind: str,
    expected_provider_session_id: str,
) -> str:
    requested = provider.canonical_session_id(session_id)
    expected = provider.canonical_session_id(expected_provider_session_id)
    if requested != expected:
        raise ProviderSessionError(
            (
                f"refusing to terminate provider session {requested}: "
                f"expected bound id {expected}"
            ),
            session_id=requested,
        )
    owned = _require_owned_provider_session(
        provider,
        requested,
        role=role,
        kind=kind,
    )
    provider.terminate_session(
        owned,
        timeout=DEFAULT_PROVIDER_LIFECYCLE_TIMEOUT_SECONDS,
    )
    return owned


def _assert_unique_durable_session_owner(
    provider: Provider,
    store: RunStore,
    run_id: str,
    resolved: str,
    *,
    owner_role: str,
    owner_loop_id: str | None = None,
) -> None:
    if is_transient_provider_session_id(resolved):
        return
    run = store.load_run(run_id)
    for role in ("planner", "producer"):
        binding = get_primary_binding(run, role)
        if binding is None or not binding.provider_session_id:
            continue
        canonical = provider.canonical_session_id(str(binding.provider_session_id))
        if is_transient_provider_session_id(canonical):
            continue
        if canonical != resolved:
            continue
        if owner_role == role and owner_loop_id is None:
            continue
        raise ProviderSessionError(
            (
                f"durable provider session {resolved} is already owned by "
                f"{role}; refusing {owner_role} binding"
            ),
            session_id=resolved,
        )
    for payload in store.list_reviews(run_id):
        loop = ReviewLoop.from_dict(payload)
        binding = loop.reviewer_binding
        if binding is None or not binding.provider_session_id:
            continue
        canonical = provider.canonical_session_id(str(binding.provider_session_id))
        if is_transient_provider_session_id(canonical):
            continue
        if canonical != resolved:
            continue
        if owner_role == "reviewer" and owner_loop_id == loop.id:
            continue
        raise ProviderSessionError(
            (
                f"durable provider session {resolved} is already owned by "
                f"reviewer loop {loop.id}; refusing {owner_role} binding"
            ),
            session_id=resolved,
        )


def _assert_session_binding_before_persist(
    session_provider: Provider | None,
    store: RunStore,
    run_id: str,
    provider_session_id: str,
    *,
    owner_role: str,
    kind: str,
    owner_loop_id: str | None = None,
) -> str:
    if session_provider is None:
        return provider_session_id
    resolved = session_provider.canonical_session_id(provider_session_id)
    _assert_unique_durable_session_owner(
        session_provider,
        store,
        run_id,
        resolved,
        owner_role=owner_role,
        owner_loop_id=owner_loop_id,
    )
    getter = getattr(session_provider, "get_session_reference", None)
    if getter is None:
        raise ProviderSessionError(
            f"provider cannot prove ownership of session {resolved}",
            session_id=resolved,
        )
    reference = None
    lookup_error: ProviderSessionError | None = None
    for candidate in (resolved, provider_session_id):
        try:
            candidate_ref = getter(candidate)
        except ProviderSessionError as exc:
            lookup_error = exc
            continue
        if isinstance(candidate_ref, dict):
            reference = candidate_ref
            break
    if reference is None:
        raise ProviderSessionError(
            f"provider session {resolved} is not registered",
            session_id=resolved,
        ) from lookup_error
    reported_role = str(reference.get("role") or "")
    reported_kind = str(reference.get("kind") or "")
    if reported_role != owner_role or reported_kind != kind:
        raise ProviderSessionError(
            (
                f"refusing to bind provider session {resolved}: "
                f"expected {owner_role}/{kind}, provider reports "
                f"{reported_role}/{reported_kind}"
            ),
            session_id=resolved,
        )
    return resolved


def provider_session_publication_state(
    store: RunStore,
    run_id: str,
    session_id: str,
    provider: Provider,
    *,
    role: str,
    loop_id: str | None = None,
) -> PublicationState:
    canonical = provider.canonical_session_id(session_id)
    try:
        if role == "reviewer" and loop_id is not None:
            loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
            binding = loop.reviewer_binding
        else:
            binding = get_primary_binding(store.load_run(run_id), role)
    except Exception:
        return PublicationState.UNKNOWN
    if binding is None or not binding.provider_session_id:
        return PublicationState.UNPUBLISHED
    try:
        bound = provider.canonical_session_id(binding.provider_session_id)
    except Exception:
        return PublicationState.UNKNOWN
    if bound == canonical:
        return PublicationState.PUBLISHED
    return PublicationState.UNPUBLISHED


def provider_session_is_published(
    store: RunStore,
    run_id: str,
    session_id: str,
    provider: Provider,
    *,
    role: str,
    loop_id: str | None = None,
) -> bool:
    return (
        provider_session_publication_state(
            store,
            run_id,
            session_id,
            provider,
            role=role,
            loop_id=loop_id,
        )
        is PublicationState.PUBLISHED
    )


def discard_if_unpublished(
    provider: Provider,
    store: RunStore,
    run_id: str,
    session_id: str,
    *,
    preexisting_ids: set[str],
    role: str,
    loop_id: str | None = None,
) -> None:
    state = provider_session_publication_state(
        store,
        run_id,
        session_id,
        provider,
        role=role,
        loop_id=loop_id,
    )
    if state is PublicationState.PUBLISHED:
        return
    if state is PublicationState.UNKNOWN:
        raise PersistenceError(
            f"cannot discard provider session {session_id}: publication state unknown"
        )
    discard_unbound_provider_session(
        provider,
        session_id,
        preexisting_ids=preexisting_ids,
    )


def validate_provider_session_binding(
    session_provider: Provider | None,
    store: RunStore,
    run_id: str,
    provider_session_id: str,
    *,
    owner_role: str,
    kind: str,
    owner_loop_id: str | None = None,
) -> str:
    """Canonicalize a candidate ID and require uniqueness plus role/kind proof."""

    return _assert_session_binding_before_persist(
        session_provider,
        store,
        run_id,
        provider_session_id,
        owner_role=owner_role,
        kind=kind,
        owner_loop_id=owner_loop_id,
    )


def discard_unbound_provider_session(
    provider: Provider,
    session_id: str,
    *,
    preexisting_ids: set[str],
    timeout: float = 2.0,
) -> None:
    """Terminate a newly allocated session that failed bind validation."""

    canonical = provider.canonical_session_id(session_id)
    if canonical in preexisting_ids or session_id in preexisting_ids:
        return
    last_error: BaseException | None = None
    terminated = False
    seen: set[str] = set()
    for candidate in (canonical, session_id):
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            provider.terminate_session(candidate, timeout=timeout)
            terminated = True
            break
        except TypeError:
            raise
        except Exception as exc:
            last_error = exc
            continue
    remaining = {
        str(session["session_id"])
        for session in provider.list_active_sessions()
        if isinstance(session, dict) and session.get("session_id")
    }
    still_active = canonical in remaining or session_id in remaining
    if still_active:
        raise ProviderSessionError(
            (
                f"rejected provider session {canonical} is still active after discard"
                + (f": {last_error}" if last_error is not None else "")
            ),
            session_id=canonical,
        )
    if not terminated and last_error is not None:
        raise ProviderSessionError(
            f"failed to discard unbound provider session {canonical}: {last_error}",
            session_id=canonical,
        ) from last_error


def active_provider_session_ids(provider: Provider) -> set[str]:
    return {
        str(session["session_id"])
        for session in provider.list_active_sessions()
        if isinstance(session, dict) and session.get("session_id")
    }


@dataclass(frozen=True)
class SessionTerminationResult:
    """Outcome of terminating a provider session with audit."""

    session_id: str
    ended: bool


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


def _primary_session_is_active(provider: Provider, session_id: str) -> bool:
    canonical_session_id = provider.canonical_session_id(session_id)
    active_ids = {
        str(session["session_id"])
        for session in provider.list_active_sessions()
    }
    return canonical_session_id in active_ids or session_id in active_ids


def end_primary_session_with_audit(
    append_event: Callable[..., None],
    provider: Provider,
    *,
    role: str,
    phase: str,
    session_id: str,
    **fields: Any,
) -> SessionTerminationResult:
    """Terminate a primary session and record ``{role}_session_ended``.

    Idempotent when the session is already absent from the provider registry.
    """

    if role not in _PRIMARY_ROLES:
        raise ValueError(f"unsupported primary session role: {role}")
    if not _primary_session_is_active(provider, session_id):
        return SessionTerminationResult(
            provider.canonical_session_id(session_id),
            ended=True,
        )
    canonical_session_id = _require_owned_provider_session(
        provider,
        session_id,
        role=role,
        kind="primary",
    )

    model_fields = _session_model_fields(provider, canonical_session_id)

    teardown_error: str | None = None
    try:
        provider.terminate_session(
            canonical_session_id,
            timeout=DEFAULT_PROVIDER_LIFECYCLE_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        teardown_error = str(exc)

    if _primary_session_is_active(provider, session_id):
        append_event(
            "provider_session_teardown_failed",
            session_id=canonical_session_id,
            role=role,
            phase=phase,
            message=teardown_error or "session still active after termination",
            **model_fields,
            **fields,
        )
        return SessionTerminationResult(canonical_session_id, ended=False)

    append_event(
        f"{role}_session_ended",
        session_id=canonical_session_id,
        role=role,
        phase=phase,
        **model_fields,
        **fields,
    )
    return SessionTerminationResult(canonical_session_id, ended=True)


def end_reviewer_session_with_audit(
    append_event: Callable[..., None],
    provider: Provider,
    *,
    phase: str,
    session_id: str,
    store: RunStore | None = None,
    run_id: str | None = None,
    binding_loop_id: str | None = None,
    expected_provider_session_id: str | None = None,
    **fields: Any,
) -> SessionTerminationResult:
    """Terminate a bounded reviewer session and record reviewer_session_ended.

    Idempotent: when the session is already absent from the provider registry,
    termination and the durable audit event are skipped.
    """

    expected_id = expected_provider_session_id
    owned_loop_id = binding_loop_id or (
        str(fields["loop_id"]) if fields.get("loop_id") else None
    )
    if store is not None and run_id is not None and owned_loop_id is not None:
        loop = ReviewLoop.from_dict(store.load_review(run_id, owned_loop_id))
        binding = loop.reviewer_binding
        expected_id = (
            str(binding.provider_session_id)
            if binding is not None and binding.provider_session_id
            else None
        )
        if expected_id is None:
            raise ProviderSessionError(
                f"reviewer loop {owned_loop_id} has no bound provider session to release",
                session_id=session_id,
            )
    if expected_id is not None:
        requested = provider.canonical_session_id(session_id)
        expected = provider.canonical_session_id(expected_id)
        if requested != expected:
            raise ProviderSessionError(
                (
                    f"refusing to terminate reviewer session {requested}: "
                    f"loop owns {expected}"
                ),
                session_id=requested,
            )

    if not _reviewer_session_is_active(provider, session_id):
        return SessionTerminationResult(
            provider.canonical_session_id(session_id),
            ended=True,
        )
    canonical_session_id = _require_owned_provider_session(
        provider,
        session_id,
        role="reviewer",
        kind="reviewer",
    )

    model_fields = _session_model_fields(provider, canonical_session_id)

    teardown_error: str | None = None
    try:
        provider.terminate_session(
            canonical_session_id,
            timeout=DEFAULT_PROVIDER_LIFECYCLE_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        teardown_error = str(exc)

    if _reviewer_session_is_active(provider, session_id):
        append_event(
            "provider_session_teardown_failed",
            session_id=canonical_session_id,
            role="reviewer",
            phase=phase,
            message=teardown_error or "session still active after termination",
            **model_fields,
            **fields,
        )
        return SessionTerminationResult(canonical_session_id, ended=False)

    append_event(
        "reviewer_session_ended",
        session_id=canonical_session_id,
        role="reviewer",
        phase=phase,
        **model_fields,
        **fields,
    )
    return SessionTerminationResult(canonical_session_id, ended=True)


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
    provider.resume_primary_session(session_id, request, role=role, model=model)
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
    activity: str | None = None,
    context_digest: str | None = None,
    session_provider: Provider | None = None,
) -> dict[str, Any]:
    """Persist a provider session id on the primary binding.

    Transient ``cursor-pending-*`` ids are stored in ``state: starting``; durable
    ids are promoted to ``state: bound`` during provider turn drain and emit
    ``session_provider_id_bound`` lineage events when first persisted.
    """

    resolved = _assert_session_binding_before_persist(
        session_provider,
        store,
        run_id,
        provider_session_id,
        owner_role=role,
        kind="primary",
    )
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    phase = str(run.get("phase") or "")
    existing = get_primary_binding(run, role)
    if (
        existing is not None
        and existing.provider_session_id == resolved
        and existing.state in {"bound", "starting"}
    ):
        return run

    run = dict(run)
    run["revision"] = expected_revision + 1
    run["sessions"] = update_primary_binding(
        dict(run.get("sessions") or {}),
        role=role,
        provider_session_id=resolved,
        provider=provider,
        activity=activity,
        context_digest=context_digest,
    )
    binding = get_primary_binding(run, role)
    events: list[dict[str, Any]] = []
    if (
        binding is not None
        and binding.provider_session_id
        and not is_transient_provider_session_id(binding.provider_session_id)
    ):
        events.append(
            session_provider_id_bound_payload(
                run_id=run_id,
                phase=phase,
                role=role,
                session_instance_id=binding.session_instance_id,
                generation=binding.generation,
                provider_session_id=binding.provider_session_id,
                provider=binding.provider,
                phase_action_id=phase_action_id,
            )
        )
    store.commit(
        run_id,
        CommitSpec(
            run=run,
            run_expected_revision=expected_revision,
            events=events,
        ),
    )
    return store.load_run(run_id)


def _forbidden_replacement_provider_ids(
    store: RunStore,
    run_id: str,
    *,
    role: str,
    generation: int | None,
    loop_id: str | None = None,
) -> set[str]:
    if generation is None:
        return set()
    forbidden: set[str] = set()
    for event in store.load_events(run_id):
        if event.get("type") != SESSION_REPLACEMENT_STARTED:
            continue
        if str(event.get("role") or "") != role:
            continue
        if int(event.get("generation") or 0) != int(generation):
            continue
        if loop_id is not None and str(event.get("loop_id") or "") != str(loop_id):
            continue
        old = event.get("old_provider_session_id")
        if isinstance(old, str) and old.strip():
            forbidden.add(old.strip())
    return forbidden


def _reject_replacement_reuse_of_old_id(
    provider: Provider,
    store: RunStore,
    run_id: str,
    resolved: str,
    *,
    role: str,
    generation: int | None,
    loop_id: str | None = None,
) -> None:
    for forbidden in _forbidden_replacement_provider_ids(
        store,
        run_id,
        role=role,
        generation=generation,
        loop_id=loop_id,
    ):
        if provider.canonical_session_id(forbidden) == provider.canonical_session_id(
            resolved
        ):
            raise ProviderReplacementIdentityError(
                (
                    f"replacement provider session {resolved} canonicalizes to "
                    f"replaced id {forbidden}"
                ),
                session_id=resolved,
            )


def _has_session_provider_id_bound_event(
    store: RunStore,
    run_id: str,
    *,
    role: str,
    provider_session_id: str,
    loop_id: str | None = None,
) -> bool:
    for event in store.load_events(run_id):
        if event.get("type") != SESSION_PROVIDER_ID_BOUND:
            continue
        if str(event.get("role") or "") != role:
            continue
        if str(event.get("provider_session_id") or "") != provider_session_id:
            continue
        if loop_id is not None and str(event.get("loop_id") or "") != str(loop_id):
            continue
        return True
    return False


def _complete_replacement_if_durable(
    store: RunStore,
    run_id: str,
    *,
    role: str,
    generation: int | None,
    provider_session_id: str,
    loop_id: str | None = None,
) -> None:
    if generation is None or is_transient_provider_session_id(provider_session_id):
        return
    started: dict[str, Any] | None = None
    replaced = False
    failed = False
    for event in store.load_events(run_id):
        if str(event.get("role") or "") != role:
            continue
        if int(event.get("generation") or 0) != int(generation):
            continue
        if loop_id is not None and str(event.get("loop_id") or "") != str(loop_id):
            continue
        event_type = str(event.get("type") or "")
        if event_type == SESSION_REPLACEMENT_STARTED:
            started = event
        elif event_type == SESSION_REPLACED:
            replaced = True
        elif event_type == SESSION_REPLACEMENT_FAILED:
            failed = True
    if started is None or replaced or failed:
        return
    run = store.load_run(run_id)
    instance_id = str(started.get("session_instance_id") or "")
    emit_session_replaced(
        store,
        run_id,
        phase=str(started.get("phase") or run.get("phase") or ""),
        role=role,
        old_session_instance_id=instance_id,
        new_session_instance_id=instance_id,
        generation=int(generation),
        reason=str(started.get("reason") or ""),
        old_provider_session_id=started.get("old_provider_session_id"),
        new_provider_session_id=provider_session_id,
        phase_action_id=started.get("phase_action_id"),
        loop_id=loop_id,
    )


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
    if is_transient_provider_session_id(resolved):
        return resolved
    _assert_unique_durable_session_owner(
        provider,
        store,
        run_id,
        resolved,
        owner_role=role,
    )
    run = store.load_run(run_id)
    existing = get_primary_binding(run, role)
    _reject_replacement_reuse_of_old_id(
        provider,
        store,
        run_id,
        resolved,
        role=role,
        generation=existing.generation if existing is not None else None,
    )
    current = existing.provider_session_id if existing is not None else None
    generation = existing.generation if existing is not None else None
    if current == resolved:
        _complete_replacement_if_durable(
            store,
            run_id,
            role=role,
            generation=generation,
            provider_session_id=resolved,
        )
        return resolved
    if current and not is_transient_provider_session_id(current) and current != resolved:
        raise ProviderSessionError(
            "primary session id mismatch during resume: "
            f"expected {current!r}, got {resolved!r}",
            session_id=session_id,
        )

    commit_primary_provider_session_binding(
        store,
        run_id,
        role=role,
        provider_session_id=resolved,
        provider="cursor",
        session_provider=provider,
    )
    rebind_primary_session_capability(store, run_id, provider, role=role)
    _complete_replacement_if_durable(
        store,
        run_id,
        role=role,
        generation=generation,
        provider_session_id=resolved,
    )
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
    _assert_unique_durable_session_owner(
        provider,
        store,
        run_id,
        resolved,
        owner_role="reviewer",
        owner_loop_id=loop_id,
    )

    review = dict(store.load_review(run_id, loop_id))
    loop = ReviewLoop.from_dict(review)
    binding = loop.reviewer_binding
    _reject_replacement_reuse_of_old_id(
        provider,
        store,
        run_id,
        resolved,
        role="reviewer",
        generation=binding.generation if binding is not None else None,
        loop_id=loop_id,
    )
    prior_provider_id = binding.provider_session_id if binding is not None else None
    if (
        prior_provider_id == resolved
        and binding is not None
        and binding.state == "bound"
    ):
        if not _has_session_provider_id_bound_event(
            store,
            run_id,
            role="reviewer",
            provider_session_id=resolved,
            loop_id=loop_id,
        ):
            _emit_reviewer_provider_id_bound(store, run_id, loop)
        rebind_reviewer_session_capability(store, run_id, provider, loop_id=loop_id)
        _complete_replacement_if_durable(
            store,
            run_id,
            role="reviewer",
            generation=binding.generation if binding is not None else None,
            provider_session_id=resolved,
            loop_id=loop_id,
        )
        return resolved
    if (
        prior_provider_id
        and not is_transient_provider_session_id(prior_provider_id)
        and not is_transient_provider_session_id(resolved)
        and resolved != prior_provider_id
    ):
        raise ProviderSessionError(
            "reviewer session id mismatch during resume: "
            f"expected {prior_provider_id!r}, got {resolved!r}",
            session_id=session_id,
        )

    updated = loop.with_reviewer_provider_session_id(resolved, provider="cursor")
    commit_reviewer_loop_provider_session(
        store,
        run_id,
        updated,
        expected_revision=review_record_revision(review),
        session_provider=provider,
    )
    rebind_reviewer_session_capability(store, run_id, provider, loop_id=loop_id)
    _complete_replacement_if_durable(
        store,
        run_id,
        role="reviewer",
        generation=binding.generation if binding is not None else None,
        provider_session_id=resolved,
        loop_id=loop_id,
    )
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

    Releases only when a non-``pending`` orchestration decision is persisted.
    Pending loops keep the session registered for follow-up turns.
    """

    from top_down_planning.orchestrator.provider_turns import (
        orchestration_decision_from_store,
    )

    decision = orchestration_decision_from_store(store, run_id, loop_id)
    if decision is not None:
        loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
        end_reviewer_session_with_audit(
            append_event,
            provider,
            phase=phase,
            session_id=provider.canonical_session_id(session_id),
            store=store,
            run_id=run_id,
            binding_loop_id=loop_id,
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
    session_provider: Provider | None = None,
) -> ReviewLoop:
    """Persist reviewer loop binding and emit session_provider_id_bound when durable."""

    binding = loop.reviewer_binding
    if binding is not None and binding.provider_session_id:
        resolved = _assert_session_binding_before_persist(
            session_provider,
            store,
            run_id,
            str(binding.provider_session_id),
            owner_role="reviewer",
            kind="reviewer",
            owner_loop_id=loop.id,
        )
        if resolved != str(binding.provider_session_id):
            loop = loop.with_reviewer_provider_session_id(
                resolved,
                provider=binding.provider or "cursor",
            )

    if expected_revision is None:
        try:
            review_record = store.load_review(run_id, loop.id)
        except RunNotFoundError:
            expected_revision = 0
        else:
            expected_revision = review_record_revision(review_record)
    payload = loop.to_dict()
    payload["revision"] = int(expected_revision) + 1
    events: list[dict[str, Any]] = []
    committed_binding = loop.reviewer_binding
    if (
        committed_binding is not None
        and committed_binding.provider_session_id
        and not is_transient_provider_session_id(committed_binding.provider_session_id)
    ):
        run = store.load_run(run_id)
        events.append(
            session_provider_id_bound_payload(
                run_id=run_id,
                phase=str(run.get("phase") or ""),
                role="reviewer",
                session_instance_id=committed_binding.session_instance_id,
                generation=committed_binding.generation,
                provider_session_id=committed_binding.provider_session_id,
                provider=committed_binding.provider,
                loop_id=loop.id,
                phase_action_id=phase_action_id,
            )
        )
    store.commit(
        run_id,
        CommitSpec(
            reviews=[review_record_for_persistence(payload)],
            review_expected_revisions={loop.id: int(expected_revision)},
            events=events,
        ),
    )
    return ReviewLoop.from_dict(store.load_review(run_id, loop.id))
