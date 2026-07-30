"""Resolved-config helpers for agent tool responses."""

from __future__ import annotations

from typing import Any

from top_down_planning.domain.models import PlanningLimits


def planning_limits_from_config(config: dict[str, Any]) -> PlanningLimits:
    """Read planning depth/expansion limits from resolved config (proposal §14)."""

    planning = config.get("planning") or {}
    defaults = PlanningLimits()
    return PlanningLimits(
        max_depth=int(planning.get("max_depth", defaults.max_depth)),
        max_expansion_per_item=int(
            planning.get("max_expansion_per_item", defaults.max_expansion_per_item)
        ),
    )
