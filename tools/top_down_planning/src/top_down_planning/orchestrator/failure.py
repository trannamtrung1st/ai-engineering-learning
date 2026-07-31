"""Operational failure handling for orchestrator runs (proposal §15)."""

from __future__ import annotations

import re
from typing import Any

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


def apply_review_incomplete_run_transition(
    store: RunStore,
    run_id: str,
    *,
    loop_id: str,
    reason: str,
    finding_set_id: str | None = None,
    stage: str | None = None,
) -> dict[str, Any]:
    """Fail the run for incomplete discovery without a quality outcome (AC10 / VR15–16).

    Phase and outcome stay unchanged (outcome remains null). Resume retries the
    same review stage without implying artifact rejection.
    """

    run = store.load_run(run_id)
    phase = run.get("phase")
    outcome = run.get("outcome")
    status = str(run.get("status") or "")
    if status == "completed":
        raise ValueError("cannot apply review_incomplete to a completed run")
    if outcome is not None:
        raise ValueError(
            "review_incomplete is an operational failure and cannot override a "
            "quality outcome"
        )

    if status != "failed":
        expected_revision = int(run["revision"])
        updated = dict(run)
        updated["revision"] = expected_revision + 1
        updated["status"] = "failed"
        store.save_run(run_id, updated, expected_revision)
        run = updated

    event: dict[str, Any] = {
        "type": "review_incomplete",
        "run_id": run_id,
        "loop_id": loop_id,
        "reason": reason,
        "phase": phase,
    }
    if finding_set_id is not None:
        event["finding_set_id"] = finding_set_id
    if stage is not None:
        event["stage"] = stage
    store.append_event(run_id, event)
    return {
        "ok": True,
        "run_id": run_id,
        "status": "failed",
        "phase": phase,
        "outcome": None,
        "loop_id": loop_id,
    }


def run_has_review_incomplete(store: RunStore, run_id: str) -> bool:
    for payload in store.list_reviews(run_id):
        if isinstance(payload.get("review_incomplete"), dict):
            return True
    return False


def restore_run_after_review_incomplete(store: RunStore, run_id: str) -> bool:
    """Set ``status=running`` when resuming a review_incomplete operational failure."""

    try:
        run = store.load_run(run_id)
    except RunNotFoundError:
        return False
    if str(run.get("status") or "") != "failed":
        return False
    if run.get("outcome") is not None:
        return False
    if not run_has_review_incomplete(store, run_id):
        return False

    expected_revision = int(run["revision"])
    updated = dict(run)
    updated["revision"] = expected_revision + 1
    updated["status"] = "running"
    store.save_run(run_id, updated, expected_revision)
    store.append_event(
        run_id,
        {
            "type": "review_incomplete_resume",
            "run_id": run_id,
            "phase": updated.get("phase"),
        },
    )
    return True
