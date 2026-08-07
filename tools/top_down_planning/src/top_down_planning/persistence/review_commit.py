"""Review-loop optimistic concurrency helpers."""

from __future__ import annotations

from typing import Any

from core_tools.persistence import parse_revision_value

from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.persistence.interface import RunStore


def review_record_revision(review: dict[str, Any]) -> int:
    if "revision" not in review:
        return 0
    return parse_revision_value(review["revision"], "review")


def save_review_with_expected_revision(
    store: RunStore,
    run_id: str,
    loop: ReviewLoop | dict[str, Any],
    *,
    expected_revision: int,
) -> int:
    """Persist a review loop with compare-and-swap on its record revision."""

    payload = loop.to_dict() if isinstance(loop, ReviewLoop) else dict(loop)
    expected = parse_revision_value(expected_revision, "review")
    next_revision = expected + 1
    payload["revision"] = next_revision
    store.save_review(run_id, payload, expected_revision=expected)
    return next_revision


__all__ = [
    "review_record_revision",
    "save_review_with_expected_revision",
]
