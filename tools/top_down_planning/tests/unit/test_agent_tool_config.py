"""Unit tests for agent tool config helpers."""

from __future__ import annotations

from top_down_planning.agent_tool.config import planning_limits_from_config


def test_planning_limits_read_from_planning_section_only() -> None:
    limits = planning_limits_from_config(
        {
            "planning": {"max_depth": 5, "max_expansion_per_item": 3},
            "limits": {"planning": {"max_expansion_iterations": 20}},
        }
    )
    assert limits.max_depth == 5
    assert limits.max_expansion_per_item == 3


def test_planning_limits_use_domain_defaults_when_missing() -> None:
    limits = planning_limits_from_config({})
    assert limits.max_depth == 4
    assert limits.max_expansion_per_item == 7
