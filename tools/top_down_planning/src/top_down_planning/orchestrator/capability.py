"""Orchestrator helpers for issuing session capability tokens."""

from __future__ import annotations

from typing import Any

from top_down_planning.persistence.capabilities import (
    capability_token_value,
    ops_for_session,
)
from top_down_planning.persistence.interface import RunStore


def issue_session_capability(
    store: RunStore,
    run_id: str,
    *,
    role: str,
    phase: str,
    session_id: str | None = None,
    session_kind: str = "primary",
) -> str:
    """Create and return a capability token for a provider session."""

    allowed_ops = ops_for_session(role, phase, session_kind=session_kind)
    _capability_id, record = store.create_capability(
        run_id,
        role=role,
        phase=phase,
        allowed_ops=allowed_ops,
        session_id=session_id,
        session_kind=session_kind,
    )
    return capability_token_value(record)


def bind_provider_capability(provider: Any, token: str | None) -> None:
    """Export a capability token to provider subprocesses when supported."""

    setter = getattr(provider, "set_capability_token", None)
    if setter is not None and token is not None:
        setter(token)


def bind_reviewer_capability(
    store: RunStore,
    run_id: str,
    provider: Any,
    *,
    session_id: str,
    phase: str,
) -> str:
    """Issue and bind a reviewer capability for an existing reviewer session."""

    token = issue_session_capability(
        store,
        run_id,
        role="reviewer",
        phase=phase,
        session_id=session_id,
        session_kind="reviewer",
    )
    bind_provider_capability(provider, token)
    return token
