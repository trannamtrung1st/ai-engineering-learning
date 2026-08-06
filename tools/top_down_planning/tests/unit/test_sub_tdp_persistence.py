"""Tests for Sub-TDP orchestration persistence on parent production."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.domain.sub_tdp_units import SubTdpUnit
from top_down_planning.domain.models import Plan
from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID, seed_plan_root_item
from top_down_planning.persistence.path_ids import new_run_id
from top_down_planning.package.lineage import accepted_result_digest
from top_down_planning.persistence.sub_tdp_state import (
    all_units_completed,
    ensure_sub_tdp_state_matches_units,
    initial_sub_tdp_state,
    load_sub_tdp_state,
    merge_sub_tdp_state_into_production,
    next_ready_unit_id,
    unit_dependencies_satisfied,
    unit_status_from_child_run,
    UNIT_STATUS_COMPLETED,
)
from tests.helpers import create_run_kwargs, minimal_resolved_config


def _accepted_attestation(unit_id: str = "item-a") -> dict:
    return {
        "schema_version": 1,
        "package_id": "pkg-test",
        "package_digest": "p" * 64,
        "unit_id": unit_id,
        "unit_plan_digest": "u" * 64,
        "assigned_subtree_digest": "s" * 64,
        "child_run_id": f"run-{unit_id}",
        "output_revision": 1,
        "output_digest": "o" * 64,
        "whole_output_review_id": "review-whole-output-1",
        "whole_output_review_digest": "r" * 64,
        "outcome": "accepted",
        "evidence_digest": "e" * 64,
        "output_refs": [],
        "contributions": [],
        "workspace_changes": {},
        "baseline_context_snapshot_digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "baseline_accepted_result_digests": [],
        "final_context_snapshot_digest": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
        "completion_assessment": "done",
    }


def _bind_accepted(unit_record: dict, unit_id: str = "item-a") -> None:
    accepted = _accepted_attestation(unit_id)
    unit_record["accepted_result"] = accepted
    unit_record["accepted_result_digest"] = accepted_result_digest(accepted)
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
    assert (
        unit_status_from_child_run(
            {"status": "completed", "phase": "output_validated", "outcome": "accepted"}
        )
        == "completed"
    )
    assert (
        unit_status_from_child_run(
            {"status": "completed", "phase": "output_validated", "outcome": "rejected"}
        )
        == "failed"
    )
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
    _bind_accepted(state["units"][0], "item-a")
    assert not all_units_completed(state, units)
    state["units"][1]["status"] = "completed"
    assert not all_units_completed(state, units)
    _bind_accepted(state["units"][1], "item-b")
    assert all_units_completed(state, units)


def test_unit_dependencies_satisfied_requires_completed_prerequisites() -> None:
    from top_down_planning.package.loader import LoadedUnit
    from top_down_planning.domain.models import Plan
    from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID, seed_plan_root_item

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
    plan = Plan(
        id="plan-test",
        revision=0,
        output_goal="Goal.",
        items={PLAN_ROOT_ITEM_ID: seed_plan_root_item()},
    )
    package_units = {
        "item-a": LoadedUnit(
            unit_id="item-a",
            ordinal=1,
            title="A",
            plan_file=Path("units/01-a/plan.json"),
            plan_digest="d1",
            assigned_root_item_id="item-a",
            assigned_item_ids=["item-a"],
            assigned_subtree_digest="s1",
            depends_on=[],
            plan=plan,
        ),
        "item-b": LoadedUnit(
            unit_id="item-b",
            ordinal=2,
            title="B",
            plan_file=Path("units/02-b/plan.json"),
            plan_digest="d2",
            assigned_root_item_id="item-b",
            assigned_item_ids=["item-b"],
            assigned_subtree_digest="s2",
            depends_on=["item-a"],
            plan=plan,
        ),
    }
    assert unit_dependencies_satisfied(state, package_units, "item-a")
    assert not unit_dependencies_satisfied(state, package_units, "item-b")
    assert next_ready_unit_id(state, package_units) == "item-a"
    state["units"][0]["status"] = UNIT_STATUS_COMPLETED
    assert not unit_dependencies_satisfied(state, package_units, "item-b")
    _bind_accepted(state["units"][0], "item-a")
    assert unit_dependencies_satisfied(state, package_units, "item-b")
    assert next_ready_unit_id(state, package_units) == "item-b"
