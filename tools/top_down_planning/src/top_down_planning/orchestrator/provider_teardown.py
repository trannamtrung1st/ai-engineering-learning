"""Provider session teardown with durable cancel audit events."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core_tools.observability import ConsoleEvent
from core_tools.provider import Provider

from top_down_planning.observability import session_lifecycle_event

AppendEvent = Callable[..., None]
EmitConsole = Callable[[ConsoleEvent], None]

_PRIMARY_ROLES = frozenset({"planner", "producer"})


def _session_model_fields(session: dict[str, str]) -> dict[str, str]:
    model = session.get("model")
    if isinstance(model, str) and model:
        return {"model": model}
    return {}


def teardown_provider_sessions(
    provider: Provider,
    *,
    run_id: str,
    phase: str,
    append_event: AppendEvent,
    emit_console: EmitConsole,
    audit_cancel: bool = False,
) -> list[int]:
    """End active provider sessions and terminate subprocesses.

    When *audit_cancel* is true, durable ``*_session_ended`` and ``agent_terminated``
    audit events are recorded around subprocess termination and console teardown.
    """

    active_sessions = provider.list_active_sessions()

    terminated_agents = provider.terminate_all_sessions()
    terminated_pids = sorted(
        {
            int(record["pid"])
            for record in terminated_agents
            if isinstance(record.get("pid"), int)
            and str(record.get("reason") or "") == "terminated"
        }
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

        for record in terminated_agents:
            pid = record.get("pid")
            if not isinstance(pid, int):
                continue
            reason = str(record.get("reason") or "cancelled")
            if reason == "termination_failed":
                append_event(
                    "agent_termination_failed",
                    pid=pid,
                    role=str(record.get("role") or "unknown"),
                    session_id=record.get("session_id"),
                    phase=phase,
                    reason=reason,
                )
                continue
            append_event(
                "agent_terminated",
                pid=pid,
                role=str(record.get("role") or "unknown"),
                session_id=record.get("session_id"),
                phase=phase,
                reason=reason,
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

    return terminated_pids


__all__ = ["teardown_provider_sessions"]
