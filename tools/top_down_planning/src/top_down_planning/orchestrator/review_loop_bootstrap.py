"""Shared cold-resume bootstrap for mandatory whole review orchestrators."""

from __future__ import annotations

from collections.abc import Callable

from top_down_planning.domain.reviews import (
    ReviewLoop,
    pending_interrupted_owner_revision,
)
from top_down_planning.orchestrator.reviewer_session import reviewer_loop_provider_session_id
from top_down_planning.orchestrator.review_loop_types import MandatoryWholeReviewResult

ResumeInterruptedOwnerRevisionResult = ReviewLoop | MandatoryWholeReviewResult
BootstrapWholeReviewLoopResult = tuple[ReviewLoop, bool] | MandatoryWholeReviewResult


def bootstrap_whole_review_loop(
    loop: ReviewLoop,
    *,
    current_revision: int,
    resume_interrupted_revision: Callable[
        [ReviewLoop], ResumeInterruptedOwnerRevisionResult
    ],
    normalize_loop_for_resume: Callable[[ReviewLoop], tuple[ReviewLoop, bool]],
) -> BootstrapWholeReviewLoopResult:
    """Normalize loop state, then resume an interrupted primary revision.

    Normalize runs first so ``limit_reached`` revival can restore
    ``revision_in_progress`` / ``pending`` before owner-resume detection.
    Owner resume runs when an interrupted owner revision is pending after
    normalize did not already deliver a verification recheck (avoids double
    owner work after ``changes_requested`` cold-resume and after
    ``review_incomplete`` retry). Remaining work is the owner turn, not a
    replay of a consumed ``needs_revision`` / ``changes_requested`` decision.
    When revival set ``pending_revision_cycle_entry``, the driver charges
    exactly one new ``revision_cycles`` before the owner turn.

    ``resume_interrupted_revision`` may return ``MandatoryWholeReviewResult``
    when recovery hits a revision limit; callers must propagate that terminal
    outcome instead of treating it as a loop object.
    """

    loop, reviewer_turn_delivered = normalize_loop_for_resume(loop)
    interrupted_revision_resumed = False
    if not reviewer_turn_delivered and pending_interrupted_owner_revision(
        loop, current_revision=current_revision
    ):
        resume_outcome = resume_interrupted_revision(loop)
        if isinstance(resume_outcome, MandatoryWholeReviewResult):
            return resume_outcome
        loop = resume_outcome
        interrupted_revision_resumed = True

    deliver_on_existing_session = (
        reviewer_loop_provider_session_id(loop) is not None
        and not reviewer_turn_delivered
        and not interrupted_revision_resumed
    )
    return loop, deliver_on_existing_session


__all__ = [
    "BootstrapWholeReviewLoopResult",
    "ResumeInterruptedOwnerRevisionResult",
    "bootstrap_whole_review_loop",
]
