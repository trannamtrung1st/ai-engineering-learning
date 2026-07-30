"""Operational failure handling for orchestrator runs (proposal §15)."""

from __future__ import annotations

import re

from core_tools.persistence import RunNotFoundError
from top_down_planning.persistence.interface import RunStore

_TERMINAL_STATUSES = frozenset({"completed", "failed"})
_MAX_FAILURE_MESSAGE_LENGTH = 500
_PATH_PATTERN = re.compile(r"(?:/[\w.\-]+)+")


def sanitize_operational_error(exc: BaseException) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    message = _PATH_PATTERN.sub("<path>", message)
    if len(message) > _MAX_FAILURE_MESSAGE_LENGTH:
        return message[: _MAX_FAILURE_MESSAGE_LENGTH - 3] + "..."
    return message


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
