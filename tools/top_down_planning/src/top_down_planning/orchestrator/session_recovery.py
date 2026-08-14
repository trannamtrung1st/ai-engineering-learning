"""Resume-then-replace orchestration for unrecoverable provider sessions (§12.3)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from core_tools.persistence import PersistenceError, StoreRevisionConflictError
from core_tools.provider import Provider
from core_tools.provider.errors import (
    ProviderError,
    ProviderSessionError,
    ProviderSessionNotFoundError,
    ProviderTurnError,
    ProviderTurnStalledError,
)
from top_down_planning.agent_tool.artifacts import (
    EvidenceIntegrityError,
    validate_production_evidence_integrity,
)
from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.domain.session_lineage import (
    REASON_PROVIDER_SESSION_NOT_FOUND,
    REASON_PROVIDER_TURN_STALLED,
    session_replacement_started_payload,
)
from top_down_planning.persistence.commit import CommitSpec
from top_down_planning.domain.session_bindings import is_transient_provider_session_id
from top_down_planning.domain.run_lifecycle import StopRecord
from top_down_planning.domain.run_ownership import (
    assert_expected_run_revision,
    resolve_run_dir,
    run_ownership,
)
from top_down_planning.orchestrator.agent_context import manifest_agent_context_fields
from top_down_planning.orchestrator.capability import (
    revoke_all_capabilities_for_session_instance,
)
from top_down_planning.orchestrator.errors import (
    ProducerReplacementBlocked,
    ProviderRunError,
    SessionRecoveryPaused,
)
from top_down_planning.orchestrator.run_transitions import fail_run, pause_run
from top_down_planning.orchestrator.session_events import (
    active_provider_session_ids,
    commit_primary_provider_session_binding,
    commit_reviewer_loop_provider_session,
    discard_if_unpublished,
    discard_unbound_provider_session,
    emit_primary_session_started,
    emit_reviewer_session_started,
    terminate_owned_session,
    validate_provider_session_binding,
)
from top_down_planning.orchestrator.session_lineage import (
    emit_session_replaced,
    emit_session_replacement_failed,
    emit_session_resume_failed,
)
from top_down_planning.persistence.review_commit import (
    review_record_revision,
)
from top_down_planning.persistence.session_bindings import (
    bump_primary_binding_generation,
    get_primary_binding,
    review_record_for_persistence,
)
from top_down_planning.workspace import (
    WorkspaceIntegrityError,
    validate_run_workspace_integrity,
)


def is_recoverable_provider_session_loss(exc: BaseException) -> bool:
    """Return True when orchestration may replace the provider session once."""

    return isinstance(exc, (ProviderSessionNotFoundError, ProviderTurnStalledError))


def recovery_reason_for_session_loss(exc: BaseException) -> str:
    """Map a recoverable provider session loss to a session-lineage reason token."""

    if not is_recoverable_provider_session_loss(exc):
        raise TypeError(f"unsupported recoverable session loss: {exc!r}")
    if isinstance(exc, ProviderTurnStalledError):
        return REASON_PROVIDER_TURN_STALLED
    return REASON_PROVIDER_SESSION_NOT_FOUND


def _release_replaced_provider_session(
    provider: Provider,
    provider_session_id: str,
    *,
    role: str,
    kind: str,
    expected_provider_session_id: str,
) -> None:
    """Drop a replaced provider session from the in-memory adapter registry."""

    try:
        canonical_id = terminate_owned_session(
            provider,
            provider_session_id,
            role=role,
            kind=kind,
            expected_provider_session_id=expected_provider_session_id,
        )
    except ProviderSessionError:
        raise
    except Exception as exc:
        canonical_id = provider.canonical_session_id(provider_session_id)
        raise ProviderRunError(
            f"cannot release replaced provider session {canonical_id}: {exc}"
        ) from exc
    active_ids = {
        str(session["session_id"]) for session in provider.list_active_sessions()
    }
    if canonical_id in active_ids or provider_session_id in active_ids:
        raise ProviderRunError(
            f"cannot release replaced provider session {canonical_id}: still active"
        )


@dataclass(frozen=True)
class PrimarySessionRecoverySpec:
    role: Literal["planner", "producer"]
    phase: str
    expected_next_action: str
    append_event: Callable[..., None]
    model: str | None
    build_recovery_manifest: Callable[[str], dict[str, Any]]
    workspace: Path | None = None


@dataclass(frozen=True)
class ReviewerSessionRecoverySpec:
    phase: str
    loop_id: str
    expected_next_action: str
    append_event: Callable[..., None]
    model: str | None
    build_recovery_manifest: Callable[[str], dict[str, Any]]


def _validate_producer_replacement(
    store: RunStore,
    run_id: str,
    *,
    workspace: Path | None = None,
) -> None:
    run = store.load_run(run_id)
    try:
        validate_run_workspace_integrity(run, workspace=workspace)
    except WorkspaceIntegrityError as exc:
        raise ProducerReplacementBlocked(str(exc)) from exc

    production = store.load_production(run_id)
    try:
        validate_production_evidence_integrity(store, run_id, production)
    except EvidenceIntegrityError as exc:
        raise ProducerReplacementBlocked(str(exc)) from exc


def _pause_for_provider_unavailable(
    store: RunStore,
    run_id: str,
    *,
    phase: str,
    role: str,
    message: str,
) -> None:
    stop = StopRecord(
        code="provider_unavailable",
        category="operational",
        phase=phase,
        role=role,
        message=message,
    )
    pause_run(store, run_id, stop=stop, role=role, phase=phase)


def _fail_replacement_persistence(
    store: RunStore,
    run_id: str,
    *,
    phase: str,
    role: str,
    message: str,
) -> None:
    fail_run(
        store,
        run_id,
        stop=StopRecord(
            code="state_integrity_failure",
            category="invariant",
            phase=phase,
            role=role,
            message=message,
        ),
    )


def _discard_replacement_candidate(
    provider: Provider,
    store: RunStore,
    run_id: str,
    session_id: str,
    *,
    preexisting_ids: set[str],
    role: str,
    loop_id: str | None = None,
) -> None:
    discard_if_unpublished(
        provider,
        store,
        run_id,
        session_id,
        preexisting_ids=preexisting_ids,
        role=role,
        loop_id=loop_id,
    )


def _try_discard_replacement_candidate(
    provider: Provider,
    store: RunStore,
    run_id: str,
    session_id: str | None,
    *,
    preexisting_ids: set[str],
    role: str,
    loop_id: str | None = None,
) -> list[BaseException]:
    if session_id is None:
        return []
    try:
        _discard_replacement_candidate(
            provider,
            store,
            run_id,
            session_id,
            preexisting_ids=preexisting_ids,
            role=role,
            loop_id=loop_id,
        )
    except BaseException as exc:
        return [exc]
    return []


def _attach_cleanup_errors(exc: BaseException, cleanup_errors: list[BaseException]) -> None:
    for extra in cleanup_errors:
        try:
            exc.add_note(f"cleanup: {extra!r}")
        except Exception:
            pass


def _run_with_ownership(
    store: RunStore,
    run_id: str,
    operation: Callable[[], str],
) -> str:
    """Run replacement mutations under the run resume lock when a run dir exists."""

    run_dir = resolve_run_dir(store, run_id)
    if run_dir is None:
        return operation()
    with run_ownership(run_id, run_dir=run_dir):
        return operation()


def replace_primary_session(
    store: RunStore,
    run_id: str,
    provider: Provider,
    *,
    role: Literal["planner", "producer"],
    phase: str,
    old_provider_session_id: str,
    phase_action_id: str,
    append_event: Callable[..., None],
    model: str | None,
    manifest: dict[str, Any],
    workspace: Path | None = None,
    recovery_reason: str = REASON_PROVIDER_SESSION_NOT_FOUND,
) -> str:
    """Perform one primary-session replacement with lease/revision CAS."""

    if role == "producer":
        _validate_producer_replacement(store, run_id, workspace=workspace)

    def _replace() -> str:
        run = store.load_run(run_id)
        expected_revision = int(run["revision"])
        binding = get_primary_binding(run, role)
        if binding is None:
            raise ProviderRunError(f"missing {role} session binding for replacement")
        expected_id = binding.provider_session_id
        if not expected_id:
            raise ProviderRunError(f"missing {role} provider session id for replacement")
        if provider.canonical_session_id(old_provider_session_id) != provider.canonical_session_id(
            expected_id
        ):
            raise ProviderSessionError(
                (
                    f"refusing to replace {role} session "
                    f"{provider.canonical_session_id(old_provider_session_id)}: "
                    f"bound id is {provider.canonical_session_id(expected_id)}"
                ),
                session_id=old_provider_session_id,
            )

        emit_session_resume_failed(
            store,
            run_id,
            phase=phase,
            role=role,
            session_instance_id=binding.session_instance_id,
            generation=binding.generation,
            reason=recovery_reason,
            provider_session_id=old_provider_session_id,
            phase_action_id=phase_action_id,
        )

        preexisting = active_provider_session_ids(provider)
        new_session_id: str | None = None
        fail_instance = binding.session_instance_id
        fail_generation = binding.generation
        try:
            activity, context_digest = manifest_agent_context_fields(manifest)
            new_session_id = provider.start_primary_session(role, manifest, model=model)
            resolved = validate_provider_session_binding(
                provider,
                store,
                run_id,
                new_session_id,
                owner_role=role,
                kind="primary",
            )
            _release_replaced_provider_session(
                provider,
                old_provider_session_id,
                role=role,
                kind="primary",
                expected_provider_session_id=expected_id,
            )

            updated_sessions = bump_primary_binding_generation(
                dict(run.get("sessions") or {}),
                role=role,
            )
            new_binding = get_primary_binding({**run, "sessions": updated_sessions}, role)
            if new_binding is None:
                raise ProviderRunError(f"failed to bump {role} session binding generation")

            revoke_all_capabilities_for_session_instance(
                store,
                run_id,
                session_instance_id=binding.session_instance_id,
            )

            run = dict(run)
            run["revision"] = expected_revision + 1
            run["sessions"] = updated_sessions
            fail_instance = new_binding.session_instance_id
            fail_generation = new_binding.generation
            store.commit(
                run_id,
                CommitSpec(
                    run=run,
                    run_expected_revision=expected_revision,
                    events=[
                        session_replacement_started_payload(
                            run_id=run_id,
                            phase=phase,
                            role=role,
                            session_instance_id=new_binding.session_instance_id,
                            generation=new_binding.generation,
                            reason=recovery_reason,
                            old_provider_session_id=old_provider_session_id,
                            phase_action_id=phase_action_id,
                        )
                    ],
                ),
            )
            assert_expected_run_revision(store.load_run(run_id), expected_revision + 1)

            emit_primary_session_started(
                append_event,
                provider,
                role=role,
                phase=phase,
                session_id=resolved,
                replacement=True,
                activity=activity,
                context_digest=context_digest,
            )

            saved_binding = get_primary_binding(
                commit_primary_provider_session_binding(
                    store,
                    run_id,
                    role=role,
                    provider_session_id=resolved,
                    phase_action_id=phase_action_id,
                    activity=activity,
                    context_digest=context_digest,
                    session_provider=provider,
                ),
                role,
            )
            if saved_binding is None:
                raise ProviderRunError(f"failed to bind replacement {role} session")

            if not is_transient_provider_session_id(resolved):
                emit_session_replaced(
                    store,
                    run_id,
                    phase=phase,
                    role=role,
                    old_session_instance_id=binding.session_instance_id,
                    new_session_instance_id=saved_binding.session_instance_id,
                    generation=saved_binding.generation,
                    reason=recovery_reason,
                    old_provider_session_id=old_provider_session_id,
                    new_provider_session_id=resolved,
                    phase_action_id=phase_action_id,
                )
            return resolved
        except SessionRecoveryPaused:
            raise
        except (ProviderError, ProviderTurnError) as exc:
            cleanup = _try_discard_replacement_candidate(
                provider,
                store,
                run_id,
                new_session_id,
                preexisting_ids=preexisting,
                role=role,
            )
            try:
                emit_session_replacement_failed(
                    store,
                    run_id,
                    phase=phase,
                    role=role,
                    session_instance_id=fail_instance,
                    generation=fail_generation,
                    reason="provider_unavailable",
                    provider_session_id=old_provider_session_id,
                    phase_action_id=phase_action_id,
                )
                _pause_for_provider_unavailable(
                    store,
                    run_id,
                    phase=phase,
                    role=role,
                    message=str(exc),
                )
            except BaseException as record_exc:
                _attach_cleanup_errors(record_exc, cleanup)
                raise record_exc from exc
            paused = SessionRecoveryPaused(str(exc))
            _attach_cleanup_errors(paused, cleanup)
            raise paused from exc
        except (PersistenceError, StoreRevisionConflictError, OSError) as exc:
            cleanup = _try_discard_replacement_candidate(
                provider,
                store,
                run_id,
                new_session_id,
                preexisting_ids=preexisting,
                role=role,
            )
            try:
                emit_session_replacement_failed(
                    store,
                    run_id,
                    phase=phase,
                    role=role,
                    session_instance_id=fail_instance,
                    generation=fail_generation,
                    reason="persistence_failure",
                    provider_session_id=old_provider_session_id,
                    phase_action_id=phase_action_id,
                )
                _fail_replacement_persistence(
                    store,
                    run_id,
                    phase=phase,
                    role=role,
                    message=str(exc),
                )
            except BaseException as record_exc:
                _attach_cleanup_errors(record_exc, cleanup)
                raise record_exc from exc
            _attach_cleanup_errors(exc, cleanup)
            raise
        except Exception as exc:
            cleanup = _try_discard_replacement_candidate(
                provider,
                store,
                run_id,
                new_session_id,
                preexisting_ids=preexisting,
                role=role,
            )
            try:
                emit_session_replacement_failed(
                    store,
                    run_id,
                    phase=phase,
                    role=role,
                    session_instance_id=fail_instance,
                    generation=fail_generation,
                    reason="orchestrator_invariant_failure",
                    provider_session_id=old_provider_session_id,
                    phase_action_id=phase_action_id,
                )
                current = store.load_run(run_id)
                if str(current.get("status") or "") == "running":
                    _fail_replacement_persistence(
                        store,
                        run_id,
                        phase=phase,
                        role=role,
                        message=str(exc),
                    )
            except BaseException as record_exc:
                _attach_cleanup_errors(record_exc, cleanup)
                raise record_exc from exc
            _attach_cleanup_errors(exc, cleanup)
            raise

    return _run_with_ownership(store, run_id, _replace)


def replace_reviewer_session(
    store: RunStore,
    run_id: str,
    provider: Provider,
    *,
    loop: ReviewLoop,
    phase: str,
    old_provider_session_id: str,
    phase_action_id: str,
    append_event: Callable[..., None],
    model: str | None,
    manifest: dict[str, Any],
    recovery_reason: str = REASON_PROVIDER_SESSION_NOT_FOUND,
) -> str:
    """Perform one reviewer-session replacement for a review loop."""

    def _replace() -> str:
        run = store.load_run(run_id)
        expected_revision = int(run["revision"])
        assert_expected_run_revision(run, expected_revision)

        review_record = store.load_review(run_id, loop.id)
        review_revision = review_record_revision(review_record)
        current_loop = ReviewLoop.from_dict(review_record)
        binding = current_loop.reviewer_binding
        if binding is None:
            raise ProviderRunError("missing reviewer session binding for replacement")
        expected_id = binding.provider_session_id
        if not expected_id:
            raise ProviderRunError("missing reviewer provider session id for replacement")
        if provider.canonical_session_id(old_provider_session_id) != provider.canonical_session_id(
            expected_id
        ):
            raise ProviderSessionError(
                (
                    "refusing to replace reviewer session "
                    f"{provider.canonical_session_id(old_provider_session_id)}: "
                    f"loop owns {provider.canonical_session_id(expected_id)}"
                ),
                session_id=old_provider_session_id,
            )

        emit_session_resume_failed(
            store,
            run_id,
            phase=phase,
            role="reviewer",
            session_instance_id=binding.session_instance_id,
            generation=binding.generation,
            reason=recovery_reason,
            provider_session_id=old_provider_session_id,
            phase_action_id=phase_action_id,
            loop_id=current_loop.id,
        )

        preexisting = active_provider_session_ids(provider)
        new_session_id: str | None = None
        fail_instance = binding.session_instance_id
        fail_generation = binding.generation
        try:
            activity, context_digest = manifest_agent_context_fields(manifest)
            new_session_id = provider.start_reviewer_session(manifest, model=model)
            resolved = validate_provider_session_binding(
                provider,
                store,
                run_id,
                new_session_id,
                owner_role="reviewer",
                kind="reviewer",
                owner_loop_id=current_loop.id,
            )
            _release_replaced_provider_session(
                provider,
                old_provider_session_id,
                role="reviewer",
                kind="reviewer",
                expected_provider_session_id=expected_id,
            )

            updated_binding = binding.with_next_generation()
            updated_loop = replace(
                current_loop,
                reviewer_binding=updated_binding,
            )
            review_payload = updated_loop.to_dict()
            review_payload["revision"] = int(review_revision) + 1
            fail_instance = updated_binding.session_instance_id
            fail_generation = updated_binding.generation
            store.commit(
                run_id,
                CommitSpec(
                    reviews=[review_record_for_persistence(review_payload)],
                    review_expected_revisions={updated_loop.id: int(review_revision)},
                    events=[
                        session_replacement_started_payload(
                            run_id=run_id,
                            phase=phase,
                            role="reviewer",
                            session_instance_id=updated_binding.session_instance_id,
                            generation=updated_binding.generation,
                            reason=recovery_reason,
                            old_provider_session_id=old_provider_session_id,
                            phase_action_id=phase_action_id,
                            loop_id=loop.id,
                        )
                    ],
                ),
            )
            review_revision += 1

            revoke_all_capabilities_for_session_instance(
                store,
                run_id,
                session_instance_id=binding.session_instance_id,
            )

            emit_reviewer_session_started(
                append_event,
                provider,
                phase=phase,
                session_id=resolved,
                loop=current_loop,
                replacement=True,
                activity=activity,
                context_digest=context_digest,
            )

            committed_loop = commit_reviewer_loop_provider_session(
                store,
                run_id,
                updated_loop.with_reviewer_provider_session_id(resolved),
                phase_action_id=phase_action_id,
                expected_revision=review_revision,
                session_provider=provider,
            )
            committed_binding = committed_loop.reviewer_binding
            if committed_binding is None:
                raise ProviderRunError("failed to bind replacement reviewer session")

            if not is_transient_provider_session_id(resolved):
                emit_session_replaced(
                    store,
                    run_id,
                    phase=phase,
                    role="reviewer",
                    old_session_instance_id=binding.session_instance_id,
                    new_session_instance_id=committed_binding.session_instance_id,
                    generation=committed_binding.generation,
                    reason=recovery_reason,
                    old_provider_session_id=old_provider_session_id,
                    new_provider_session_id=resolved,
                    phase_action_id=phase_action_id,
                    loop_id=loop.id,
                )
            return resolved
        except SessionRecoveryPaused:
            raise
        except (ProviderError, ProviderTurnError) as exc:
            cleanup = _try_discard_replacement_candidate(
                provider,
                store,
                run_id,
                new_session_id,
                preexisting_ids=preexisting,
                role="reviewer",
                loop_id=loop.id,
            )
            try:
                emit_session_replacement_failed(
                    store,
                    run_id,
                    phase=phase,
                    role="reviewer",
                    session_instance_id=fail_instance,
                    generation=fail_generation,
                    reason="provider_unavailable",
                    provider_session_id=old_provider_session_id,
                    phase_action_id=phase_action_id,
                    loop_id=loop.id,
                )
                _pause_for_provider_unavailable(
                    store,
                    run_id,
                    phase=phase,
                    role="reviewer",
                    message=str(exc),
                )
            except BaseException as record_exc:
                _attach_cleanup_errors(record_exc, cleanup)
                raise record_exc from exc
            paused = SessionRecoveryPaused(str(exc))
            _attach_cleanup_errors(paused, cleanup)
            raise paused from exc
        except (PersistenceError, StoreRevisionConflictError, OSError) as exc:
            cleanup = _try_discard_replacement_candidate(
                provider,
                store,
                run_id,
                new_session_id,
                preexisting_ids=preexisting,
                role="reviewer",
                loop_id=loop.id,
            )
            try:
                emit_session_replacement_failed(
                    store,
                    run_id,
                    phase=phase,
                    role="reviewer",
                    session_instance_id=fail_instance,
                    generation=fail_generation,
                    reason="persistence_failure",
                    provider_session_id=old_provider_session_id,
                    phase_action_id=phase_action_id,
                    loop_id=loop.id,
                )
                _fail_replacement_persistence(
                    store,
                    run_id,
                    phase=phase,
                    role="reviewer",
                    message=str(exc),
                )
            except BaseException as record_exc:
                _attach_cleanup_errors(record_exc, cleanup)
                raise record_exc from exc
            _attach_cleanup_errors(exc, cleanup)
            raise
        except Exception as exc:
            cleanup = _try_discard_replacement_candidate(
                provider,
                store,
                run_id,
                new_session_id,
                preexisting_ids=preexisting,
                role="reviewer",
                loop_id=loop.id,
            )
            try:
                emit_session_replacement_failed(
                    store,
                    run_id,
                    phase=phase,
                    role="reviewer",
                    session_instance_id=fail_instance,
                    generation=fail_generation,
                    reason="orchestrator_invariant_failure",
                    provider_session_id=old_provider_session_id,
                    phase_action_id=phase_action_id,
                    loop_id=loop.id,
                )
                current = store.load_run(run_id)
                if str(current.get("status") or "") == "running":
                    _fail_replacement_persistence(
                        store,
                        run_id,
                        phase=phase,
                        role="reviewer",
                        message=str(exc),
                    )
            except BaseException as record_exc:
                _attach_cleanup_errors(record_exc, cleanup)
                raise record_exc from exc
            _attach_cleanup_errors(exc, cleanup)
            raise

    return _run_with_ownership(store, run_id, _replace)


__all__ = [
    "PrimarySessionRecoverySpec",
    "ReviewerSessionRecoverySpec",
    "is_recoverable_provider_session_loss",
    "recovery_reason_for_session_loss",
    "replace_primary_session",
    "replace_reviewer_session",
]
