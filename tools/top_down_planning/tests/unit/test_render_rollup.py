"""Unit tests for rollup scheduling."""

from __future__ import annotations

from top_down_planning.models import RenderConfig, RenderNodePhase
from top_down_planning.render_scheduler import build_rollup_schedule
from tests.unit.test_render_scheduler import _plan_with_hierarchy


def test_rollup_items_use_rollup_phase():
    plan = _plan_with_hierarchy()
    items, errors = build_rollup_schedule(plan, render_config=RenderConfig())
    assert errors == []
    assert all(item.phase == RenderNodePhase.ROLLUP for item in items)
