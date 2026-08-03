"""Persist run lifecycle transitions with structured stop records (proposal §4–§5)."""

from __future__ import annotations

import uuid
from typing import Any

from top_down_planning.domain.run_lifecycle import StopRecord
from top_down_planning.orchestrator.capability import revoke_capabilities_for_phase
from top_down_planning.persistence.interface import RunStore


def generate_phase_action_id() -> str:
    return f"action-{uuid.uuid4().hex[:12]}"


def pause_run(
    store: RunStore,
    run_id: str,
    *,
    stop: StopRecord,
    revoke_phase: str | None = None,
    event_type: str = "run_paused",
    **event_fields: Any,
) -> dict[str, Any]:
    run = store.load_run(run_id)
    if revoke_phase is not None:
        revoke_capabilities_for_phase(store, run_id, revoke_phase)

    expected_revision = int(run["revision"])
    updated = dict(run)
    updated["revision"] = expected_revision + 1
    updated["status"] = "paused"
    updated["outcome"] = None
    updated["stop"] = stop.to_dict()
    store.save_run(run_id, updated, expected_revision)
    store.append_event(
        run_id,
        {
            "type": event_type,
            "run_id": run_id,
            "stop": stop.to_dict(),
            **event_fields,
        },
    )
    return store.load_run(run_id)


def fail_run(
    store: RunStore,
    run_id: str,
    *,
    stop: StopRecord,
    revoke_phase: str | None = None,
    **event_fields: Any,
) -> dict[str, Any]:
    run = store.load_run(run_id)
    if str(run.get("status") or "") in {"completed", "failed"}:
        return run

    if revoke_phase is not None:
        revoke_capabilities_for_phase(store, run_id, revoke_phase)

    expected_revision = int(run["revision"])
    updated = dict(run)
    updated["revision"] = expected_revision + 1
    updated["status"] = "failed"
    updated["outcome"] = None
    updated["stop"] = stop.to_dict()
    store.save_run(run_id, updated, expected_revision)
    store.append_event(
        run_id,
        {
            "type": "run_failed",
            "run_id": run_id,
            "stop": stop.to_dict(),
            **event_fields,
        },
    )
    return store.load_run(run_id)


def complete_run_with_outcome(
    store: RunStore,
    run_id: str,
    outcome: str,
    *,
    revoke_phase: str | None = None,
    event_type: str = "run_completed",
    **event_fields: Any,
) -> dict[str, Any]:
    run = store.load_run(run_id)
    if revoke_phase is not None:
        revoke_capabilities_for_phase(store, run_id, revoke_phase)

    expected_revision = int(run["revision"])
    updated = dict(run)
    updated["revision"] = expected_revision + 1
    updated["status"] = "completed"
    updated["outcome"] = outcome
    updated["stop"] = None
    store.save_run(run_id, updated, expected_revision)
    store.append_event(
        run_id,
        {
            "type": event_type,
            "run_id": run_id,
            "outcome": outcome,
            **event_fields,
        },
    )
    return store.load_run(run_id)


def pause_for_limit_exhausted(
    store: RunStore,
    run_id: str,
    *,
    phase: str,
    message: str,
    limit: str,
    consumed: int,
    configured: int,
    role: str | None = None,
    revoke_phase: str | None = None,
    **event_fields: Any,
) -> dict[str, Any]:
    limit_path = str(limit).strip()
    if not limit_path.startswith("limits."):
        raise ValueError(
            f"limit_exhausted stop requires a full limits.* path; got {limit!r}"
        )
    details: dict[str, Any] = {
        "limit": limit_path,
        "consumed": consumed,
        "configured": configured,
    }
    loop_id = event_fields.get("loop_id")
    if loop_id is not None and str(loop_id).strip():
        details["loop_id"] = str(loop_id).strip()
    exhausted_budget = event_fields.get("exhausted_budget")
    if exhausted_budget is not None and str(exhausted_budget).strip():
        details["exhausted_budget"] = str(exhausted_budget).strip()
    stop = StopRecord(
        code="limit_exhausted",
        category="operational",
        phase=phase,
        role=role,
        message=message,
        details=details,
    )
    return pause_run(
        store,
        run_id,
        stop=stop,
        revoke_phase=revoke_phase,
        limit=limit_path,
        consumed=consumed,
        configured=configured,
        **event_fields,
    )


__all__ = [
    "complete_run_with_outcome",
    "fail_run",
    "generate_phase_action_id",
    "pause_for_limit_exhausted",
    "pause_run",
]
