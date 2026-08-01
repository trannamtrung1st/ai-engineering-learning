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
    """Resume an interrupted primary revision, then normalize loop state."""

    interrupted_revision_resumed = False
    if needs_primary_revision_resume(loop, current_revision=current_revision):
        loop = resume_interrupted_revision(loop)
        interrupted_revision_resumed = True

    loop, reviewer_turn_delivered = normalize_loop_for_resume(loop)
    deliver_on_existing_session = (
        reviewer_loop_provider_session_id(loop) is not None
        and not reviewer_turn_delivered
        and not interrupted_revision_resumed
    )
    return loop, deliver_on_existing_session


__all__ = ["bootstrap_whole_review_loop"]
