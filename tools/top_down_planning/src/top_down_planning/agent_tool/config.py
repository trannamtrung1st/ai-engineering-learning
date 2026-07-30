"""Resolved-config helpers for agent tool responses."""

from __future__ import annotations

from typing import Any

from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.domain.models import PlanningLimits

_PLANNING_DEFAULTS = DEFAULT_CONFIG["planning"]


def planning_limits_from_config(config: dict[str, Any]) -> PlanningLimits:
    """Read planning depth/expansion limits from resolved config (proposal §14)."""

    planning = config.get("planning") or {}
    return PlanningLimits(
        max_depth=int(planning.get("max_depth", _PLANNING_DEFAULTS["max_depth"])),
        max_expansion_per_item=int(
            planning.get(
                "max_expansion_per_item",
                _PLANNING_DEFAULTS["max_expansion_per_item"],
            )
        ),
    )
