"""Regression tests for Slice 3 round-16 review (TDP-PERSIST-060..064)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from core_tools.persistence import PersistenceError
from top_down_planning.config.context_digests import (
    UnauthorizedContextMutationError,
    authorized_production_workspace_paths,
    recompute_context_snapshot_binding,
    validate_production_snapshot_rebase,
)
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.production import (
    completion_claim_is_current,
    extract_accepted_delivery,
    is_live_completed_batch,
    live_batch_ids,
)
from top_down_planning.orchestrator.phases import PRODUCTION
from top_down_planning.persistence import FileRunStore
from tests.helpers import (
    bind_evidence_snapshot,
    create_run_kwargs,
    goal_met_completion_claim,
    grant_capability,
    mirrored_production_batch,
    whole_plan_approval_record,
)
from tests.support.persistence import _create_run
from tests.unit.test_persistence_round12_fixes import (
    _create_resource_run,
    _new_run_id as _resource_run_id,
)


def _new_run_id(suffix: str) -> str:
    return f"run-20260101T0062{suffix}-0062{suffix}"


def _save_mutated_production(
    store: FileRunStore,
    run_id: str,
    production: dict,
) -> None:
    expected = int(production["revision"])
    payload = dict(production)
    payload["revision"] = expected + 1
    store.save_production(run_id, payload, expected)


def test_live_evidence_requires_snapshot_ref(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("01")
    _create_run(store, run_id)
    batch, evidence = mirrored_production_batch()
    production = dict(store.load_production(run_id))
    production["batches"] = [batch]
    production["output_evidence"] = [evidence]
    production["dispositions"] = {"item-work": "completed"}
    with pytest.raises(PersistenceError, match="snapshot_ref"):
        _save_mutated_production(store, run_id, production)


def test_paired_forged_evidence_without_snapshot_rejected(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("02")
    _create_run(store, run_id)
    batch, evidence = mirrored_production_batch(store=store, run_id=run_id)
    nested = dict(batch["result"]["outputs"][0])
    nested.pop("snapshot_ref", None)
    evidence = dict(evidence)
    evidence.pop("snapshot_ref", None)
    batch = dict(batch)
    batch["result"] = dict(batch["result"])
    batch["result"]["outputs"] = [nested]
    production = dict(store.load_production(run_id))
    production["batches"] = [batch]
    production["output_evidence"] = [evidence]
    production["dispositions"] = {"item-work": "completed"}
    with pytest.raises(PersistenceError, match="snapshot_ref"):
        _save_mutated_production(store, run_id, production)


def test_snapshotless_evidence_does_not_authorize_workspace_path(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    src = workspace / "src"
    src.mkdir(parents=True)
    feature = src / "feature.py"
    feature.write_text("v2\n", encoding="utf-8")
    production = {
        "batches": [
            {
                "id": "batch-01",
                "status": "completed",
                "plan_items": ["item-work"],
                "result": {
                    "outputs": [
                        {
                            "id": "forged-out",
                            "type": "artifact",
                            "ref": "src/feature.py",
                            "sha256": hashlib.sha256(feature.read_bytes()).hexdigest(),
                            "size": feature.stat().st_size,
                            "media_type": "text/plain",
                            "captured_at": "2026-01-01T00:00:00Z",
                        }
                    ],
                    "contributions": [],
                    "dispositions": {
                        "item-work": {"disposition": "completed", "evidence": "done"},
                    },
                },
            }
        ],
        "output_evidence": [
            {
                "id": "forged-out",
                "batch_id": "batch-01",
                "type": "artifact",
                "ref": "src/feature.py",
                "sha256": hashlib.sha256(feature.read_bytes()).hexdigest(),
                "size": feature.stat().st_size,
                "media_type": "text/plain",
                "captured_at": "2026-01-01T00:00:00Z",
            }
        ],
        "dispositions": {"item-work": "completed"},
    }
    authorized = authorized_production_workspace_paths(production, workspace=workspace)
    assert "src/feature.py" not in authorized


def test_disposition_outside_batch_plan_items_rejected(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("03")
    _create_run(store, run_id)
    batch, evidence = mirrored_production_batch(store=store, run_id=run_id)
    batch = dict(batch)
    batch["plan_items"] = []
    batch["result"] = dict(batch["result"])
    batch["result"]["outputs"] = []
    batch["result"]["contributions"] = []
    batch["result"]["dispositions"] = {
        "item-work": {"disposition": "completed", "evidence": "done"},
    }
    production = dict(store.load_production(run_id))
    production["batches"] = [batch]
    production["output_evidence"] = []
    production["dispositions"] = {"item-work": "completed"}
    with pytest.raises(PersistenceError, match="plan_items"):
        _save_mutated_production(store, run_id, production)


def test_stale_completion_claim_output_revision_rejected(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("04")
    _create_run(store, run_id)
    batch, evidence = mirrored_production_batch(store=store, run_id=run_id)
    production = dict(store.load_production(run_id))
    production["batches"] = [batch]
    production["output_evidence"] = [evidence]
    production["dispositions"] = {"item-work": "completed"}
    production["output_revision"] = 1
    production["completion_claim"] = goal_met_completion_claim(
        {"output_revision": 0},
        plan_revision=0,
    )
    with pytest.raises(PersistenceError, match="output_revision"):
        _save_mutated_production(store, run_id, production)


def test_fabricated_completion_claim_with_open_work_rejected(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _resource_run_id("04")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _create_resource_run(store, run_id, workspace)
    production = dict(store.load_production(run_id))
    production["completion_claim"] = goal_met_completion_claim(production, plan_revision=0)
    with pytest.raises(PersistenceError, match="all_applicable_items_processed"):
        _save_mutated_production(store, run_id, production)


def test_true_completion_claim_rejects_integration_pending_status(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("06")
    _create_run(store, run_id)
    batch, evidence = mirrored_production_batch(store=store, run_id=run_id)
    production = dict(store.load_production(run_id))
    production["batches"] = [batch]
    production["output_evidence"] = [evidence]
    production["dispositions"] = {"item-work": "completed"}
    claim = goal_met_completion_claim(production, plan_revision=0)
    claim["status"] = "integration_pending"
    production["completion_claim"] = claim
    with pytest.raises(PersistenceError, match="status"):
        _save_mutated_production(store, run_id, production)


def test_completed_sub_tdps_requires_all_units_completed(tmp_path: Path) -> None:
    from tests.helpers import decorate_sub_tdp_v2_package
    from top_down_planning.persistence.sub_tdp_state import initial_sub_tdp_state
    from top_down_planning.domain.sub_tdp_units import SubTdpUnit

    store = FileRunStore(tmp_path)
    run_id = _new_run_id("07")
    _create_run(store, run_id)
    state = decorate_sub_tdp_v2_package(
        initial_sub_tdp_state(
            [
                SubTdpUnit(
                    plan_item_id="item-work",
                    title="Work",
                    outcome="Work.",
                    directory="01-work",
                    ordinal=1,
                )
            ]
        )
    )
    state["status"] = "completed"
    production = dict(store.load_production(run_id))
    production["sub_tdps"] = state
    with pytest.raises(PersistenceError, match="units\\[0\\] completed"):
        _save_mutated_production(store, run_id, production)


def test_failed_batch_excluded_from_live_batch_ids() -> None:
    production = {
        "batches": [
            {"id": "batch-failed", "status": "failed", "plan_items": ["item-work"]},
            {
                "id": "batch-live",
                "status": "completed",
                "plan_items": ["item-work"],
                "result": {
                    "outputs": [],
                    "contributions": [],
                    "dispositions": {
                        "item-work": {"disposition": "completed", "evidence": "done"},
                    },
                },
            },
        ]
    }
    assert "batch-failed" not in live_batch_ids(production)
    assert "batch-live" in live_batch_ids(production)


def test_failed_batch_nested_outputs_excluded_from_accepted_delivery() -> None:
    production = {
        "batches": [
            {
                "id": "batch-failed",
                "status": "failed",
                "plan_items": ["item-work"],
                "result": {
                    "outputs": [{"id": "out-bad", "ref": "src/bad.py"}],
                    "contributions": [],
                    "dispositions": {},
                },
            }
        ],
        "output_evidence": [],
        "dispositions": {},
    }
    delivery = extract_accepted_delivery(production)
    assert delivery.outputs == []


def test_completion_claim_is_current_requires_bound_revisions() -> None:
    plan = Plan(
        id="plan-1",
        revision=0,
        output_goal="Goal.",
        items={
            "item-work": PlanItem(
                "item-work",
                None,
                "0000000000",
                "Work",
                kind="work",
            )
        },
    )
    production = {
        "output_revision": 1,
        "dispositions": {"item-work": "completed"},
        "completion_claim": goal_met_completion_claim(
            {"output_revision": 0},
            plan_revision=0,
        ),
    }
    assert completion_claim_is_current(production["completion_claim"], production=production, plan=plan) is False
