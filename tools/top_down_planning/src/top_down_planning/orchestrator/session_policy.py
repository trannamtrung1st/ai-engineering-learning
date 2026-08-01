"""Session policy execution hook (Phase 4 wiring point)."""

from __future__ import annotations

from typing import Any, Callable, Protocol

from top_down_planning.persistence.interface import RunStore

SessionPolicyExecutor = Callable[[RunStore, str, dict[str, Any]], None]

_executor: SessionPolicyExecutor | None = None


def register_session_policy_executor(executor: SessionPolicyExecutor | None) -> None:
    """Register a runtime executor for post-resume session policy (item 1.4.3)."""

    global _executor
    _executor = executor


def execute_session_policy_if_registered(
    store: RunStore,
    run_id: str,
    session_policy: dict[str, Any],
) -> bool:
    """Invoke the registered session-policy executor when present."""

    if _executor is None:
        return False
    _executor(store, run_id, session_policy)
    return True


__all__ = [
    "SessionPolicyExecutor",
    "execute_session_policy_if_registered",
    "register_session_policy_executor",
]
