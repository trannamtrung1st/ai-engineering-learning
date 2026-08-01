"""Tests for shared resume limit consumption helpers."""

from __future__ import annotations

from top_down_planning.domain.resume_limits import consumed_limits_from_run


def test_consumed_limits_from_limit_exhausted_stop_details() -> None:
    run = {
        "stop": {
            "code": "limit_exhausted",
            "details": {
                "limit": "limits.production.max_batches",
                "consumed": 3,
            },
        }
    }
    assert consumed_limits_from_run(run) == {
        "limits.production.max_batches": 3,
    }


def test_consumed_limits_from_planning_counters_when_stop_details_missing() -> None:
    run = {
        "stop": {"code": "limit_exhausted", "details": {}},
        "planning": {"agent_turns": 4, "items_added": 2},
    }
    assert consumed_limits_from_run(run) == {
        "limits.planning.max_agent_turns": 4,
        "limits.planning.max_items_added": 2,
    }


def test_consumed_limits_returns_none_for_non_limit_stop() -> None:
    run = {"stop": {"code": "user_cancelled", "details": {}}}
    assert consumed_limits_from_run(run) is None
