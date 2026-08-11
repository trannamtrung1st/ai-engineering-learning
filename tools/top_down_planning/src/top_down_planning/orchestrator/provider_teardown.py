"""Provider session teardown with durable cancel audit events."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core_tools.observability import ConsoleEvent
from core_tools.provider import Provider
from core_tools.provider.process_cleanup import is_pid_alive, terminate_pid_tree

from top_down_planning.observability import session_lifecycle_event
from top_down_planning.orchestrator.agent_process_cleanup import scan_orphan_agent_pids, kill_orphan_agents
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


def _session_model_fields(session: dict[str, str]) -> dict[str, str]:
    model = session.get("model")
    if isinstance(model, str) and model:
        return {"model": model}
    return {}


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
            append_event(
                "agent_termination_failed",
                pid=pid,
                role=str(record.get("role") or "unknown"),
                session_id=record.get("session_id"),
                phase=phase,
                reason=reason,
            )
            continue
        if reason == "terminated":
            terminated_pids.append(pid)
            if audit_cancel:
                append_event(
                    "agent_terminated",
                    pid=pid,
                    role=str(record.get("role") or "unknown"),
                    session_id=record.get("session_id"),
                    phase=phase,
                    reason=reason,
                )
    return terminated_pids, failed_pids


def _retry_terminate_pids(pids: list[int]) -> tuple[list[int], list[int]]:
    terminated: list[int] = []
    failed: list[int] = []
    for pid in pids:
        if not is_pid_alive(pid):
            continue
        if terminate_pid_tree(pid):
            terminated.append(pid)
        else:
            failed.append(pid)
    return terminated, failed


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
    audit events are recorded around subprocess termination and console teardown.
    """

    active_sessions = provider.list_active_sessions()

    terminated_agents = provider.terminate_all_sessions()
    terminated_pids, failed_pids = _emit_agent_termination_records(
        append_event,
        phase=phase,
        records=terminated_agents,
        audit_cancel=audit_cancel,
    )

    if audit_cancel:
        for session in active_sessions:
            role = str(session.get("role") or "")
            session_id = str(session.get("session_id") or "")
            if not session_id:
                continue
            model_fields = _session_model_fields(session)
            canonical_session_id = provider.canonical_session_id(session_id)
            still_active = any(
                str(active.get("session_id") or "")
                in {session_id, canonical_session_id}
                for active in provider.list_active_sessions()
            )
            if still_active:
                append_event(
                    "provider_session_teardown_failed",
                    session_id=canonical_session_id,
                    role=role,
                    phase=phase,
                    message="session still active after terminate_all_sessions",
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

    retried_terminated, retried_failed = _retry_terminate_pids(failed_pids)
    terminated_pids.extend(retried_terminated)
    failed_pids = retried_failed

    verified_terminated = sorted(set(terminated_pids))
    survivors = list(failed_pids)

    if store is not None:
        orphan_pids = scan_orphan_agent_pids(
            run_id,
            exclude_pids=exclude_pids,
            terminated_pids=verified_terminated,
        )
        orphan_retry_terminated, orphan_retry_failed = _retry_terminate_pids(orphan_pids)
        verified_terminated = sorted(set(verified_terminated) | set(orphan_retry_terminated))
        survivors = sorted(set(survivors) | set(orphan_retry_failed))
        remaining = scan_orphan_agent_pids(
            run_id,
            exclude_pids=exclude_pids,
            terminated_pids=verified_terminated,
        )
        survivors = sorted(set(survivors) | set(remaining))

    for pid in survivors:
        if is_pid_alive(pid):
            append_event(
                "agent_orphan_cleanup_failed",
                pid=pid,
                run_id=run_id,
                phase=phase,
                reason="surviving_after_teardown",
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

    alive_survivors = tuple(pid for pid in survivors if is_pid_alive(pid))
    if alive_survivors:
        raise ProviderTeardownError(
            f"provider teardown left surviving agent processes: {list(alive_survivors)}",
            surviving_pids=alive_survivors,
        )

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
    remaining = scan_orphan_agent_pids(
        run_id,
        exclude_pids=exclude_pids,
        terminated_pids=verified_terminated,
    )
    for pid in remaining:
        if is_pid_alive(pid) and pid not in survivors:
            survivors.append(pid)
    return TeardownVerificationResult(
        terminated_pids=tuple(verified_terminated),
        surviving_pids=tuple(sorted(set(survivors))),
    )


__all__ = [
    "TeardownVerificationResult",
    "teardown_provider_sessions",
    "verify_run_agent_survivors",
]
