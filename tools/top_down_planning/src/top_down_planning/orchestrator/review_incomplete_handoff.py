"""Shared helpers for review_incomplete transitions (§15.5)."""

from __future__ import annotations

from top_down_planning.domain.reviews import (
    ReviewLoop,
    is_mandatory_review_loop,
    loop_revise_at,
    mark_advisory_handoff_incomplete,
    optional_finding_ids_missing_owner_response,
    primary_owner_role_for_review,
)
from top_down_planning.orchestrator.failure import apply_review_incomplete_run_transition
from top_down_planning.persistence.interface import RunStore

_ADVISORY_INCOMPLETE_REASON = (
    "advisory handoff incomplete: optional findings lack owner responses"
)


def advisory_handoff_incomplete_loop(
    loop: ReviewLoop,
) -> tuple[ReviewLoop, str, list[str]]:
    """Mark a loop review_incomplete after an unfinished advisory owner handoff."""

    missing = optional_finding_ids_missing_owner_response(
        loop.findings,
        loop.finding_actions,
        loop_revise_at(loop),
        finding_set_id=loop.finding_set_id,
    )
    marked = mark_advisory_handoff_incomplete(
        loop,
        missing_finding_ids=missing,
        reason=_ADVISORY_INCOMPLETE_REASON,
    )
    return marked, _ADVISORY_INCOMPLETE_REASON, missing


def pause_advisory_handoff_incomplete(
    store: RunStore,
    run_id: str,
    loop: ReviewLoop,
    *,
    pause_run: bool | None = None,
) -> tuple[ReviewLoop, str]:
    """Mark advisory handoff incomplete; pause the run for mandatory loops only."""

    marked, reason, missing = advisory_handoff_incomplete_loop(loop)
    should_pause = (
        pause_run if pause_run is not None else is_mandatory_review_loop(loop)
    )
    if should_pause:
        apply_review_incomplete_run_transition(
            store,
            run_id,
            loop_id=marked.id,
            reason=reason,
            finding_set_id=marked.finding_set_id,
            stage="advisory_handoff",
            missing_owner_action_ids=missing,
            role=primary_owner_role_for_review(marked),
        )
    return marked, reason


__all__ = [
    "advisory_handoff_incomplete_loop",
    "pause_advisory_handoff_incomplete",
]
