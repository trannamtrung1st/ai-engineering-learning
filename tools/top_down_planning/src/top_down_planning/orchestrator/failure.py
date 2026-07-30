"""Operational failure handling for orchestrator runs (proposal §15)."""

from __future__ import annotations

from core_tools.persistence import RunNotFoundError
from top_down_planning.persistence.interface import RunStore

_TERMINAL_STATUSES = frozenset({"completed", "failed"})


def mark_run_failed(store: RunStore, run_id: str, *, message: str) -> None:
    """Persist ``status=failed`` for an operational provider/orchestrator crash."""

    try:
        run = store.load_run(run_id)
    except RunNotFoundError:
        return

    if str(run.get("status") or "") in _TERMINAL_STATUSES:
        return

    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["status"] = "failed"
    store.save_run(run_id, run, expected_revision)
    try:
        store.append_event(
            run_id,
            {
                "type": "run_failed",
                "run_id": run_id,
                "message": message,
            },
        )
    except RunNotFoundError:
        return
