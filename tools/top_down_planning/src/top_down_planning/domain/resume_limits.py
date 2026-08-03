"""Shared resume limit-consumption helpers (proposal §8)."""

from __future__ import annotations

from typing import Any


def consumed_limits_from_run(run: dict[str, Any]) -> dict[str, int] | None:
    """Derive consumed limit usage from a paused ``limit_exhausted`` stop record.

    Requires ``stop.details.limit`` as a full config path
    (e.g. ``limits.whole_plan_review.max_scope_review_rounds``) and integer
    ``consumed``.
    """

    stop = run.get("stop")
    if not isinstance(stop, dict) or str(stop.get("code") or "") != "limit_exhausted":
        return None
    details = stop.get("details") or {}
    if not isinstance(details, dict):
        return None
    limit_path = str(details.get("limit") or "").strip()
    consumed = details.get("consumed")
    if not limit_path.startswith("limits."):
        return None
    # Reject bool (subclass of int) and non-ints so resume gates stay strict.
    if type(consumed) is not int:
        return None
    return {limit_path: consumed}


__all__ = ["consumed_limits_from_run"]
