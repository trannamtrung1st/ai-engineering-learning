"""Amendment state helpers for session recovery manifests."""

from __future__ import annotations

from typing import Any


def pending_amendment_recovery_state(production: dict[str, Any]) -> dict[str, Any] | None:
    """Return pending amendment context when production is awaiting plan amendment."""

    pending_id = production.get("pending_amendment_id")
    if not isinstance(pending_id, str) or not pending_id.strip():
        return None

    state: dict[str, Any] = {"pending_amendment_id": pending_id.strip()}
    request = production.get("pending_amendment_request")
    if isinstance(request, dict):
        state["pending_amendment_request"] = dict(request)
    reconciliation = production.get("reconciliation")
    if isinstance(reconciliation, dict):
        state["reconciliation"] = dict(reconciliation)
    return state


__all__ = ["pending_amendment_recovery_state"]
