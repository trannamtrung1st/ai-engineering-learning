"""Unit tests for agent tool config helpers."""

from __future__ import annotations

from top_down_planning.agent_tool.config import planning_limits_from_config
from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.domain.models import PlanningLimits


def test_planning_limits_read_from_planning_section_only() -> None:
    limits = planning_limits_from_config(
        {
            "planning": {"max_depth": 5, "max_expansion_per_item": 3},
            "limits": {"planning": {"max_items_added": 20}},
        }
    )
    assert limits.max_depth == 5
    assert limits.max_expansion_per_item == 3


def test_planning_limits_use_config_defaults_when_missing() -> None:
    limits = planning_limits_from_config({})
    defaults = DEFAULT_CONFIG["planning"]
    assert limits.max_depth == defaults["max_depth"]
    assert limits.max_expansion_per_item == defaults["max_expansion_per_item"]
    assert limits == PlanningLimits()


def test_planning_limits_match_domain_and_config_defaults() -> None:
    config_defaults = DEFAULT_CONFIG["planning"]
    domain_defaults = PlanningLimits()
    assert domain_defaults.max_depth == config_defaults["max_depth"]
    assert domain_defaults.max_expansion_per_item == config_defaults["max_expansion_per_item"]
