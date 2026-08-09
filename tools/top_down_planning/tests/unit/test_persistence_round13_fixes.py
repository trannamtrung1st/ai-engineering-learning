"""Regression tests for Slice 3 round-13 review (TDP-PERSIST-048..052)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core_tools.persistence import PersistenceError, atomic_write_json
from top_down_planning.domain.dispositions import TERMINAL_DISPOSITIONS
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.readiness import resolve_satisfaction
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, mirrored_production_batch, minimal_resolved_config
from tests.unit.test_commit_crash_recovery import _create_run


def _new_run_id(suffix: str) -> str:
    return f"run-20260101T0041{suffix}-0041{suffix}"


def _create_work_plan_run(store: FileRunStore, run_id: str) -> None:
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Root",
                kind="aggregate",
            ),
            "item-work": PlanItem(
                id="item-work",
                parent_id="item-root",
                order_key="0000000001",
                title="Work",
                kind="work",
                planning_status="open",
            ),
        },
    )
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
    )


@pytest.mark.parametrize("disposition", sorted(TERMINAL_DISPOSITIONS))
def test_flat_disposition_string_round_trip_matches_readiness(
    tmp_path: Path,
    disposition: str,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("01")
    _create_work_plan_run(store, run_id)
    plan = store.load_plan_model(run_id)
    production = store.load_production(run_id)
    expected = int(production["revision"])
    production = dict(production)
    production["revision"] = expected + 1
    batch, evidence = mirrored_production_batch(
        item_id="item-work",
        disposition=disposition,
        evidence_id=f"out-{disposition}",
    )
    production["batches"] = [batch]
    production["output_evidence"] = [evidence]
    production["dispositions"] = {"item-work": disposition}

    store.save_production(run_id, production, expected)
    loaded = store.load_production(run_id)
    assert loaded["dispositions"]["item-work"] == disposition
    assert isinstance(loaded["dispositions"]["item-work"], str)

    satisfaction = resolve_satisfaction(plan, "item-work", loaded["dispositions"])
    if disposition == "blocked":
        assert satisfaction.state == "blocked"
    else:
        assert satisfaction.state == "satisfied"


def test_save_production_rejects_object_form_flat_disposition(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("02")
    _create_work_plan_run(store, run_id)
    production = store.load_production(run_id)
    expected = int(production["revision"])
    production = dict(production)
    production["revision"] = expected + 1
    production["dispositions"] = {
        "item-work": {"disposition": "blocked", "evidence": "cannot proceed"},
    }
    before = (store.run_dir(run_id) / "production.json").read_bytes()

    with pytest.raises(PersistenceError, match="must be a terminal disposition string"):
        store.save_production(run_id, production, expected)

    assert (store.run_dir(run_id) / "production.json").read_bytes() == before


def test_blocked_object_flat_disposition_cannot_make_all_items_processed(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("03")
    _create_work_plan_run(store, run_id)
    production = store.load_production(run_id)
    production["dispositions"] = {
        "item-work": {"disposition": "blocked", "evidence": "cannot proceed"},
    }
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="must be a terminal disposition string"):
        store.load_production(run_id)


def test_load_production_rejects_numeric_pending_amendment_id(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("11")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["amendment_requests"] = [
        {
            "id": "amendment-01",
            "status": "pending",
            "evidence": "plan must change",
            "affected_refs": ["item-root"],
        }
    ]
    production["pending_amendment_id"] = 1
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="pending_amendment_id"):
        store.load_production(run_id)


def test_save_production_rejects_ghost_pending_amendment_id(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("12")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    expected = int(production["revision"])
    production = dict(production)
    production["revision"] = expected + 1
    production["pending_amendment_id"] = "amendment-missing"
    before = (store.run_dir(run_id) / "production.json").read_bytes()

    with pytest.raises(PersistenceError, match="pending_amendment_id"):
        store.save_production(run_id, production, expected)

    assert (store.run_dir(run_id) / "production.json").read_bytes() == before


def test_load_production_rejects_pending_request_without_matching_latch(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("13")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["amendment_requests"] = [
        {
            "id": "amendment-01",
            "status": "pending",
            "evidence": "plan must change",
            "affected_refs": ["item-root"],
        }
    ]
    production["pending_amendment_id"] = None
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="pending_amendment_id"):
        store.load_production(run_id)


def test_load_production_accepts_valid_pending_amendment_state(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("14")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["amendment_requests"] = [
        {
            "id": "amendment-01",
            "status": "pending",
            "evidence": "plan must change",
            "affected_refs": ["item-root"],
        }
    ]
    production["pending_amendment_id"] = "amendment-01"
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    loaded = store.load_production(run_id)
    assert loaded["pending_amendment_id"] == "amendment-01"
    assert loaded["amendment_requests"][0]["status"] == "pending"


def test_load_production_rejects_bool_reconciliation_revision(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("21")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["reconciliation_reports"] = [
        {
            "amendment_id": "amendment-01",
            "prior_plan_revision": True,
            "new_plan_revision": 1,
            "unchanged": [],
            "changed": [],
            "removed": [],
            "newly_added": [],
            "evidence_preserved": [],
        }
    ]
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="prior_plan_revision"):
        store.load_production(run_id)


def test_load_production_rejects_empty_completion_claim(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("31")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["completion_claim"] = {}
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="completion_claim"):
        store.load_production(run_id)


def test_load_production_accepts_submit_completion_claim_shape(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("32")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    claim = {
        "goal_assessment": "Output goal is fully met.",
        "goal_met": True,
        "summary": "Done.",
        "plan_revision": 0,
        "output_revision": 0,
        "all_applicable_items_processed": True,
    }
    production["completion_claim"] = claim
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    loaded = store.load_production(run_id)
    assert loaded["completion_claim"] == claim


def test_load_production_accepts_integration_pending_completion_claim(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("33")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    claim = {
        "goal_met": False,
        "status": "integration_pending",
        "goal_assessment": "Child deliveries collected.",
        "submitted_at": "2026-01-01T00:00:00Z",
    }
    production["completion_claim"] = claim
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    loaded = store.load_production(run_id)
    assert loaded["completion_claim"] == claim


def test_load_production_rejects_sub_tdps_active_unit_not_in_units(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("41")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["sub_tdps"] = {
        "version": 2,
        "status": "running",
        "active_unit_id": "missing-unit",
        "package_id": "pkg-01",
        "package_digest": "a" * 64,
        "manifest_path": "execution/manifest.json",
        "units": [
            {
                "id": "item-work",
                "plan_item_id": "item-work",
                "title": "Work",
                "directory": "01-work",
                "ordinal": 1,
                "status": "pending",
                "child_run_id": None,
                "unit_plan_digest": "b" * 64,
                "assigned_subtree_digest": "c" * 64,
                "depends_on": [],
                "notes": [],
            }
        ],
    }
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="active_unit_id"):
        store.load_production(run_id)


def test_load_production_rejects_invalid_batch_evidence_status(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("42")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["batches"] = [
        {
            "id": "batch-01",
            "plan_items": ["item-root"],
            "status": "completed",
            "evidence_status": "garbage",
        }
    ]
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="evidence_status"):
        store.load_production(run_id)
