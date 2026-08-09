"""Operational failure handling for orchestrator runs (proposal §5, §15)."""

from __future__ import annotations

import re
from typing import Any

from core_tools.persistence import RunNotFoundError
from top_down_planning.domain.run_lifecycle import StopRecord
from top_down_planning.orchestrator.run_transitions import fail_run, pause_run
from top_down_planning.persistence.interface import RunStore

_TERMINAL_STATUSES = frozenset({"completed", "failed"})
_PAUSED_STATUS = "paused"
_MAX_FAILURE_MESSAGE_LENGTH = 500
_PATH_PATTERN = re.compile(r"(?:/[\w.\-]+)+")


def sanitize_operational_error(exc: BaseException) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    message = _PATH_PATTERN.sub("<path>", message)
    if len(message) > _MAX_FAILURE_MESSAGE_LENGTH:
        return message[: _MAX_FAILURE_MESSAGE_LENGTH - 3] + "..."
    return message


def mark_run_failed(
    store: RunStore,
    run_id: str,
    *,
    message: str,
    code: str = "orchestrator_invariant_failure",
) -> None:
    """Persist ``status=failed`` with a structured invariant stop record."""

    try:
        run = store.load_run(run_id)
    except RunNotFoundError:
        return

    if str(run.get("status") or "") in _TERMINAL_STATUSES:
        return

    if str(run.get("status") or "") == _PAUSED_STATUS:
        return

    phase = str(run.get("phase") or "")
    stop = StopRecord(
        code=code,  # type: ignore[arg-type]
        category="invariant",
        phase=phase or "unknown",
        message=message,
    )
    fail_run(store, run_id, stop=stop, message=message)


def apply_review_incomplete_run_transition(
    store: RunStore,
    run_id: str,
    *,
    loop_id: str,
    reason: str,
    finding_set_id: str | None = None,
    stage: str | None = None,
    missing_owner_action_ids: list[str] | None = None,
    role: str | None = None,
) -> dict[str, Any]:
    """Pause the run when mandatory review cannot proceed (discovery or advisory).

    Phase and outcome stay unchanged (outcome remains null). Resume retries the
    same review stage without implying artifact rejection. Focused optional loops
    mark ``review_incomplete`` on the loop only and leave the run ``running``.
    """

    run = store.load_run(run_id)
    phase = str(run.get("phase") or "")
    outcome = run.get("outcome")
    status = str(run.get("status") or "")
    if status in {"completed", "failed"}:
        raise ValueError(f"cannot apply review_incomplete to a {status} run")
    if outcome is not None:
        raise ValueError(
            "review_incomplete is an operational failure and cannot override a "
            "quality outcome"
        )

    details: dict[str, Any] = {"loop_id": loop_id}
    if finding_set_id is not None:
        details["finding_set_id"] = finding_set_id
    if stage is not None:
        details["stage"] = stage
    if missing_owner_action_ids:
        details["missing_owner_action_ids"] = list(missing_owner_action_ids)

    stop = StopRecord(
        code="review_incomplete",
        category="operational",
        phase=phase or "unknown",
        role=role or "reviewer",
        message=reason,
        details=details,
    )
    pause_run(
        store,
        run_id,
        stop=stop,
        loop_id=loop_id,
        reason=reason,
        phase=phase,
    )

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
    if missing_owner_action_ids:
        event["missing_owner_action_ids"] = list(missing_owner_action_ids)
    if role is not None:
        event["role"] = role
    store.append_event(run_id, event)

    run = store.load_run(run_id)
    return {
        "ok": True,
        "run_id": run_id,
        "status": run.get("status"),
        "phase": phase,
        "outcome": None,
        "loop_id": loop_id,
    }


def run_has_review_incomplete(store: RunStore, run_id: str) -> bool:
    run = store.load_run(run_id)
    stop = run.get("stop")
    if isinstance(stop, dict) and stop.get("code") == "review_incomplete":
        return True
    for payload in store.list_reviews(run_id):
        if isinstance(payload.get("review_incomplete"), dict):
            return True
    return False


__all__ = [
    "apply_review_incomplete_run_transition",
    "mark_run_failed",
    "run_has_review_incomplete",
    "sanitize_operational_error",
]
