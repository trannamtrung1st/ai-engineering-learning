"""Regression tests for Slice 3 round-15 review (TDP-PERSIST-056..059)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from core_tools.persistence import PersistenceError, atomic_write_json
from top_down_planning.config import recompute_context_snapshot_binding
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.production import derive_live_disposition_map
from top_down_planning.orchestrator.phases import PRODUCTION
from top_down_planning.package.lineage import accepted_result_digest
from top_down_planning.persistence import FileRunStore
from top_down_planning.domain.sub_tdp_units import SubTdpUnit
from top_down_planning.persistence.sub_tdp_state import initial_sub_tdp_state_from_package
from tests.helpers import apply_production, bind_evidence_snapshot, create_run_kwargs, grant_capability, whole_plan_approval_record, write_config
from tests.unit.test_commit_crash_recovery import _create_run
from tests.unit.test_persistence_round12_fixes import (
    _create_resource_run,
    _new_run_id as _resource_run_id,
)
from tests.unit.test_prepared_runs import _built_package


def _new_run_id(suffix: str) -> str:
    return f"run-20260101T0061{suffix}-0061{suffix}"


def _minimal_evidence(
    *,
    evidence_id: str = "out-1",
    batch_id: str = "batch-01",
    ref: str = "src/file.py",
    sha256: str | None = None,
) -> dict:
    return {
        "id": evidence_id,
        "type": "artifact",
        "ref": ref,
        "sha256": sha256 or ("a" * 64),
        "size": 10,
        "media_type": "text/plain",
        "captured_at": "2026-01-01T00:00:00Z",
        "batch_id": batch_id,
    }


def _nested_output_from_evidence(evidence: dict) -> dict:
    return {key: value for key, value in evidence.items() if key != "batch_id"}


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
    nested = _nested_output_from_evidence(evidence)
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


def _package_backed_sub_tdps_state(tmp_path: Path) -> tuple[FileRunStore, dict, object]:
    store, _, package = _built_package(tmp_path)
    units = list(package.units.values())
    sub_tdp_units = [
        SubTdpUnit(
            plan_item_id=u.unit_id,
            title=u.title,
            outcome="",
            directory=u.plan_file.parent.name,
            ordinal=u.ordinal,
        )
        for u in sorted(units, key=lambda item: item.ordinal)
    ]
    state = initial_sub_tdp_state_from_package(
        package.manifest,
        manifest_path=str(package.manifest_path),
        units=sub_tdp_units,
        package_units=package.units,
    )
    return store, state, package


def test_load_production_rejects_top_level_evidence_missing_from_batch_outputs(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("01")
    _create_run(store, run_id)
    batch, evidence = _mirrored_completed_batch(store=store, run_id=run_id)
    batch["result"]["outputs"] = []
    production = store.load_production(run_id)
    production["batches"] = [batch]
    production["output_evidence"] = [evidence]
    production["dispositions"] = {"item-work": "completed"}
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="result.outputs"):
        store.load_production(run_id)


@pytest.mark.parametrize(
    ("batch_status", "run_suffix"),
    [("started", "02"), ("failed", "03"), ("aborted", "04")],
)
def test_load_production_rejects_evidence_on_non_completed_batch(
    tmp_path: Path,
    batch_status: str,
    run_suffix: str,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id(run_suffix)
    _create_run(store, run_id)
    batch, evidence = _mirrored_completed_batch(store=store, run_id=run_id)
    batch["status"] = batch_status
    production = store.load_production(run_id)
    production["batches"] = [batch]
    production["output_evidence"] = [evidence]
    production["dispositions"] = {}
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="completed live batch"):
        store.load_production(run_id)


def test_load_production_rejects_mismatched_evidence_mirror_metadata(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("03")
    _create_run(store, run_id)
    batch, evidence = _mirrored_completed_batch(store=store, run_id=run_id)
    batch["result"]["outputs"][0]["ref"] = "src/other.py"
    production = store.load_production(run_id)
    production["batches"] = [batch]
    production["output_evidence"] = [evidence]
    production["dispositions"] = {"item-work": "completed"}
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="mirror"):
        store.load_production(run_id)


def test_load_production_rejects_nested_output_without_top_level_evidence(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("04")
    _create_run(store, run_id)
    batch, _evidence = _mirrored_completed_batch(store=store, run_id=run_id)
    production = store.load_production(run_id)
    production["batches"] = [batch]
    production["output_evidence"] = []
    production["dispositions"] = {"item-work": "completed"}
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="output_evidence"):
        store.load_production(run_id)


def test_load_production_rejects_cross_batch_contribution_output_ref(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("05")
    _create_run(store, run_id)
    batch_a, evidence_a = _mirrored_completed_batch(
        batch_id="batch-a",
        evidence_id="out-a",
        store=store,
        run_id=run_id,
    )
    batch_b, evidence_b = _mirrored_completed_batch(
        batch_id="batch-b",
        plan_items=["item-other"],
        evidence_id="out-b",
        store=store,
        run_id=run_id,
    )
    batch_b["result"]["contributions"] = [
        {
            "item_id": "item-other",
            "output_refs": ["out-a"],
            "summary": "cross-batch ref",
        }
    ]
    batch_b["result"]["outputs"] = [_nested_output_from_evidence(evidence_b)]
    production = store.load_production(run_id)
    production["batches"] = [batch_a, batch_b]
    production["output_evidence"] = [evidence_a, evidence_b]
    production["dispositions"] = {"item-work": "completed", "item-other": "completed"}
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="output_ref"):
        store.load_production(run_id)


def test_load_production_rejects_contribution_item_outside_batch_plan_items(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("06")
    _create_run(store, run_id)
    batch, evidence = _mirrored_completed_batch(store=store, run_id=run_id)
    batch["result"]["contributions"] = [
        {
            "item_id": "item-missing",
            "output_refs": ["out-1"],
            "summary": "wrong item",
        }
    ]
    production = store.load_production(run_id)
    production["batches"] = [batch]
    production["output_evidence"] = [evidence]
    production["dispositions"] = {"item-work": "completed"}
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="plan_items"):
        store.load_production(run_id)


def test_save_production_rejects_forged_top_level_evidence(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    src = workspace / "src"
    src.mkdir(parents=True)
    feature = src / "feature.py"
    feature.write_text("v1\n", encoding="utf-8")
    store = FileRunStore(tmp_path / "runs")
    run_id = _resource_run_id("11")
    _create_resource_run(store, run_id, workspace)
    store.save_review(run_id, whole_plan_approval_record(store, run_id))

    from top_down_planning.agent_tool import ProductionAgentService

    run = store.load_run(run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["phase"] = PRODUCTION
    run["status"] = "running"
    store.save_run(run_id, run, expected)

    service = ProductionAgentService(store, run_id)
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)
    service.apply(
        {
            "production_revision": int(store.load_production(run_id)["revision"]),
            "plan_items": ["item-work"],
            "dispositions": {
                "item-work": {"disposition": "completed", "evidence": "done"},
            },
            "outputs": [],
            "contributions": [],
            "summary": "empty batch",
            "empty_output": True,
            "empty_output_reason": "no files",
        },
        capability_token=token,
    )

    feature.write_text("v2\n", encoding="utf-8")
    digest = hashlib.sha256(feature.read_bytes()).hexdigest()
    production = dict(store.load_production(run_id))
    expected = int(production["revision"])
    production["revision"] = expected + 1
    production["output_evidence"].append(
        {
            "id": "forged-out",
            "batch_id": production["batches"][0]["id"],
            "ref": "src/feature.py",
            "sha256": digest,
            "size": feature.stat().st_size,
            "media_type": "text/plain",
            "captured_at": "2026-01-01T00:00:00Z",
            "type": "artifact",
        }
    )
    before = (store.run_dir(run_id) / "production.json").read_bytes()

    with pytest.raises(PersistenceError, match="result.outputs"):
        store.save_production(run_id, production, expected)

    assert (store.run_dir(run_id) / "production.json").read_bytes() == before


def test_forged_top_level_evidence_cannot_authorize_context_snapshot_rebase(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "ws"
    src = workspace / "src"
    src.mkdir(parents=True)
    feature = src / "feature.py"
    feature.write_text("v1\n", encoding="utf-8")
    store = FileRunStore(tmp_path / "runs")
    run_id = _resource_run_id("12")
    _create_resource_run(store, run_id, workspace)

    production = dict(store.load_production(run_id))
    batch, evidence = _mirrored_completed_batch(
        batch_id="batch-01",
        store=store,
        run_id=run_id,
    )
    production["batches"] = [batch]
    production["output_evidence"] = [evidence]
    production["dispositions"] = {"item-work": "completed"}
    expected_prod = int(production["revision"])
    production["revision"] = expected_prod + 1
    store.save_production(run_id, production, expected_prod)

    feature.write_text("v2-unauthorized\n", encoding="utf-8")
    digest = hashlib.sha256(feature.read_bytes()).hexdigest()
    production = dict(store.load_production(run_id))
    expected_prod = int(production["revision"])
    production["revision"] = expected_prod + 1
    production["output_evidence"].append(
        {
            "id": "forged-out",
            "batch_id": "batch-01",
            "ref": "src/feature.py",
            "sha256": digest,
            "size": feature.stat().st_size,
            "media_type": "text/plain",
            "captured_at": "2026-01-01T00:00:00Z",
            "type": "artifact",
        }
    )
    with pytest.raises(PersistenceError, match="result.outputs"):
        store.save_production(run_id, production, expected_prod)

    run = store.load_run(run_id)
    config = store.load_resolved_config(run_id)
    expected_run = int(run["revision"])
    new_binding, new_digest = recompute_context_snapshot_binding(config, workspace=workspace)
    run = dict(run)
    run["revision"] = expected_run + 1
    run["context_snapshot_binding"] = new_binding
    digests = dict(run.get("digests") or {})
    digests["context_snapshot"] = new_digest
    run["digests"] = digests
    with pytest.raises(PersistenceError, match="src/feature.py"):
        store.save_run(run_id, run, expected_run)


def test_load_production_rejects_orphan_flat_completed_disposition(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("21")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["batches"] = []
    production["dispositions"] = {"item-work": "completed"}
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="dispositions"):
        store.load_production(run_id)


def test_load_production_rejects_flat_disposition_conflicting_with_batch_record(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("22")
    _create_run(store, run_id)
    batch, evidence = _mirrored_completed_batch(
        disposition="blocked",
        store=store,
        run_id=run_id,
    )
    production = store.load_production(run_id)
    production["batches"] = [batch]
    production["output_evidence"] = [evidence]
    production["dispositions"] = {"item-work": "completed"}
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="dispositions"):
        store.load_production(run_id)


def test_derive_live_disposition_map_ignores_invalidated_batch(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("23")
    _create_run(store, run_id)
    live_batch, live_evidence = _mirrored_completed_batch(
        batch_id="batch-live",
        store=store,
        run_id=run_id,
    )
    invalidated_batch, _ = _mirrored_completed_batch(
        batch_id="batch-old",
        plan_items=["item-old"],
        evidence_id="out-old",
        store=store,
        run_id=run_id,
    )
    invalidated_batch["evidence_status"] = "invalidated_by_reconciliation"
    invalidated_batch["invalidated_item_ids"] = ["item-old"]
    production = store.load_production(run_id)
    production["batches"] = [invalidated_batch, live_batch]
    production["output_evidence"] = [live_evidence]
    production["dispositions"] = {"item-work": "completed"}
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    loaded = store.load_production(run_id)
    assert derive_live_disposition_map(loaded) == {"item-work": "completed"}


def test_save_production_rejects_conflicting_live_batch_dispositions(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("24")
    _create_run(store, run_id)
    batch_a, evidence_a = _mirrored_completed_batch(
        batch_id="batch-a",
        evidence_id="out-a",
        disposition="completed",
        store=store,
        run_id=run_id,
    )
    batch_b, evidence_b = _mirrored_completed_batch(
        batch_id="batch-b",
        evidence_id="out-b",
        disposition="blocked",
        store=store,
        run_id=run_id,
    )
    production = store.load_production(run_id)
    expected = int(production["revision"])
    production = dict(production)
    production["revision"] = expected + 1
    production["batches"] = [batch_a, batch_b]
    production["output_evidence"] = [evidence_a, evidence_b]
    production["dispositions"] = {"item-work": "completed"}

    with pytest.raises(PersistenceError, match="conflicting live disposition"):
        store.save_production(run_id, production, expected)


def test_mirrored_production_apply_round_trips(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    src = workspace / "src"
    src.mkdir(parents=True)
    (src / "feature.py").write_text("content\n", encoding="utf-8")
    config = write_config(
        workspace / "cfg.yaml",
        """
run:
  output_goal: Goal.
agent_context:
  roles:
    producer:
      resources:
        - src/
""",
    )
    store = FileRunStore(tmp_path / "runs")
    plan = Plan(
        id="plan-apply",
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
    run_id = _new_run_id("25")
    from top_down_planning.config import resolve_config

    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(workspace, resolved_config=resolve_config(config, cwd=workspace)),
    )
    store.save_review(run_id, whole_plan_approval_record(store, run_id))
    run = store.load_run(run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["phase"] = PRODUCTION
    run["status"] = "running"
    store.save_run(run_id, run, expected)
    apply_production(
        store,
        run_id,
        {
            "production_revision": int(store.load_production(run_id)["revision"]),
            "plan_items": ["item-work"],
            "dispositions": {
                "item-work": {"disposition": "completed", "evidence": "done"},
            },
            "outputs": [{"id": "out-1", "type": "artifact", "ref": "src/feature.py"}],
            "contributions": [
                {
                    "item_id": "item-work",
                    "output_refs": ["out-1"],
                    "summary": "done",
                }
            ],
            "summary": "batch",
        },
        handler="apply",
        phase=PRODUCTION,
    )()
    loaded = store.load_production(run_id)
    assert derive_live_disposition_map(loaded) == {"item-work": "completed"}
    assert loaded["output_evidence"][0]["batch_id"] == loaded["batches"][0]["id"]


def test_load_production_rejects_partial_completion_claim_with_string_revision(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("31")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["completion_claim"] = {
        "goal_met": True,
        "goal_assessment": "done",
        "plan_revision": "not-an-integer",
    }
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="plan_revision"):
        store.load_production(run_id)


def test_load_production_rejects_true_completion_claim_missing_binding_fields(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("32")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["completion_claim"] = {
        "goal_met": True,
        "goal_assessment": "done",
    }
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="plan_revision"):
        store.load_production(run_id)


def test_load_production_rejects_false_completion_claim_without_integration_pending(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("33")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["completion_claim"] = {
        "goal_met": False,
        "goal_assessment": "waiting",
    }
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="integration_pending"):
        store.load_production(run_id)


def test_load_production_accepts_supported_completion_claim_variants(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("34")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["completion_claim"] = {
        "goal_met": True,
        "goal_assessment": "Output goal is fully met.",
        "summary": "Done.",
        "plan_revision": 0,
        "output_revision": 0,
        "all_applicable_items_processed": True,
    }
    atomic_write_json(store.run_dir(run_id) / "production.json", production)
    assert store.load_production(run_id)["completion_claim"]["goal_met"] is True

    production["completion_claim"] = {
        "goal_met": False,
        "status": "integration_pending",
        "goal_assessment": "Child deliveries collected.",
        "submitted_at": "2026-01-01T00:00:00Z",
    }
    atomic_write_json(store.run_dir(run_id) / "production.json", production)
    assert store.load_production(run_id)["completion_claim"]["status"] == "integration_pending"


def test_load_production_rejects_version2_sub_tdps_missing_package_identity(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _new_run_id("41")
    _create_run(store, run_id)
    production = store.load_production(run_id)
    production["sub_tdps"] = {
        "version": 2,
        "status": "preparing",
        "active_unit_id": None,
        "units": [],
    }
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="package_id"):
        store.load_production(run_id)


def test_load_production_accepts_package_generated_version2_state(tmp_path: Path) -> None:
    store, state, _package = _package_backed_sub_tdps_state(tmp_path)
    run_id = "run-20260101T000901-000901"
    production = store.load_production(run_id)
    expected = int(production["revision"])
    production = dict(production)
    production["revision"] = expected + 1
    production["sub_tdps"] = state
    store.save_production(run_id, production, expected)
    loaded = store.load_production(run_id)
    assert loaded["sub_tdps"]["package_id"]
    assert loaded["sub_tdps"]["package_digest"]


def test_load_production_rejects_completed_unit_accepted_result_package_mismatch(
    tmp_path: Path,
) -> None:
    store, state, package = _package_backed_sub_tdps_state(tmp_path)
    run_id = "run-20260101T000901-000901"
    unit = state["units"][0]
    accepted = {
        "schema_version": 1,
        "package_id": "other-package",
        "package_digest": str(package.manifest.get("package_digest") or ""),
        "unit_id": unit["plan_item_id"],
        "unit_plan_digest": unit["unit_plan_digest"],
        "assigned_subtree_digest": unit["assigned_subtree_digest"],
        "child_run_id": "child-1",
        "output_revision": 1,
        "output_digest": "d" * 64,
        "whole_output_review_id": "review-01",
        "whole_output_review_digest": "e" * 64,
        "outcome": "accepted",
        "evidence_digest": "f" * 64,
        "output_refs": [],
        "contributions": [],
        "workspace_changes": {},
        "baseline_context_snapshot_digest": "2" * 64,
        "final_context_snapshot_digest": "3" * 64,
        "baseline_accepted_result_digests": [],
        "completion_assessment": "done",
    }
    unit["status"] = "completed"
    unit["child_run_id"] = "child-1"
    unit["accepted_result"] = accepted
    unit["accepted_result_digest"] = accepted_result_digest(accepted)
    production = store.load_production(run_id)
    production["sub_tdps"] = state
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="package_id"):
        store.load_production(run_id)


def test_load_production_rejects_accepted_result_short_digest(tmp_path: Path) -> None:
    store, state, package = _package_backed_sub_tdps_state(tmp_path)
    run_id = "run-20260101T000901-000901"
    unit = state["units"][0]
    accepted = {
        "schema_version": 1,
        "package_id": str(package.manifest.get("package_id") or ""),
        "package_digest": str(package.manifest.get("package_digest") or ""),
        "unit_id": unit["plan_item_id"],
        "unit_plan_digest": unit["unit_plan_digest"],
        "assigned_subtree_digest": unit["assigned_subtree_digest"],
        "child_run_id": "child-1",
        "output_revision": 1,
        "output_digest": "short",
        "whole_output_review_id": "review-01",
        "whole_output_review_digest": "e" * 64,
        "outcome": "accepted",
        "evidence_digest": "f" * 64,
        "output_refs": [],
        "contributions": [],
        "workspace_changes": {},
        "baseline_context_snapshot_digest": "2" * 64,
        "final_context_snapshot_digest": "3" * 64,
        "baseline_accepted_result_digests": [],
        "completion_assessment": "done",
    }
    unit["status"] = "completed"
    unit["child_run_id"] = "child-1"
    unit["accepted_result"] = accepted
    unit["accepted_result_digest"] = accepted_result_digest(accepted)
    production = store.load_production(run_id)
    production["sub_tdps"] = state
    atomic_write_json(store.run_dir(run_id) / "production.json", production)

    with pytest.raises(PersistenceError, match="output_digest"):
        store.load_production(run_id)
