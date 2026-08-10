"""Persist run lifecycle transitions with structured stop records (proposal §4–§5)."""

from __future__ import annotations

import uuid
from typing import Any

from top_down_planning.domain.run_lifecycle import StopRecord
from top_down_planning.orchestrator.capability import revoke_capabilities_for_phase
from top_down_planning.persistence.commit import CommitSpec
from top_down_planning.persistence.interface import RunStore

_TERMINAL_STATUSES = frozenset({"completed", "failed"})


def _run_status(run: dict[str, Any]) -> str:
    return str(run.get("status") or "")


def generate_phase_action_id() -> str:
    return f"action-{uuid.uuid4().hex[:12]}"


def pending_capability_revoke_phase(run: dict[str, Any]) -> str | None:
    raw = run.get("pending_capability_revoke_phase")
    if raw is None:
        return None
    phase = str(raw).strip()
    return phase or None


def pending_capability_revoke_all(run: dict[str, Any]) -> bool:
    return bool(run.get("pending_capability_revoke_all"))


def pending_capability_revocation_pending(run: dict[str, Any]) -> bool:
    return pending_capability_revoke_phase(run) is not None or pending_capability_revoke_all(run)


def _active_capability_token_present(store: RunStore, run_id: str) -> bool:
    from top_down_planning.persistence.capabilities import (
        capability_token_file_path,
        read_capability_token_file,
    )

    path = capability_token_file_path(store, run_id)
    return read_capability_token_file(path) is not None


def _run_has_live_capabilities(store: RunStore, run_id: str) -> bool:
    for record in store.list_capabilities(run_id):
        if record.get("revoked") is True:
            continue
        return True
    return False


def _phase_has_live_capabilities(store: RunStore, run_id: str, phase: str) -> bool:
    for record in store.list_capabilities(run_id):
        if record.get("revoked") is True:
            continue
        if str(record.get("phase") or "") == str(phase):
            return True
    return False


def _try_clear_pending_capability_revoke_marker(
    store: RunStore,
    run_id: str,
    expected_phase: str,
) -> dict[str, Any]:
    run = store.load_run(run_id)
    pending = pending_capability_revoke_phase(run)
    if pending is None:
        return run
    if pending != str(expected_phase):
        return run
    if _phase_has_live_capabilities(store, run_id, expected_phase):
        return run

    expected_revision = int(run["revision"])
    updated = dict(run)
    updated["revision"] = expected_revision + 1
    updated.pop("pending_capability_revoke_phase", None)
    try:
        store.commit(
            run_id,
            CommitSpec(run=updated, run_expected_revision=expected_revision),
        )
    except Exception:
        return store.load_run(run_id)
    return store.load_run(run_id)


def _try_clear_pending_capability_revoke_all_marker(
    store: RunStore,
    run_id: str,
) -> dict[str, Any]:
    run = store.load_run(run_id)
    if not pending_capability_revoke_all(run):
        return run
    if _run_has_live_capabilities(store, run_id):
        return run
    if _active_capability_token_present(store, run_id):
        return run

    expected_revision = int(run["revision"])
    updated = dict(run)
    updated["revision"] = expected_revision + 1
    updated.pop("pending_capability_revoke_all", None)
    try:
        store.commit(
            run_id,
            CommitSpec(run=updated, run_expected_revision=expected_revision),
        )
    except Exception:
        return store.load_run(run_id)
    return store.load_run(run_id)


def _attempt_all_capability_revocation(store: RunStore, run_id: str) -> None:
    from top_down_planning.persistence.capabilities import clear_capability_token_file

    try:
        if not _run_has_live_capabilities(store, run_id):
            clear_capability_token_file(store, run_id)
            _try_clear_pending_capability_revoke_all_marker(store, run_id)
            return
        for record in store.list_capabilities(run_id):
            if record.get("revoked") is True:
                continue
            capability_id = str(record.get("id") or "")
            if capability_id:
                store.revoke_capability(run_id, capability_id)
        clear_capability_token_file(store, run_id)
        if not _run_has_live_capabilities(store, run_id) and not _active_capability_token_present(
            store, run_id
        ):
            _try_clear_pending_capability_revoke_all_marker(store, run_id)
    except Exception:
        return


def _attempt_phase_capability_revocation(
    store: RunStore,
    run_id: str,
    revoke_phase: str,
) -> None:
    try:
        if not _phase_has_live_capabilities(store, run_id, revoke_phase):
            _try_clear_pending_capability_revoke_marker(store, run_id, revoke_phase)
            return
        revoke_capabilities_for_phase(store, run_id, revoke_phase)
        if not _phase_has_live_capabilities(store, run_id, revoke_phase):
            _try_clear_pending_capability_revoke_marker(store, run_id, revoke_phase)
    except Exception:
        return


def pending_capability_revoke_unresolved(
    store: RunStore,
    run_id: str,
    run: dict[str, Any] | None = None,
) -> bool:
    """Return True when a pending revoke marker still requires convergence."""

    if run is None:
        run = store.load_run(run_id)
    if pending_capability_revoke_all(run):
        if _run_has_live_capabilities(store, run_id):
            return True
        if _active_capability_token_present(store, run_id):
            return True
        return pending_capability_revoke_all(store.load_run(run_id))
    phase = pending_capability_revoke_phase(run)
    if phase is None:
        return False
    if _phase_has_live_capabilities(store, run_id, phase):
        return True
    return pending_capability_revoke_phase(store.load_run(run_id)) is not None


def reconcile_pending_capability_revocation(
    store: RunStore,
    run_id: str,
    *,
    revoke_phase: str | None = None,
) -> dict[str, Any]:
    """Revoke capabilities for a durable post-transition marker when still live."""

    run = store.load_run(run_id)
    if pending_capability_revoke_all(run):
        _attempt_all_capability_revocation(store, run_id)
        run = store.load_run(run_id)
    phase = revoke_phase or pending_capability_revoke_phase(run)
    if phase is not None:
        _attempt_phase_capability_revocation(store, run_id, phase)
    return store.load_run(run_id)


def pause_run(
    store: RunStore,
    run_id: str,
    *,
    stop: StopRecord,
    revoke_phase: str | None = None,
    event_type: str = "run_paused",
    additional_events: list[dict[str, Any]] | None = None,
    **event_fields: Any,
) -> dict[str, Any]:
    run = store.load_run(run_id)
    status = _run_status(run)
    if status in _TERMINAL_STATUSES:
        return run
    if status == "paused":
        phase = revoke_phase or pending_capability_revoke_phase(run)
        if phase is not None:
            _attempt_phase_capability_revocation(store, run_id, phase)
        return store.load_run(run_id)

    expected_revision = int(run["revision"])
    updated = dict(run)
    updated["revision"] = expected_revision + 1
    updated["status"] = "paused"
    updated["outcome"] = None
    updated["stop"] = stop.to_dict()
    if revoke_phase is not None:
        updated["pending_capability_revoke_phase"] = revoke_phase
    primary_event: dict[str, Any] = {
        "type": event_type,
        "run_id": run_id,
        "stop": stop.to_dict(),
        **event_fields,
    }
    events: list[dict[str, Any]] = [primary_event]
    if additional_events:
        for extra in additional_events:
            payload = dict(extra)
            payload.setdefault("run_id", run_id)
            events.append(payload)
    store.commit(
        run_id,
        CommitSpec(
            run=updated,
            run_expected_revision=expected_revision,
            events=events,
        ),
    )
    if revoke_phase is not None:
        _attempt_phase_capability_revocation(store, run_id, revoke_phase)
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
    status = _run_status(run)
    if status in {"completed", "failed"}:
        if status == "failed":
            phase = revoke_phase or pending_capability_revoke_phase(run)
            if phase is not None:
                _attempt_phase_capability_revocation(store, run_id, phase)
        return store.load_run(run_id)
    if status == "paused":
        return run

    expected_revision = int(run["revision"])
    updated = dict(run)
    updated["revision"] = expected_revision + 1
    updated["status"] = "failed"
    updated["outcome"] = None
    updated["stop"] = stop.to_dict()
    if revoke_phase is not None:
        updated["pending_capability_revoke_phase"] = revoke_phase
    store.commit(
        run_id,
        CommitSpec(
            run=updated,
            run_expected_revision=expected_revision,
            events=[
                {
                    "type": "run_failed",
                    "run_id": run_id,
                    "stop": stop.to_dict(),
                    **event_fields,
                }
            ],
        ),
    )
    if revoke_phase is not None:
        _attempt_phase_capability_revocation(store, run_id, revoke_phase)
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
    status = _run_status(run)
    if status == "completed":
        if run.get("outcome") == outcome:
            phase = revoke_phase or pending_capability_revoke_phase(run)
            if phase is not None:
                _attempt_phase_capability_revocation(store, run_id, phase)
        return store.load_run(run_id)
    if status == "failed":
        return run
    if status == "paused":
        return run

    expected_revision = int(run["revision"])
    updated = dict(run)
    updated["revision"] = expected_revision + 1
    updated["status"] = "completed"
    updated["outcome"] = outcome
    updated["stop"] = None
    if revoke_phase is not None:
        updated["pending_capability_revoke_phase"] = revoke_phase
    store.commit(
        run_id,
        CommitSpec(
            run=updated,
            run_expected_revision=expected_revision,
            events=[
                {
                    "type": event_type,
                    "run_id": run_id,
                    "outcome": outcome,
                    **event_fields,
                }
            ],
        ),
    )
    if revoke_phase is not None:
        _attempt_phase_capability_revocation(store, run_id, revoke_phase)
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
    additional_events: list[dict[str, Any]] | None = None,
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
        additional_events=additional_events,
        **event_fields,
    )


__all__ = [
    "complete_run_with_outcome",
    "fail_run",
    "generate_phase_action_id",
    "pause_for_limit_exhausted",
    "pause_run",
    "pending_capability_revoke_all",
    "pending_capability_revoke_phase",
    "pending_capability_revocation_pending",
    "pending_capability_revoke_unresolved",
    "reconcile_pending_capability_revocation",
]
