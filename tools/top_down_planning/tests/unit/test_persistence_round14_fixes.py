"""Regression tests for Slice 3 round-14 review (TDP-PERSIST-053..055)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core_tools.persistence import PersistenceError, atomic_write_json
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.production import (
    build_output_traceability,
    completion_claim_asserts_goal_met,
    live_output_evidence_entries,
)
from top_down_planning.package.lineage import (
    accepted_result_digest,
    workspace_changes_from_output_evidence,
)
from top_down_planning.persistence import FileRunStore
from tests.helpers import bind_evidence_snapshot
from tests.support.persistence import _create_run


def _new_run_id(suffix: str) -> str:
    return f"run-20260101T0051{suffix}-0051{suffix}"


def _minimal_evidence(
    *,
    evidence_id: str = "out-1",
    batch_id: str = "batch-01",
) -> dict:
    return {
        "id": evidence_id,
        "type": "artifact",
        "ref": "src/file.py",
        "sha256": "a" * 64,
        "size": 10,
        "media_type": "text/plain",
        "captured_at": "2026-01-01T00:00:00Z",
        "batch_id": batch_id,
    }


def _minimal_batch(
    *,
    batch_id: str = "batch-01",
    plan_items: list[str] | None = None,
    **extra: object,
) -> dict:
    batch = {
        "id": batch_id,
        "status": "started",
        "plan_items": plan_items or ["item-work"],
    }
    batch.update(extra)
    return batch


def _mirrored_completed_batch(
    *,
    batch_id: str = "batch-01",
    plan_items: list[str] | None = None,
    evidence_id: str = "out-1",
    disposition: str = "completed",
    store: FileRunStore | None = None,
    run_id: str | None = None,
) -> tuple[dict, dict]:
    plan_items = plan_items or ["item-work"]
    evidence = _minimal_evidence(evidence_id=evidence_id, batch_id=batch_id)
    nested = {key: value for key, value in evidence.items() if key != "batch_id"}
    batch = {
        "id": batch_id,
        "status": "completed",
        "plan_items": plan_items,
        "result": {
            "outputs": [nested],
            "contributions": [
                {
                    "item_id": plan_items[0],
                    "output_refs": [evidence_id],
                    "summary": "done",
                }
            ],
            "dispositions": {
                item_id: {"disposition": disposition, "evidence": "done"}
                for item_id in plan_items
            },
        },
    }
    if store is not None and run_id is not None:
        evidence, nested = bind_evidence_snapshot(store, run_id, evidence)
        batch["result"]["outputs"] = [nested]
    return batch, evidence


def _minimal_accepted_result(
    *,
    unit_id: str = "item-work",
    child_run_id: str = "child-1",
    unit_plan_digest: str = "b" * 64,
) -> dict:
    ref = "src/out.py"
    return {
        "schema_version": 1,
        "package_id": "pkg-01",
        "package_digest": "a" * 64,
        "unit_id": unit_id,
        "unit_plan_digest": unit_plan_digest,
        "assigned_subtree_digest": "c" * 64,
        "child_run_id": child_run_id,
        "output_revision": 1,
        "output_digest": "d" * 64,
        "whole_output_review_id": "review-01",
        "whole_output_review_digest": "e" * 64,
        "outcome": "accepted",
        "evidence_digest": "f" * 64,
        "output_refs": [
            {
                "id": "out-1",
                "type": "artifact",
                "ref": ref,
                "sha256": "1" * 64,
                "size": 1,
                "media_type": "text/plain",
                "captured_at": "2026-01-01T00:00:00Z",
                "snapshot_ref": "artifacts/test/out.py",
            }
        ],
        "contributions": [],
        "workspace_changes": workspace_changes_from_output_evidence(
            [
                {
                    "id": "out-1",
                    "type": "artifact",
                    "ref": ref,
                    "sha256": "1" * 64,
                    "size": 1,
                    "media_type": "text/plain",
                    "captured_at": "2026-01-01T00:00:00Z",
                    "snapshot_ref": "artifacts/test/out.py",
                }
            ]
        ),
        "baseline_context_snapshot_digest": "2" * 64,
        "final_context_snapshot_digest": "3" * 64,
        "baseline_accepted_result_digests": [],
        "completion_assessment": "done",
    }


def _completed_sub_tdp_unit(**extra: object) -> dict:
    accepted = _minimal_accepted_result()
    unit = {
        "id": "item-work",
        "plan_item_id": "item-work",
        "title": "Work",
        "directory": "01-work",
        "ordinal": 1,
        "status": "completed",
        "child_run_id": "child-1",
        "unit_plan_digest": accepted["unit_plan_digest"],
        "assigned_subtree_digest": accepted["assigned_subtree_digest"],
        "depends_on": [],
        "notes": [],
        "accepted_result": accepted,
        "accepted_result_digest": accepted_result_digest(accepted),
    }
    unit.update(extra)
    return unit


def _version2_sub_tdps_shell(*, units: list[dict], **extra: object) -> dict:
    accepted = _minimal_accepted_result()
    state = {
        "version": 2,
        "status": "running",
        "active_unit_id": None,
        "package_id": accepted["package_id"],
        "package_digest": accepted["package_digest"],
        "manifest_path": "execution/manifest.json",
        "units": units,
    }
    state.update(extra)
    return state


def test_save_production_rejects_duplicate_live_batch_ids(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("01")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    expected = int(production["revision"])
    production = dict(production)
    production["revision"] = expected + 1
    production["batches"] = [
        _minimal_batch(batch_id="batch-01", plan_items=["item-a"]),
        _minimal_batch(batch_id="batch-01", plan_items=["item-b"]),
    ]
    before = (store.run_dir(run_id) / "production.json").read_bytes()

    with pytest.raises(PersistenceError, match="duplicate batch id"):
        store.save_production(run_id, production, expected)

    assert (store.run_dir(run_id) / "production.json").read_bytes() == before


def test_load_production_rejects_invalidated_and_live_batch_share_id(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("02")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["batches"] = [
        {
            "id": "batch-01",
            "status": "started",
            "plan_items": ["item-old"],
            "evidence_status": "invalidated_by_reconciliation",
            "invalidated_item_ids": ["item-old"],
        },
        {
            "id": "batch-01",
            "status": "started",
            "plan_items": ["item-current"],
        },
    ]
    production["output_evidence"] = []
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="duplicate batch id"):
        store.load_production(run_id)


def test_invalidated_batch_evidence_excluded_from_live_output_evidence_entries(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("03")
    _create_run(store, run_id)
    live_batch, live_evidence = _mirrored_completed_batch(
        batch_id="batch-live",
        plan_items=["item-current"],
        evidence_id="out-live",
        store=store,
        run_id=run_id,
    )
    production = store.load_production(run_id)
    production["batches"] = [
        {
            "id": "batch-invalid",
            "status": "completed",
            "plan_items": ["item-old"],
            "evidence_status": "invalidated_by_reconciliation",
            "invalidated_item_ids": ["item-old"],
            "result": {
                "outputs": [_nested_output_from_evidence(
                    _minimal_evidence(evidence_id="out-old", batch_id="batch-invalid")
                )],
                "contributions": [],
                "dispositions": {
                    "item-old": {"disposition": "completed", "evidence": "done"},
                },
            },
        },
        live_batch,
    ]
    production["output_evidence"] = [live_evidence]
    production["dispositions"] = {"item-current": "completed"}
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    loaded = store.load_production(run_id)
    live_ids = {entry["id"] for entry in live_output_evidence_entries(loaded)}
    assert live_ids == {"out-live"}


def _nested_output_from_evidence(evidence: dict) -> dict:
    return {key: value for key, value in evidence.items() if key != "batch_id"}


def test_save_production_rejects_duplicate_output_evidence_ids(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("04")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    expected = int(production["revision"])
    production = dict(production)
    production["revision"] = expected + 1
    batch, evidence = _mirrored_completed_batch(store=store, run_id=run_id)
    production["batches"] = [batch]
    production["output_evidence"] = [evidence, dict(evidence)]
    production["dispositions"] = {"item-work": "completed"}

    with pytest.raises(PersistenceError, match="duplicate output evidence id"):
        store.save_production(run_id, production, expected)


def test_load_production_rejects_output_evidence_missing_batch(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("05")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["batches"] = [_minimal_batch()]
    production["output_evidence"] = [
        _minimal_evidence(evidence_id="out-1", batch_id="missing-batch"),
    ]
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="unknown batch"):
        store.load_production(run_id)


def test_load_production_rejects_output_evidence_with_empty_batch_id(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("06")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["batches"] = [_minimal_batch()]
    evidence = _minimal_evidence()
    evidence["batch_id"] = ""
    production["output_evidence"] = [evidence]
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="batch_id"):
        store.load_production(run_id)


def test_load_production_rejects_contribution_missing_evidence_ref(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("07")
    _create_run(store, run_id)
    batch, evidence = _mirrored_completed_batch(store=store, run_id=run_id)
    batch["result"]["contributions"] = [
        {
            "item_id": "item-work",
            "output_refs": ["missing-evidence"],
            "summary": "",
        }
    ]
    production = store.load_production(run_id)
    production["batches"] = [batch]
    production["output_evidence"] = [evidence]
    production["dispositions"] = {"item-work": "completed"}
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="output_ref"):
        store.load_production(run_id)


def test_duplicate_output_evidence_ids_cannot_load_for_traceability(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("08")
    _create_run(store, run_id)
    batch, evidence = _mirrored_completed_batch(evidence_id="out-dup", store=store, run_id=run_id)
    production = store.load_production(run_id)
    production["batches"] = [batch]
    production["output_evidence"] = [evidence, dict(evidence)]
    production["dispositions"] = {"item-work": "completed"}
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="duplicate output evidence id"):
        store.load_production(run_id)


def test_load_production_rejects_completion_claim_missing_goal_met(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("11")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["completion_claim"] = {
        "goal_assessment": "Output goal is fully met.",
    }
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="goal_met"):
        store.load_production(run_id)


def test_load_production_rejects_full_completion_claim_missing_goal_met(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("12")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["completion_claim"] = {
        "goal_assessment": "Output goal is fully met.",
        "summary": "Done.",
        "plan_revision": 0,
        "output_revision": 0,
        "all_applicable_items_processed": True,
    }
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="goal_met"):
        store.load_production(run_id)


def test_accepted_completion_claim_matches_completion_claim_asserts_goal_met(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("13")
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
    assert completion_claim_asserts_goal_met(loaded["completion_claim"])


def test_load_production_rejects_completed_unit_missing_accepted_result(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("21")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["sub_tdps"] = _version2_sub_tdps_shell(
        units=[
            {
                "id": "item-work",
                "plan_item_id": "item-work",
                "status": "completed",
                "child_run_id": "child-1",
                "unit_plan_digest": "b" * 64,
                "assigned_subtree_digest": "c" * 64,
                "depends_on": [],
                "notes": [],
            }
        ],
    )
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="accepted_result"):
        store.load_production(run_id)


def test_load_production_rejects_completed_unit_digest_mismatch(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("22")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    unit = _completed_sub_tdp_unit()
    unit["accepted_result_digest"] = "0" * 64
    production["sub_tdps"] = _version2_sub_tdps_shell(
        status="completed",
        units=[unit],
    )
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="accepted_result_digest"):
        store.load_production(run_id)


def test_load_production_rejects_completed_orchestration_with_active_unit(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("23")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["sub_tdps"] = _version2_sub_tdps_shell(
        status="completed",
        active_unit_id="item-work",
        units=[_completed_sub_tdp_unit()],
    )
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="active_unit_id"):
        store.load_production(run_id)


def test_load_production_rejects_active_unit_that_is_completed(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("24")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["sub_tdps"] = _version2_sub_tdps_shell(
        active_unit_id="item-work",
        units=[_completed_sub_tdp_unit()],
    )
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="active_unit_id"):
        store.load_production(run_id)


def test_load_production_accepts_valid_completed_sub_tdp_state(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("25")
    _create_run(store, run_id)
    accepted = _minimal_accepted_result()
    unit = _completed_sub_tdp_unit()
    unit["accepted_result"] = accepted
    unit["accepted_result_digest"] = accepted_result_digest(accepted)
    sub_tdps = {
        "version": 2,
        "status": "completed",
        "active_unit_id": None,
        "package_id": accepted["package_id"],
        "package_digest": accepted["package_digest"],
        "manifest_path": "execution/manifest.json",
        "units": [unit],
    }
    production = store.load_production(run_id)
    production["sub_tdps"] = sub_tdps
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    loaded = store.load_production(run_id)
    assert loaded["sub_tdps"]["status"] == "completed"
    assert loaded["sub_tdps"]["units"][0]["accepted_result"]["outcome"] == "accepted"


def test_load_production_rejects_reconciliation_invalidated_item_ids_mismatch(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("31")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["reconciliation_reports"] = [
        {
            "amendment_id": "amendment-01",
            "prior_plan_revision": 0,
            "new_plan_revision": 1,
            "unchanged": [],
            "changed": ["item-changed"],
            "removed": ["item-removed"],
            "newly_added": [],
            "evidence_preserved": [],
            "invalidated_item_ids": ["item-changed"],
        }
    ]
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="invalidated_item_ids"):
        store.load_production(run_id)


def test_load_production_rejects_reconciliation_revision_regression(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("32")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["reconciliation_reports"] = [
        {
            "amendment_id": "amendment-01",
            "prior_plan_revision": 2,
            "new_plan_revision": 1,
            "unchanged": [],
            "changed": [],
            "removed": [],
            "newly_added": [],
            "evidence_preserved": [],
        }
    ]
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="new_plan_revision"):
        store.load_production(run_id)


def test_load_production_rejects_invalidated_batch_without_item_ids(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("33")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["batches"] = [
        {
            "id": "batch-01",
            "status": "completed",
            "plan_items": ["item-work"],
            "evidence_status": "invalidated_by_reconciliation",
            "invalidated_item_ids": [],
        }
    ]
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="invalidated_item_ids"):
        store.load_production(run_id)


def test_load_production_rejects_duplicate_plan_items_in_batch(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("34")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["batches"] = [
        _minimal_batch(plan_items=["item-work", "item-work"]),
    ]
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="duplicate plan_item"):
        store.load_production(run_id)


def test_valid_production_graph_builds_traceability(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("35")
    _create_run(store, run_id)
    plan = Plan(
        id="plan-work",
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
    batch, evidence = _mirrored_completed_batch(store=store, run_id=run_id)
    production = store.load_production(run_id)
    production["batches"] = [batch]
    production["output_evidence"] = [evidence]
    production["dispositions"] = {"item-work": "completed"}
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    loaded = store.load_production(run_id)
    traceability = build_output_traceability(plan, loaded, item_ids=["item-work"])
    assert traceability["evidence_by_item"]["item-work"][0]["ref"] == "src/file.py"
