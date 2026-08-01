"""Stop-specific resume apply validators (proposal §10.2)."""

from __future__ import annotations

from typing import Any

from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.orchestrator.phases import PLAN_AMENDMENT
from top_down_planning.persistence.interface import RunStore


class ResumeStopValidationError(ValueError):
    """Stop-specific resume apply precondition failure."""


def _require_phase_matches_stop(run: dict[str, Any], stop: dict[str, Any]) -> None:
    phase = str(run.get("phase") or "")
    stop_phase = str(stop.get("phase") or "")
    if stop_phase and stop_phase != phase:
        raise ResumeStopValidationError(
            f"stop phase {stop_phase!r} does not match run phase {phase!r}"
        )


def validate_review_incomplete_stop(
    store: RunStore,
    run_id: str,
    stop: dict[str, Any],
) -> ReviewLoop:
    details = stop.get("details") or {}
    loop_id = str(details.get("loop_id") or "").strip()
    if not loop_id:
        raise ResumeStopValidationError("review_incomplete stop requires details.loop_id")
    try:
        payload = store.load_review(run_id, loop_id)
    except Exception as exc:
        raise ResumeStopValidationError(
            f"review_incomplete loop {loop_id!r} is missing"
        ) from exc
    loop = ReviewLoop.from_dict(payload)
    if loop.review_incomplete is None and loop.status != "review_incomplete":
        raise ResumeStopValidationError(
            f"review loop {loop_id!r} is not marked review_incomplete"
        )
    return loop


def validate_amendment_pending_stop(
    run: dict[str, Any],
    production: dict[str, Any],
    stop: dict[str, Any],
) -> None:
    if str(run.get("phase") or "") != PLAN_AMENDMENT:
        raise ResumeStopValidationError(
            "amendment_pending resume requires phase plan_amendment"
        )
    details = stop.get("details") or {}
    pending_id = str(details.get("pending_amendment_id") or "").strip()
    if not pending_id:
        raise ResumeStopValidationError(
            "amendment_pending stop requires details.pending_amendment_id"
        )
    stored_pending = str(production.get("pending_amendment_id") or "").strip()
    if stored_pending != pending_id:
        raise ResumeStopValidationError(
            "pending_amendment_id does not match production state"
        )
    for request in production.get("amendment_requests") or []:
        if not isinstance(request, dict):
            continue
        if str(request.get("id") or "") != pending_id:
            continue
        if str(request.get("status") or "") in {"completed", "cancelled"}:
            raise ResumeStopValidationError("amendment request is not pending")
        return
    raise ResumeStopValidationError("amendment request record missing")


def validate_stop_for_resume_apply(
    store: RunStore,
    run_id: str,
    run: dict[str, Any],
    stop: dict[str, Any],
) -> ReviewLoop | None:
    """Validate paused stop semantics before atomic resume apply or --check."""

    code = str(stop.get("code") or "")
    _require_phase_matches_stop(run, stop)

    if code == "limit_exhausted":
        return None
    if code == "amendment_pending":
        production = store.load_production(run_id)
        validate_amendment_pending_stop(run, production, stop)
        return None
    if code == "review_incomplete":
        return validate_review_incomplete_stop(store, run_id, stop)
    if code == "provider_unavailable":
        return None
    if code == "provider_turn_failed":
        if not str(run.get("phase_action_id") or "").strip():
            raise ResumeStopValidationError(
                "provider_turn_failed resume requires phase_action_id on run record"
            )
        return None
    if code == "user_cancelled":
        return None
    raise ResumeStopValidationError(f"unsupported paused stop code for resume apply: {code!r}")


__all__ = [
    "ResumeStopValidationError",
    "validate_amendment_pending_stop",
    "validate_review_incomplete_stop",
    "validate_stop_for_resume_apply",
]
