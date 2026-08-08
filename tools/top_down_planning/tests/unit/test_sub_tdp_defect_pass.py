"""Defect-pass tests: remaining Sub-TDP correctness gaps from code review."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core_tools.persistence import atomic_write_json
from top_down_planning.domain.models import Plan, PlanItem, Scope
from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID
from top_down_planning.domain.sub_tdp_units import SubTdpUnit
from top_down_planning.orchestrator.phases import OUTPUT_VALIDATED
from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory
from top_down_planning.orchestrator.prepared_unit_executor import PreparedUnitExecutor
from top_down_planning.orchestrator.sub_tdps import SubTdpsPhaseOrchestrator
from top_down_planning.package.builder import ExecutionPackageBuilder
from top_down_planning.package.digests import assigned_subtree_digest
from top_down_planning.package.execution_validation import verify_package_authoritative_inputs
from top_down_planning.package.lineage import ExecutionLineageValidator
from top_down_planning.package.loader import ExecutionPackageError, ExecutionPackageLoader
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.digests import compute_output_digest
from top_down_planning.persistence.sub_tdp_state import unit_status_from_child_run
from tests.helpers import create_run_kwargs, whole_plan_approval_record


def _item(item_id: str, *, parent_id: str | None, order_key: str, title: str, **kwargs):
    return PlanItem(
        id=item_id,
        parent_id=parent_id,
        order_key=order_key,
        title=title,
        outcome=f"{title} outcome.",
        kind=kwargs.get("kind", "work"),
        depends_on=list(kwargs.get("depends_on") or []),
        scope=Scope(includes=[title.lower()]),
    )


def _dependent_plan(run_id: str) -> Plan:
    return Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Ship.",
        input_refs=[],
        items={
            PLAN_ROOT_ITEM_ID: _item(
                PLAN_ROOT_ITEM_ID,
                parent_id=None,
                order_key="0",
                title="Root",
                kind="aggregate",
            ),
            "item-a": _item("item-a", parent_id=PLAN_ROOT_ITEM_ID, order_key="1", title="A"),
            "item-b": _item(
                "item-b",
                parent_id=PLAN_ROOT_ITEM_ID,
                order_key="2",
                title="B",
                depends_on=["item-a"],
            ),
        },
    )


def _build_package(tmp_path: Path) -> tuple[FileRunStore, Path, Plan]:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T004001-004001"
    plan = _dependent_plan(run_id)
    kwargs = create_run_kwargs(tmp_path)
    store.create_run(run_id, plan=plan, phase="plan_validated", **kwargs)
    store.save_review(run_id, whole_plan_approval_record(store, run_id))
    output_dir = tmp_path / "pkg"
    ExecutionPackageBuilder().build_from_planning_run(
        store, run_id, output_dir=output_dir
    )
    return store, output_dir, plan


def _force_run_fields(store: FileRunStore, run_id: str, **fields) -> None:
    run = store.load_run(run_id)
    run = dict(run)
    run.update(fields)
    if (
        str(run.get("outcome") or "") == "accepted"
        and str(run.get("phase") or "") == OUTPUT_VALIDATED
    ):
        binding = dict(run.get("package_binding") or {})
        if not str(binding.get("whole_output_review_id") or "").strip():
            binding["whole_output_review_id"] = "review-whole-output-1"
            binding["whole_output_review_digest"] = "r" * 64
            run["package_binding"] = binding
    atomic_write_json(store.run_dir(run_id) / "run.json", run)


def _save_production(store: FileRunStore, run_id: str, production: dict) -> None:
    atomic_write_json(store.run_dir(run_id) / "production.json", production)


def test_all_units_completed_requires_accepted_digest() -> None:
    from top_down_planning.persistence.sub_tdp_state import (
        all_units_completed,
        initial_sub_tdp_state,
    )

    units = [
        SubTdpUnit(
            plan_item_id="item-a",
            title="A",
            outcome="A.",
            directory="01-a",
            ordinal=1,
        )
    ]
    state = initial_sub_tdp_state(units)
    state["units"][0]["status"] = "completed"
    assert all_units_completed(state, units) is False
    from top_down_planning.package.lineage import accepted_result_digest

    accepted = {
        "schema_version": 1,
        "package_id": "pkg",
        "package_digest": "p" * 64,
        "unit_id": "item-a",
        "unit_plan_digest": "u" * 64,
        "assigned_subtree_digest": "s" * 64,
        "child_run_id": "run-a",
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
    state["units"][0]["accepted_result"] = accepted
    state["units"][0]["accepted_result_digest"] = accepted_result_digest(accepted)
    assert all_units_completed(state, units) is True


def test_unit_status_requires_accepted_outcome() -> None:
    rejected = {
        "status": "completed",
        "phase": OUTPUT_VALIDATED,
        "outcome": "rejected",
    }
    assert unit_status_from_child_run(rejected) == "failed"

    accepted = {
        "status": "completed",
        "phase": OUTPUT_VALIDATED,
        "outcome": "accepted",
    }
    assert unit_status_from_child_run(accepted) == "completed"


def test_external_prerequisites_carry_owning_unit_contract_digest(tmp_path: Path) -> None:
    _, output_dir, plan = _build_package(tmp_path)
    package = ExecutionPackageLoader().load(output_dir)
    unit_b = package.units["item-b"]
    expected = assigned_subtree_digest(plan, "item-a")
    assert unit_b.external_prerequisites
    for entry in unit_b.external_prerequisites:
        assert entry["owning_unit_id"] == "item-a"
        assert entry["upstream_contract_digest"] == expected
        assert entry["upstream_contract_digest"]


def test_attach_rejects_missing_output_digest(tmp_path: Path) -> None:
    store, output_dir, _ = _build_package(tmp_path)
    package = ExecutionPackageLoader().load(output_dir)
    unit = package.units["item-a"]
    child_id = PreparedRunFactory().create_child_run(
        store,
        package,
        unit,
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
    )
    production = store.load_production(child_id)
    production["completion_claim"] = {
        "goal_met": True,
        "status": "accepted",
        "goal_assessment": "done",
    }
    _save_production(store, child_id, production)
    _force_run_fields(
        store,
        child_id,
        status="completed",
        phase=OUTPUT_VALIDATED,
        outcome="accepted",
        digests={
            key: value
            for key, value in (store.load_run(child_id).get("digests") or {}).items()
            if key != "output"
        },
    )

    mismatches = ExecutionLineageValidator().validate_attach(
        parent_package=package,
        parent_manifest_digest=str(package.manifest.get("package_digest") or ""),
        child_run=store.load_run(child_id),
        child_production=store.load_production(child_id),
        child_plan=store.load_plan_model(child_id),
    )
    assert any(m.field == "output_digest" for m in mismatches)


def test_prepared_run_persists_package_inside_run_store(tmp_path: Path) -> None:
    store, output_dir, _ = _build_package(tmp_path)
    package = ExecutionPackageLoader().load(output_dir)
    run_id = PreparedRunFactory().create_parent_run(
        store,
        package,
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
    )
    run = store.load_run(run_id)
    binding = run["package_binding"]
    persisted = Path(binding["manifest_path"])
    assert persisted.is_file()
    assert store.root.resolve() in persisted.resolve().parents
    shutil.rmtree(output_dir)
    reloaded = ExecutionPackageLoader().load(persisted.parent)
    assert reloaded.manifest["package_id"] == package.manifest["package_id"]


def test_child_run_binds_upstream_accepted_results(tmp_path: Path) -> None:
    from top_down_planning.package.builder import digest_review_record
    from top_down_planning.persistence.digests import compute_output_digest
    from tests.helpers import whole_output_approval_record

    store, output_dir, _ = _build_package(tmp_path)
    package = ExecutionPackageLoader().load(output_dir)
    unit_a = package.units["item-a"]
    dep_id = PreparedRunFactory().create_child_run(
        store,
        package,
        unit_a,
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
    )
    production = store.load_production(dep_id)
    production["completion_claim"] = {
        "goal_met": True,
        "status": "accepted",
        "goal_assessment": "A done",
    }
    production["output_revision"] = max(1, int(production.get("output_revision") or 0))
    _save_production(store, dep_id, production)
    approval = whole_output_approval_record(store, dep_id)
    store.save_review(dep_id, approval)
    review_id = str(approval.get("id") or "")
    stored_approval = store.load_review(dep_id, review_id)
    production = store.load_production(dep_id)
    output_digest = compute_output_digest(production)
    digests = dict(store.load_run(dep_id).get("digests") or {})
    digests["output"] = output_digest
    run = store.load_run(dep_id)
    binding = dict(run.get("package_binding") or {})
    binding["whole_output_review_id"] = review_id
    binding["whole_output_review_digest"] = digest_review_record(stored_approval)
    _force_run_fields(
        store,
        dep_id,
        status="completed",
        phase=OUTPUT_VALIDATED,
        outcome="accepted",
        digests=digests,
        package_binding=binding,
    )

    child_id = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        "item-b",
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
    )
    child = store.load_run(child_id)
    upstream = (child.get("package_binding") or {}).get("upstream_accepted_results")
    assert isinstance(upstream, list)
    assert len(upstream) == 1
    accepted = upstream[0]["accepted_result"]
    assert accepted["unit_id"] == "item-a"
    assert accepted["child_run_id"] == dep_id
    assert accepted["output_digest"] == output_digest
    assert upstream[0].get("upstream_contract_digest") == unit_a.assigned_subtree_digest
    assert upstream[0]["accepted_result_digest"]


def test_parent_provider_factory_does_not_swallow_child_factory_errors(
    tmp_path: Path,
) -> None:
    store, output_dir, _ = _build_package(tmp_path)
    package = ExecutionPackageLoader().load(output_dir)
    parent_id = PreparedRunFactory().create_parent_run(
        store,
        package,
        resolved_config=package.resolved_config,
        invocation={"command": "execute", "observability": {}},
    )
    _force_run_fields(store, parent_id, phase="sub_tdps", status="running")

    orch = SubTdpsPhaseOrchestrator(
        store,
        parent_id,
        provider=MagicMock(),
        create_provider=lambda *_a, **_k: MagicMock(name="parent-provider"),
    )
    unit = package.units["item-a"]
    sub_unit = SubTdpUnit(
        plan_item_id=unit.unit_id,
        title=unit.title,
        outcome="",
        directory=unit.plan_file.parent.name,
        ordinal=unit.ordinal,
    )
    child_id = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        unit.unit_id,
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
        parent_run_id=parent_id,
    )
    unit_record = {
        "plan_item_id": unit.unit_id,
        "status": "running",
        "child_run_id": child_id,
    }

    captured: dict[str, object] = {}

    def fake_execute_unit(*_args, **kwargs):
        factory_for_run = kwargs.get("provider_factory_for_run")
        if factory_for_run is not None:
            factory = factory_for_run(child_id)
        else:
            factory = kwargs["create_provider"]
        captured["factory"] = factory
        # Invoke as drive would — must not silently fall back to parent.
        factory(package.resolved_config, tmp_path)
        from top_down_planning.orchestrator.sub_tdp_child_driver import PreparedChildResult

        return PreparedChildResult.from_run(store.load_run(child_id), ok=True)

    with (
        patch(
            "top_down_planning.orchestrator.execution_runtime.build_provider",
            side_effect=RuntimeError("child provider must fail loudly"),
        ),
        patch.object(
            PreparedUnitExecutor,
            "execute_unit",
            side_effect=fake_execute_unit,
        ),
    ):
        with pytest.raises(RuntimeError, match="child provider must fail loudly"):
            orch._drive_prepared_unit(
                sub_unit,
                unit_record,
                create_provider=lambda c, w: MagicMock(name="parent"),
                workspace=tmp_path,
                config=package.resolved_config,
                package=package,
                child_store=store,
                child_run_id=child_id,
                was_existing=True,
            )


def test_context_snapshot_binding_file_is_verified(tmp_path: Path) -> None:
    _, output_dir, _ = _build_package(tmp_path)
    package = ExecutionPackageLoader().load(output_dir)
    binding_rel = (package.manifest.get("context") or {}).get(
        "context_snapshot_binding_file"
    )
    assert binding_rel
    binding_path = output_dir / binding_rel
    assert binding_path.is_file()
    # Tamper packaged binding without changing workspace files.
    payload = json.loads(binding_path.read_text(encoding="utf-8"))
    payload["resource_digests"] = dict(payload.get("resource_digests") or {})
    payload["resource_digests"]["__tampered__"] = "b" * 64
    binding_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ExecutionPackageError, match="context_snapshot_binding"):
        verify_package_authoritative_inputs(
            ExecutionPackageLoader().load(output_dir, verify_workspace=False)
        )


def test_unit_dependencies_satisfied_requires_accepted_digest() -> None:
    from top_down_planning.persistence.sub_tdp_state import (
        initial_sub_tdp_state,
        unit_dependencies_satisfied,
    )

    units = [
        SubTdpUnit(
            plan_item_id="item-a",
            title="A",
            outcome="A.",
            directory="01-a",
            ordinal=1,
        ),
        SubTdpUnit(
            plan_item_id="item-b",
            title="B",
            outcome="B.",
            directory="02-b",
            ordinal=2,
        ),
    ]
    state = initial_sub_tdp_state(units)
    state["units"][0]["status"] = "completed"
    # Missing accepted_result_digest must not satisfy downstream readiness.
    package_units = {
        "item-a": type(
            "U",
            (),
            {"depends_on": [], "unit_id": "item-a", "ordinal": 1},
        )(),
        "item-b": type(
            "U",
            (),
            {"depends_on": ["item-a"], "unit_id": "item-b", "ordinal": 2},
        )(),
    }
    assert unit_dependencies_satisfied(state, package_units, "item-b") is False
    from top_down_planning.package.lineage import accepted_result_digest

    accepted = {
        "schema_version": 1,
        "package_id": "pkg",
        "package_digest": "p" * 64,
        "unit_id": "item-a",
        "unit_plan_digest": "u" * 64,
        "assigned_subtree_digest": "s" * 64,
        "child_run_id": "run-a",
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
    state["units"][0]["accepted_result"] = accepted
    state["units"][0]["accepted_result_digest"] = accepted_result_digest(accepted)
    assert unit_dependencies_satisfied(state, package_units, "item-b") is True


def test_attach_compares_live_output_digest_when_present(tmp_path: Path) -> None:
    store, output_dir, _ = _build_package(tmp_path)
    package = ExecutionPackageLoader().load(output_dir)
    unit = package.units["item-a"]
    child_id = PreparedRunFactory().create_child_run(
        store,
        package,
        unit,
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
    )
    production = dict(store.load_production(child_id))
    production["completion_claim"] = {
        "goal_met": True,
        "status": "accepted",
        "goal_assessment": "done",
    }
    production["output_evidence"] = [
        {
            "id": "ev-1",
            "type": "artifact",
            "ref": "out.txt",
            "sha256": "a" * 64,
            "size": 4,
            "media_type": "text/plain",
            "captured_at": "2026-01-01T00:00:00Z",
            "batch_id": "b1",
        }
    ]
    expected = int(production["revision"])
    production["revision"] = expected + 1
    store.save_production(child_id, production, expected)
    live = compute_output_digest(store.load_production(child_id))
    digests = dict(store.load_run(child_id).get("digests") or {})
    digests["output"] = "0" * 64
    _force_run_fields(
        store,
        child_id,
        status="completed",
        phase=OUTPUT_VALIDATED,
        outcome="accepted",
        digests=digests,
    )

    mismatches = ExecutionLineageValidator().validate_attach(
        parent_package=package,
        parent_manifest_digest=str(package.manifest.get("package_digest") or ""),
        child_run=store.load_run(child_id),
        child_production=store.load_production(child_id),
        child_plan=store.load_plan_model(child_id),
    )
    assert any(
        m.field == "output_digest" and m.expected == "0" * 64 and m.actual == live
        for m in mismatches
    )
