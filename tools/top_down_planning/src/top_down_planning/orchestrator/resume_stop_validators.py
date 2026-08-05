"""Stop-specific resume apply validators (proposal §10.2)."""

from __future__ import annotations

from typing import Any

from top_down_planning.domain.reviews import ReviewLoop, is_limit_reached_review_loop
from top_down_planning.orchestrator.phases import (
    PLAN_AMENDMENT,
    SUB_TDPS,
    WHOLE_OUTPUT_REVIEW,
    WHOLE_PLAN_REVIEW,
)
from top_down_planning.persistence.interface import RunStore

_PHASE_TO_MANDATORY_REVIEW_TYPE = {
    WHOLE_PLAN_REVIEW: "whole_plan",
    WHOLE_OUTPUT_REVIEW: "whole_output",
}

_REVIEW_GATE_LIMIT_PATH = "limits.review.max_agent_turns_per_gate"

_EXHAUSTED_BUDGET_TO_LIMIT_LEAF = {
    "scope_review": "max_scope_review_rounds",
    "verification_revision": "max_revision_cycles",
}


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


def _validate_review_gate_turn_limit_exhausted(
    store: RunStore,
    run_id: str,
    run: dict[str, Any],
    stop: dict[str, Any],
    *,
    details: dict[str, Any],
) -> ReviewLoop:
    phase = str(run.get("phase") or stop.get("phase") or "")
    loop_id = str(details.get("loop_id") or "").strip()
    if not loop_id:
        raise ResumeStopValidationError(
            f"limit_exhausted stop for {_REVIEW_GATE_LIMIT_PATH!r} requires "
            "details.loop_id"
        )
    try:
        payload = store.load_review(run_id, loop_id)
    except Exception as exc:
        raise ResumeStopValidationError(
            f"limit_exhausted loop {loop_id!r} is missing"
        ) from exc
    loop = ReviewLoop.from_dict(payload)
    mandatory_type = _PHASE_TO_MANDATORY_REVIEW_TYPE.get(phase)
    if mandatory_type is not None:
        if loop.type != mandatory_type:
            raise ResumeStopValidationError(
                f"limit_exhausted loop {loop_id!r} type {loop.type!r} does not match "
                f"phase {phase!r}"
            )
    elif loop.type not in {"focused_plan", "focused_output"}:
        raise ResumeStopValidationError(
            f"limit_exhausted stop for {_REVIEW_GATE_LIMIT_PATH!r} in phase {phase!r} "
            f"requires a focused review loop; got {loop.type!r}"
        )
    if is_limit_reached_review_loop(loop):
        raise ResumeStopValidationError(
            f"review loop {loop_id!r} is limit_reached; gate-turn pause expects an "
            "in-progress review loop"
        )
    loop_consumed = int(loop.gate_agent_turns)
    stop_consumed = details["consumed"]
    if stop_consumed != loop_consumed:
        raise ResumeStopValidationError(
            f"stop consumed {stop_consumed} does not match loop gate_agent_turns "
            f"{loop_consumed}"
        )
    return loop


def validate_limit_exhausted_stop(
    store: RunStore,
    run_id: str,
    run: dict[str, Any],
    stop: dict[str, Any],
) -> ReviewLoop | None:
    """Return a review loop needing normalization on resume when applicable.

    All ``limit_exhausted`` stops require ``stop.details.limit`` as a full
    ``limits.*`` path. Mandatory whole-plan / whole-output budget pauses require
    ``limit_reached`` loops with ``exhausted_budget``. Gate-turn pauses use
    ``limits.review.max_agent_turns_per_gate`` with in-progress loops.
    Returns ``None`` for non-review phase limits (e.g. planning).
    """

    details = stop.get("details") or {}
    if not isinstance(details, dict):
        raise ResumeStopValidationError(
            "limit_exhausted stop requires details.limit as a full limits.* path"
        )
    limit_path = str(details.get("limit") or "").strip()
    if not limit_path.startswith("limits."):
        raise ResumeStopValidationError(
            f"limit_exhausted stop requires details.limit as a full limits.* path; "
            f"got {limit_path!r}"
        )
    if type(details.get("consumed")) is not int:
        raise ResumeStopValidationError(
            "limit_exhausted stop requires integer details.consumed"
        )
    if type(details.get("configured")) is not int:
        raise ResumeStopValidationError(
            "limit_exhausted stop requires integer details.configured"
        )

    if limit_path == _REVIEW_GATE_LIMIT_PATH:
        return _validate_review_gate_turn_limit_exhausted(
            store,
            run_id,
            run,
            stop,
            details=details,
        )

    phase = str(run.get("phase") or stop.get("phase") or "")
    review_type = _PHASE_TO_MANDATORY_REVIEW_TYPE.get(phase)
    if review_type is None:
        return None

    loop_id = str(details.get("loop_id") or "").strip()
    if not loop_id:
        raise ResumeStopValidationError(
            "limit_exhausted stop for mandatory review requires details.loop_id"
        )
    expected_prefix = f"limits.{review_type}_review."
    if not limit_path.startswith(expected_prefix):
        raise ResumeStopValidationError(
            f"limit_exhausted stop limit must start with {expected_prefix!r}; "
            f"got {limit_path!r}"
        )
    try:
        payload = store.load_review(run_id, loop_id)
    except Exception as exc:
        raise ResumeStopValidationError(
            f"limit_exhausted loop {loop_id!r} is missing"
        ) from exc
    loop = ReviewLoop.from_dict(payload)
    if loop.type != review_type:
        raise ResumeStopValidationError(
            f"limit_exhausted loop {loop_id!r} type {loop.type!r} does not match "
            f"phase {phase!r}"
        )
    if not is_limit_reached_review_loop(loop):
        raise ResumeStopValidationError(
            f"review loop {loop_id!r} is not marked limit_reached"
        )
    exhausted = str(loop.exhausted_budget or "").strip()
    if not exhausted:
        raise ResumeStopValidationError(
            f"review loop {loop_id!r} is limit_reached without exhausted_budget"
        )
    stop_exhausted = str(details.get("exhausted_budget") or "").strip()
    if not stop_exhausted:
        raise ResumeStopValidationError(
            "limit_exhausted stop for mandatory review requires details.exhausted_budget"
        )
    if stop_exhausted != exhausted:
        raise ResumeStopValidationError(
            f"stop exhausted_budget {stop_exhausted!r} does not match loop "
            f"{exhausted!r}"
        )
    expected_leaf = _EXHAUSTED_BUDGET_TO_LIMIT_LEAF.get(exhausted)
    if expected_leaf is None:
        raise ResumeStopValidationError(
            f"review loop {loop_id!r} has unknown exhausted_budget {exhausted!r}"
        )
    if not limit_path.endswith(f".{expected_leaf}"):
        raise ResumeStopValidationError(
            f"limit_exhausted stop limit {limit_path!r} does not match "
            f"exhausted_budget {exhausted!r}"
        )
    if exhausted == "scope_review":
        loop_consumed = int(loop.scope_review_rounds)
    else:
        loop_consumed = int(loop.revision_cycles)
    stop_consumed = details["consumed"]
    if stop_consumed != loop_consumed:
        raise ResumeStopValidationError(
            f"stop consumed {stop_consumed} does not match loop "
            f"{exhausted} counter {loop_consumed}"
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


def validate_sub_tdps_awaiting_children_stop(
    store: RunStore,
    run_id: str,
    run: dict[str, Any],
) -> None:
    from top_down_planning.domain.run_kind import (
        RUN_KIND_PARENT_EXECUTION,
        resolve_run_kind,
    )

    if str(run.get("phase") or "") != SUB_TDPS:
        raise ResumeStopValidationError(
            "sub_tdps_awaiting_children resume requires phase sub_tdps"
        )
    try:
        kind = resolve_run_kind(run)
    except ValueError as exc:
        raise ResumeStopValidationError(str(exc)) from exc
    if kind != RUN_KIND_PARENT_EXECUTION:
        raise ResumeStopValidationError(
            "sub_tdps_awaiting_children resume requires parent_execution run_kind"
        )
    production = store.load_production(run_id)
    state = production.get("sub_tdps")
    if not isinstance(state, dict):
        raise ResumeStopValidationError(
            "sub_tdps_awaiting_children resume requires production.sub_tdps state"
        )


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
        return validate_limit_exhausted_stop(store, run_id, run, stop)
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
    if code == "orchestrator_interrupted":
        return None
    if code == "sub_tdps_awaiting_children":
        validate_sub_tdps_awaiting_children_stop(store, run_id, run)
        return None
    raise ResumeStopValidationError(f"unsupported paused stop code for resume apply: {code!r}")


__all__ = [
    "ResumeStopValidationError",
    "validate_amendment_pending_stop",
    "validate_limit_exhausted_stop",
    "validate_review_incomplete_stop",
    "validate_stop_for_resume_apply",
    "validate_sub_tdps_awaiting_children_stop",
]
