"""Shared cold-resume bootstrap for mandatory whole review orchestrators."""

from __future__ import annotations

from collections.abc import Callable

from top_down_planning.domain.reviews import ReviewLoop, needs_primary_revision_resume
from top_down_planning.orchestrator.reviewer_session import reviewer_loop_provider_session_id


def bootstrap_whole_review_loop(
    loop: ReviewLoop,
    *,
    current_revision: int,
    resume_interrupted_revision: Callable[[ReviewLoop], ReviewLoop],
    normalize_loop_for_resume: Callable[[ReviewLoop], tuple[ReviewLoop, bool]],
) -> tuple[ReviewLoop, bool]:
    """Normalize loop state, then resume an interrupted primary revision.

    Normalize runs first so ``limit_reached`` revival can restore
    ``revision_in_progress`` / ``pending`` before owner-resume detection.
    Owner resume runs only for ``revision_in_progress`` after normalize did not
    already deliver a verification recheck (avoids double owner work after
    ``changes_requested`` cold-resume and after ``review_incomplete`` retry).
    """

    loop, reviewer_turn_delivered = normalize_loop_for_resume(loop)
    interrupted_revision_resumed = False
    if (
        not reviewer_turn_delivered
        and loop.lifecycle_status == "revision_in_progress"
        and needs_primary_revision_resume(loop, current_revision=current_revision)
    ):
        loop = resume_interrupted_revision(loop)
        interrupted_revision_resumed = True

    deliver_on_existing_session = (
        reviewer_loop_provider_session_id(loop) is not None
        and not reviewer_turn_delivered
        and not interrupted_revision_resumed
    )
    return loop, deliver_on_existing_session


__all__ = ["bootstrap_whole_review_loop"]
