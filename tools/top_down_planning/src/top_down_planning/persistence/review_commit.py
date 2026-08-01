"""Review-loop optimistic concurrency helpers."""

from __future__ import annotations

from typing import Any

from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.persistence.interface import RunStore


def review_record_revision(review: dict[str, Any]) -> int:
    return int(review.get("revision") or 0)


def save_review_with_expected_revision(
    store: RunStore,
    run_id: str,
    loop: ReviewLoop | dict[str, Any],
    *,
    expected_revision: int,
) -> int:
    """Persist a review loop with compare-and-swap on its record revision."""

    payload = loop.to_dict() if isinstance(loop, ReviewLoop) else dict(loop)
    next_revision = int(expected_revision) + 1
    payload["revision"] = next_revision
    store.save_review(run_id, payload, expected_revision=int(expected_revision))
    return next_revision


__all__ = [
    "review_record_revision",
    "save_review_with_expected_revision",
]
