"""Tests for Sub-TDP orchestration persistence on parent production."""

from __future__ import annotations

import pytest

from top_down_planning.domain.sub_tdp_units import SubTdpUnit
from top_down_planning.domain.models import Plan
from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID, seed_plan_root_item
from top_down_planning.persistence.path_ids import new_run_id
from top_down_planning.persistence.sub_tdp_state import (
    all_units_completed,
    ensure_sub_tdp_state_matches_units,
    initial_sub_tdp_state,
    load_sub_tdp_state,
    merge_sub_tdp_state_into_production,
    unit_status_from_child_run,
)
from tests.helpers import create_run_kwargs, minimal_resolved_config
from top_down_planning.persistence import FileRunStore


def test_initial_sub_tdp_state_from_units() -> None:
    units = [
        SubTdpUnit(
            plan_item_id="item-a",
            title="A",
            outcome="Outcome A",
            directory="01-a",
            ordinal=1,
        ),
        SubTdpUnit(
            plan_item_id="item-b",
            title="B",
            outcome="Outcome B",
            directory="02-b",
            ordinal=2,
        ),
    ]
    state = initial_sub_tdp_state(units)
    assert state["status"] == "preparing"
    assert len(state["units"]) == 2
    assert state["units"][0]["status"] == "pending"
    assert state["units"][0]["plan_item_id"] == "item-a"


def test_merge_sub_tdp_state_into_production(tmp_path) -> None:
    store = FileRunStore(tmp_path)
    run_id = new_run_id()
    kwargs = create_run_kwargs(tmp_path, resolved_config=minimal_resolved_config())
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Goal.",
        items={PLAN_ROOT_ITEM_ID: seed_plan_root_item()},
    )
    store.create_run(run_id, plan=plan, **kwargs)
    production = store.load_production(run_id)
    units = [
        SubTdpUnit(
            plan_item_id="item-a",
            title="A",
            outcome="Outcome A",
            directory="01-a",
            ordinal=1,
        ),
    ]
    state = initial_sub_tdp_state(units)
    merged = merge_sub_tdp_state_into_production(production, state)
    assert "sub_tdps" in merged
    loaded = load_sub_tdp_state(merged)
    assert loaded is not None
    assert loaded["units"][0]["directory"] == "01-a"


def test_unit_status_from_child_run_maps_paused() -> None:
    assert unit_status_from_child_run({"status": "paused", "phase": "production"}) == "paused"
    assert unit_status_from_child_run({"status": "completed", "phase": "output_validated"}) == "completed"
    assert unit_status_from_child_run({"status": "failed", "phase": "production"}) == "failed"


def test_ensure_sub_tdp_state_matches_units_detects_drift() -> None:
    units = [
        SubTdpUnit(
            plan_item_id="item-a",
            title="A",
            outcome="Outcome A",
            directory="01-a",
            ordinal=1,
        ),
    ]
    state = initial_sub_tdp_state(units)
    stale_state = dict(state)
    stale_state["units"] = [
        {
            "id": "item-b",
            "plan_item_id": "item-b",
            "title": "B",
            "directory": "02-b",
            "status": "pending",
            "child_run_id": None,
            "notes": [],
        }
    ]
    with pytest.raises(ValueError, match="does not match"):
        ensure_sub_tdp_state_matches_units(stale_state, units)


def test_all_units_completed_requires_every_unit() -> None:
    units = [
        SubTdpUnit(
            plan_item_id="item-a",
            title="A",
            outcome="Outcome A",
            directory="01-a",
            ordinal=1,
        ),
        SubTdpUnit(
            plan_item_id="item-b",
            title="B",
            outcome="Outcome B",
            directory="02-b",
            ordinal=2,
        ),
    ]
    state = initial_sub_tdp_state(units)
    assert not all_units_completed(state, units)
    state["units"][0]["status"] = "completed"
    assert not all_units_completed(state, units)
    state["units"][1]["status"] = "completed"
    assert all_units_completed(state, units)
