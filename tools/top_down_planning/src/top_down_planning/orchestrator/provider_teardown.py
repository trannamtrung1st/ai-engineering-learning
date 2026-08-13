"""Provider session teardown with durable cancel audit events."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core_tools.observability import ConsoleEvent
from core_tools.provider import Provider
from core_tools.provider.process_cleanup import is_pid_alive, terminate_pid_tree
from core_tools.provider.process_identity import (
    IdentityInspectState,
    ProcessIdentity,
    TerminateIdentityResult,
    inspect_process_identity,
    process_identities_from_termination_record,
    process_identity_is_live,
    read_process_identity,
    terminate_verified_process_identity,
)

from top_down_planning.observability import session_lifecycle_event
from top_down_planning.orchestrator.agent_process_cleanup import (
    PidRunAgentMatch,
    ReadPidEnviron,
    classify_pid_run_agent,
    default_read_pid_environ,
    kill_orphan_agents,
    scan_orphan_agent_pids,
    scan_orphan_agents,
)
from top_down_planning.orchestrator.errors import ProviderTeardownError
from top_down_planning.persistence.interface import RunStore

AppendEvent = Callable[..., None]
EmitConsole = Callable[[ConsoleEvent], None]

_PRIMARY_ROLES = frozenset({"planner", "producer"})


@dataclass(frozen=True)
class TeardownVerificationResult:
    """Outcome of fallback orphan verification after provider teardown."""

    terminated_pids: tuple[int, ...]
    surviving_pids: tuple[int, ...]


@dataclass(frozen=True)
class RetryTerminateResult:
    """Outcome of retrying termination for one or more PIDs."""

    terminated: tuple[int, ...]
    failed: tuple[int, ...]
    unresolved: tuple[int, ...]
    stale_reconciled: tuple[int, ...]


def _session_model_fields(session: dict[str, str]) -> dict[str, str]:
    model = session.get("model")
    if isinstance(model, str) and model:
        return {"model": model}
    return {}


def _partition_agent_termination_records(
    records: list[dict[str, Any]],
) -> tuple[list[int], list[ProcessIdentity], list[int]]:
    terminated_pids: list[int] = []
    failed_identities: list[ProcessIdentity] = []
    unresolved_pids: list[int] = []
    for record in records:
        pid = record.get("pid")
        if not isinstance(pid, int):
            continue
        reason = str(record.get("reason") or "cancelled")
        if reason == "termination_failed":
            identities = process_identities_from_termination_record(record)
            if identities:
                failed_identities.extend(identities)
            else:
                unresolved_pids.append(pid)
        elif reason == "terminated":
            terminated_pids.append(pid)
    return terminated_pids, failed_identities, unresolved_pids


def _emit_agent_termination_records(
    append_event: AppendEvent,
    *,
    phase: str,
    records: list[dict[str, Any]],
    audit_cancel: bool,
) -> tuple[list[int], list[int]]:
    terminated_pids: list[int] = []
    failed_pids: list[int] = []
    for record in records:
        pid = record.get("pid")
        if not isinstance(pid, int):
            continue
        reason = str(record.get("reason") or "cancelled")
        if reason == "termination_failed":
            failed_pids.append(pid)
            fields: dict[str, Any] = {
                "pid": pid,
                "role": str(record.get("role") or "unknown"),
                "session_id": record.get("session_id"),
                "phase": phase,
                "reason": reason,
            }
            for key in (
                "process_identity",
                "start_time",
                "pgid",
                "member_identities",
                "tree_status",
                "run_id",
            ):
                if key in record and record[key] is not None:
                    fields[key] = record[key]
            append_event("agent_termination_failed", **fields)
            continue
        if reason == "terminated" and audit_cancel:
            append_event(
                "agent_terminated",
                pid=pid,
                role=str(record.get("role") or "unknown"),
                session_id=record.get("session_id"),
                phase=phase,
                reason=reason,
            )
    return terminated_pids, failed_pids


def _classify_retry_identity(identity: ProcessIdentity) -> IdentityInspectState:
    return inspect_process_identity(identity)


def _retry_terminate_provider_identities(
    identities: list[ProcessIdentity],
) -> RetryTerminateResult:
    terminated: list[int] = []
    failed: list[int] = []
    unresolved: list[int] = []
    stale_reconciled: list[int] = []
    for identity in identities:
        state = _classify_retry_identity(identity)
        if state is IdentityInspectState.GONE:
            continue
        if state is IdentityInspectState.UNVERIFIABLE:
            unresolved.append(identity.pid)
            continue
        if state is IdentityInspectState.IDENTITY_MISMATCH:
            stale_reconciled.append(identity.pid)
            continue
        result = terminate_verified_process_identity(identity)
        if result == TerminateIdentityResult.TERMINATED:
            terminated.append(identity.pid)
        elif result == TerminateIdentityResult.FAILED:
            failed.append(identity.pid)
        elif result == TerminateIdentityResult.IDENTITY_MISMATCH:
            stale_reconciled.append(identity.pid)
        elif result == TerminateIdentityResult.ALREADY_GONE:
            continue
    return RetryTerminateResult(
        terminated=tuple(terminated),
        failed=tuple(failed),
        unresolved=tuple(unresolved),
        stale_reconciled=tuple(stale_reconciled),
    )


def _retry_terminate_pids(
    pids: list[int],
    *,
    run_id: str | None = None,
    read_pid_environ: ReadPidEnviron | None = None,
) -> RetryTerminateResult:
    terminated: list[int] = []
    failed: list[int] = []
    unresolved: list[int] = []
    stale_reconciled: list[int] = []
    read_environ = read_pid_environ or default_read_pid_environ
    for pid in pids:
        if not is_pid_alive(pid):
            continue
        if run_id is not None:
            match = classify_pid_run_agent(run_id, pid, read_environ=read_environ)
            if match == PidRunAgentMatch.CONFIRMED_DIFFERENT:
                stale_reconciled.append(pid)
                continue
            if match == PidRunAgentMatch.UNVERIFIABLE:
                unresolved.append(pid)
                continue
            identity = read_process_identity(pid, run_id=run_id)
            if identity is None:
                unresolved.append(pid)
                continue
            result = terminate_verified_process_identity(identity)
            if result == TerminateIdentityResult.TERMINATED:
                terminated.append(pid)
            elif result == TerminateIdentityResult.FAILED:
                failed.append(pid)
            elif result == TerminateIdentityResult.IDENTITY_MISMATCH:
                stale_reconciled.append(pid)
            continue
        if terminate_pid_tree(pid):
            terminated.append(pid)
        else:
            failed.append(pid)
    return RetryTerminateResult(
        terminated=tuple(terminated),
        failed=tuple(failed),
        unresolved=tuple(unresolved),
        stale_reconciled=tuple(stale_reconciled),
    )


def _retry_terminate_identities(
    identities: list[ProcessIdentity],
) -> RetryTerminateResult:
    terminated: list[int] = []
    failed: list[int] = []
    unresolved: list[int] = []
    stale_reconciled: list[int] = []
    for identity in identities:
        state = _classify_retry_identity(identity)
        if state is IdentityInspectState.GONE:
            continue
        if state is IdentityInspectState.UNVERIFIABLE:
            unresolved.append(identity.pid)
            continue
        if state is IdentityInspectState.IDENTITY_MISMATCH:
            stale_reconciled.append(identity.pid)
            continue
        result = terminate_verified_process_identity(identity)
        if result == TerminateIdentityResult.TERMINATED:
            terminated.append(identity.pid)
        elif result == TerminateIdentityResult.FAILED:
            failed.append(identity.pid)
        elif result == TerminateIdentityResult.IDENTITY_MISMATCH:
            stale_reconciled.append(identity.pid)
    return RetryTerminateResult(
        terminated=tuple(terminated),
        failed=tuple(failed),
        unresolved=tuple(unresolved),
        stale_reconciled=tuple(stale_reconciled),
    )


def _session_surviving_pids(
    session: dict[str, str],
    *,
    provider: Provider,
    termination_records: list[dict[str, Any]],
) -> list[int]:
    session_id = str(session.get("session_id") or "")
    if not session_id:
        return []
    canonical_session_id = provider.canonical_session_id(session_id)
    session_ids = {session_id, canonical_session_id}
    pids: set[int] = set()
    for record in termination_records:
        if str(record.get("session_id") or "") not in session_ids:
            continue
        identities = process_identities_from_termination_record(record)
        if not identities:
            continue
        for identity in identities:
            if process_identity_is_live(identity):
                pids.add(identity.pid)
    return sorted(pids)


def _emit_session_ended_events(
    append_event: AppendEvent,
    provider: Provider,
    *,
    phase: str,
    active_sessions: list[dict[str, str]],
    termination_records: list[dict[str, Any]],
) -> None:
    for session in active_sessions:
        role = str(session.get("role") or "")
        session_id = str(session.get("session_id") or "")
        if not session_id:
            continue
        model_fields = _session_model_fields(session)
        canonical_session_id = provider.canonical_session_id(session_id)
        still_active = any(
            str(active.get("session_id") or "") in {session_id, canonical_session_id}
            for active in provider.list_active_sessions()
        )
        session_survivors = _session_surviving_pids(
            session,
            provider=provider,
            termination_records=termination_records,
        )
        if still_active or session_survivors:
            append_event(
                "provider_session_teardown_failed",
                session_id=canonical_session_id,
                role=role,
                phase=phase,
                message=(
                    "session still active after teardown"
                    if still_active
                    else f"surviving agent processes: {session_survivors}"
                ),
                **model_fields,
            )
            continue
        if role in _PRIMARY_ROLES:
            append_event(
                f"{role}_session_ended",
                session_id=canonical_session_id,
                role=role,
                phase=phase,
                **model_fields,
            )
        elif role == "reviewer":
            append_event(
                "reviewer_session_ended",
                session_id=canonical_session_id,
                role="reviewer",
                phase=phase,
                **model_fields,
            )


def teardown_provider_sessions(
    provider: Provider,
    *,
    run_id: str,
    phase: str,
    append_event: AppendEvent,
    emit_console: EmitConsole,
    audit_cancel: bool = False,
    store: RunStore | None = None,
    exclude_pids: frozenset[int] | None = None,
) -> list[int]:
    """End active provider sessions and terminate subprocesses.

    When *audit_cancel* is true, durable ``*_session_ended`` and ``agent_terminated``
    audit events are recorded only after final process verification succeeds.
    """

    active_sessions = provider.list_active_sessions()
    verified_terminated: list[int] = []
    survivors: list[int] = []
    termination_records: list[dict[str, Any]] = []
    deferred_error: BaseException | None = None

    try:
        termination_records = provider.terminate_all_sessions()
        terminated_pids, failed_identities, unresolved_pids = (
            _partition_agent_termination_records(termination_records)
        )
        verified_terminated.extend(terminated_pids)
        _emit_agent_termination_records(
            append_event,
            phase=phase,
            records=termination_records,
            audit_cancel=audit_cancel,
        )

        retried = _retry_terminate_provider_identities(failed_identities)
        verified_terminated.extend(retried.terminated)
        survivors = (
            list(retried.failed)
            + list(retried.unresolved)
            + unresolved_pids
        )
        stale_reconciled = list(retried.stale_reconciled)

        if store is not None:
            orphan_scan = scan_orphan_agents(
                run_id,
                exclude_pids=exclude_pids,
                terminated_pids=sorted(set(verified_terminated)),
            )
            survivors.extend(orphan_scan.unverifiable_pids)
            orphan_retry = _retry_terminate_identities(
                list(orphan_scan.kill_candidates),
            )
            verified_terminated.extend(orphan_retry.terminated)
            stale_reconciled.extend(orphan_retry.stale_reconciled)
            survivors = sorted(
                set(survivors)
                | set(orphan_retry.failed)
                | set(orphan_retry.unresolved)
            )
            remaining_scan = scan_orphan_agents(
                run_id,
                exclude_pids=exclude_pids,
                terminated_pids=sorted(set(verified_terminated)),
            )
            survivors = sorted(
                set(survivors)
                | set(remaining_scan.unverifiable_pids)
                | {identity.pid for identity in remaining_scan.kill_candidates}
            )

        reconcile = getattr(provider, "reconcile_terminated_pids", None)
        reconcile_pids = sorted(
            set(verified_terminated) | set(stale_reconciled),
        )
        if reconcile is not None and reconcile_pids:
            reconcile(reconcile_pids)

        for pid in survivors:
            if is_pid_alive(pid):
                append_event(
                    "agent_orphan_cleanup_failed",
                    pid=pid,
                    run_id=run_id,
                    phase=phase,
                    reason="surviving_after_teardown",
                )

        if audit_cancel:
            _emit_session_ended_events(
                append_event,
                provider,
                phase=phase,
                active_sessions=active_sessions,
                termination_records=termination_records,
            )

        for session in active_sessions:
            session_id = session["session_id"]
            model = session.get("model")
            extra_fields: dict[str, Any] = {}
            if isinstance(model, str):
                extra_fields["model"] = model
            emit_console(
                session_lifecycle_event(
                    category="session:end",
                    role=session["role"],
                    phase=phase,
                    session_id=session_id,
                    run_id=run_id,
                    kind=session.get("kind"),
                    **extra_fields,
                )
            )
    except BaseException as exc:
        deferred_error = exc

    verified_terminated = sorted(set(verified_terminated))
    alive_survivors = tuple(pid for pid in survivors if is_pid_alive(pid))
    remaining_active = provider.list_active_sessions()
    if alive_survivors:
        raise ProviderTeardownError(
            f"provider teardown left surviving agent processes: {list(alive_survivors)}",
            surviving_pids=alive_survivors,
            terminated_pids=tuple(verified_terminated),
        )
    if remaining_active:
        active_ids = [
            str(session.get("session_id") or "")
            for session in remaining_active
            if str(session.get("session_id") or "")
        ]
        raise ProviderTeardownError(
            f"provider teardown left active sessions: {active_ids}",
            surviving_pids=(),
            terminated_pids=tuple(verified_terminated),
        )
    if deferred_error is not None:
        if isinstance(deferred_error, ProviderTeardownError):
            if not deferred_error.terminated_pids:
                raise ProviderTeardownError(
                    str(deferred_error),
                    surviving_pids=deferred_error.surviving_pids,
                    terminated_pids=tuple(verified_terminated),
                ) from deferred_error
            raise deferred_error
        raise ProviderTeardownError(
            str(deferred_error),
            terminated_pids=tuple(verified_terminated),
        ) from deferred_error

    return verified_terminated


def verify_run_agent_survivors(
    store: RunStore,
    run_id: str,
    *,
    terminated_pids: list[int],
    exclude_pids: frozenset[int] | None = None,
    known_surviving_pids: tuple[int, ...] = (),
) -> TeardownVerificationResult:
    """Verify run-associated agents after fallback cleanup."""

    cleanup = kill_orphan_agents(
        store,
        run_id,
        exclude_pids=exclude_pids,
        additional_terminated_pids=terminated_pids,
    )
    verified_terminated = sorted(
        {int(pid) for pid in terminated_pids} | {int(pid) for pid in cleanup.cleaned_pids}
    )
    survivors = sorted(
        {
            int(pid)
            for pid in cleanup.failed_pids
            if is_pid_alive(pid)
        }
        | {
            int(pid)
            for pid in known_surviving_pids
            if is_pid_alive(pid)
        }
    )
    remaining_scan = scan_orphan_agents(
        run_id,
        exclude_pids=exclude_pids,
        terminated_pids=verified_terminated,
    )
    for pid in remaining_scan.unverifiable_pids:
        if is_pid_alive(pid) and pid not in survivors:
            survivors.append(pid)
    for identity in remaining_scan.kill_candidates:
        if is_pid_alive(identity.pid) and identity.pid not in survivors:
            survivors.append(identity.pid)
    return TeardownVerificationResult(
        terminated_pids=tuple(verified_terminated),
        surviving_pids=tuple(sorted(set(survivors))),
    )


__all__ = [
    "RetryTerminateResult",
    "TeardownVerificationResult",
    "teardown_provider_sessions",
    "verify_run_agent_survivors",
]
