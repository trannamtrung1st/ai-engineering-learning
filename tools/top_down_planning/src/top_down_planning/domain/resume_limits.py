"""Shared resume limit-consumption helpers (proposal §8)."""

from __future__ import annotations

from typing import Any


def consumed_limits_from_run(run: dict[str, Any]) -> dict[str, int] | None:
    """Derive consumed limit usage from a paused ``limit_exhausted`` stop record."""

    stop = run.get("stop")
    if not isinstance(stop, dict) or str(stop.get("code") or "") != "limit_exhausted":
        return None
    details = stop.get("details") or {}
    limit_path = str(details.get("limit") or "").strip()
    consumed = details.get("consumed")
    if limit_path and isinstance(consumed, int):
        return {limit_path: consumed}
    consumed_limits: dict[str, int] = {}
    planning = run.get("planning") or {}
    if isinstance(planning, dict):
        turns = planning.get("agent_turns")
        if isinstance(turns, int):
            consumed_limits["limits.planning.max_agent_turns"] = turns
        items = planning.get("items_added")
        if isinstance(items, int):
            consumed_limits["limits.planning.max_items_added"] = items
    return consumed_limits or None


__all__ = ["consumed_limits_from_run"]
