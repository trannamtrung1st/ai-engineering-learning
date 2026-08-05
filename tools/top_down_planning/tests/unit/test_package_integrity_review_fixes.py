"""Additional package integrity tests for review P0/P1 fixes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from top_down_planning.domain.models import Plan, PlanItem, Scope
from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID
from top_down_planning.domain.unit_plan import build_unit_plan_snapshot
from top_down_planning.domain.sub_tdp_units import derive_sub_tdp_units
from top_down_planning.package.builder import ExecutionPackageBuilder
from top_down_planning.package.digests import assigned_subtree_digest
from top_down_planning.package.loader import ExecutionPackageError, ExecutionPackageLoader
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, whole_plan_approval_record


def _item(
    item_id: str,
    *,
    parent_id: str | None,
    order_key: str,
    title: str,
    depends_on: list[str] | None = None,
    kind: str = "work",
) -> PlanItem:
    return PlanItem(
        id=item_id,
        parent_id=parent_id,
        order_key=order_key,
        title=title,
        outcome=f"{title} outcome.",
        kind=kind,
        depends_on=list(depends_on or []),
        scope=Scope(includes=[title.lower()]),
    )


def _plan_with_deps(run_id: str) -> Plan:
    return Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Ship the product.",
        input_refs=["docs/spec.md"],
        items={
            PLAN_ROOT_ITEM_ID: _item(
                PLAN_ROOT_ITEM_ID,
                parent_id=None,
                order_key="0",
                title="Deliver",
                kind="aggregate",
            ),
            "item-a": _item(
                "item-a",
                parent_id=PLAN_ROOT_ITEM_ID,
                order_key="1",
                title="Foundation",
            ),
            "item-b": _item(
                "item-b",
                parent_id=PLAN_ROOT_ITEM_ID,
                order_key="2",
                title="API",
                depends_on=["item-a"],
            ),
            "item-c": _item(
                "item-c",
                parent_id=PLAN_ROOT_ITEM_ID,
                order_key="3",
                title="UI",
            ),
        },
    )


def _planning_run(store: FileRunStore, workspace: Path, run_id: str, plan: Plan) -> None:
    (workspace / "docs").mkdir(parents=True, exist_ok=True)
    (workspace / "docs" / "spec.md").write_text("spec v1\n", encoding="utf-8")
    config = create_run_kwargs(workspace)["resolved_config"]
    config = dict(config)
    run_section = dict(config.get("run") or {})
    run_section["input_refs"] = ["docs/spec.md"]
    run_section["output_goal"] = plan.output_goal
    config["run"] = run_section
    kwargs = create_run_kwargs(workspace, resolved_config=config)
    store.create_run(run_id, plan=plan, phase="plan_validated", **kwargs)
    approval = whole_plan_approval_record(store, run_id)
    approval["findings"] = [
        {
            "id": "finding-1",
            "category": "correctness",
            "severity": "blocker",
            "summary": "Resolved during planning.",
            "issue": "Resolved during planning.",
            "recommended_change": "Keep the approved plan.",
            "status": "resolved",
            "blocking": True,
            "target_refs": [],
            "evidence": [],
        }
    ]
    store.save_review(run_id, approval)


def test_package_builder_derives_real_unit_dependencies(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T001001-001001"
    _planning_run(store, tmp_path, run_id, _plan_with_deps(run_id))

    built = ExecutionPackageBuilder().build_from_planning_run(
        store,
        run_id,
        output_dir=tmp_path / "pkg",
    )
    units = {u["unit_id"]: u for u in built.manifest["units"]}
    assert units["item-a"]["depends_on"] == []
    assert units["item-b"]["depends_on"] == ["item-a"]
    assert units["item-c"]["depends_on"] == []
    assert units["item-b"]["external_prerequisites"]
    assert units["item-b"]["external_prerequisites"][0]["dependency_item_id"] == "item-a"
    assert units["item-a"]["external_prerequisites"] == []


def test_unit_snapshot_strips_external_depends_on(tmp_path: Path) -> None:
    plan = _plan_with_deps("x")
    units = derive_sub_tdp_units(plan)
    unit_b = next(u for u in units if u.plan_item_id == "item-b")
    snapshot = build_unit_plan_snapshot(plan, unit_b, all_units=units, package_id="pkg-1")
    assert snapshot.items["item-b"].depends_on == []
    assert snapshot.id == "plan-pkg-1-item-b"


def test_subtree_digest_changes_when_item_contract_changes() -> None:
    plan = _plan_with_deps("x")
    before = assigned_subtree_digest(plan, "item-a")
    plan.items["item-a"].outcome = "Changed outcome."
    after = assigned_subtree_digest(plan, "item-a")
    assert before != after


def test_package_stores_per_input_digests(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T001002-001002"
    _planning_run(store, tmp_path, run_id, _plan_with_deps(run_id))
    built = ExecutionPackageBuilder().build_from_planning_run(
        store, run_id, output_dir=tmp_path / "pkg2"
    )
    refs = built.manifest["context"]["input_refs"]
    assert isinstance(refs, dict)
    assert "aggregate_digest" in refs
    assert len(refs["refs"]) == 1
    assert refs["refs"][0]["path"] == "docs/spec.md"
    assert refs["refs"][0]["sha256"]
    assert "execution_config" in built.manifest or (
        built.manifest_path.parent / "execution" / "resolved_config.json"
    ).is_file()


def test_package_preserves_review_findings(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T001003-001003"
    _planning_run(store, tmp_path, run_id, _plan_with_deps(run_id))
    built = ExecutionPackageBuilder().build_from_planning_run(
        store, run_id, output_dir=tmp_path / "pkg3"
    )
    approval = built.manifest["planning_run"]["inherited_plan_approval"]
    assert approval["findings"]
    assert approval["findings"][0]["id"] == "finding-1"
    assert built.manifest["planning_run"]["whole_plan_review_digest"] != (
        built.manifest["planning_run"]["approved_plan_digest"]
    )


def test_loader_rejects_path_traversal(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T001004-001004"
    _planning_run(store, tmp_path, run_id, _plan_with_deps(run_id))
    output_dir = tmp_path / "pkg4"
    ExecutionPackageBuilder().build_from_planning_run(store, run_id, output_dir=output_dir)
    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["units"][0]["plan_file"] = "../outside/plan.json"
    # Keep package_digest stale so loader fails on path first if checked before digest
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ExecutionPackageError, match="escapes|outside|path"):
        ExecutionPackageLoader().load(output_dir, verify_workspace=False)


def test_failed_replace_leaves_prior_package(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T001005-001005"
    _planning_run(store, tmp_path, run_id, _plan_with_deps(run_id))
    output_dir = tmp_path / "pkg5"
    first = ExecutionPackageBuilder().build_from_planning_run(
        store, run_id, output_dir=output_dir
    )
    first_digest = first.manifest["package_digest"]
    marker = output_dir / "marker.txt"
    marker.write_text("keep-me", encoding="utf-8")

    class BoomBuilder(ExecutionPackageBuilder):
        def _validate_unit_coverage(self, plan, units):  # type: ignore[no-untyped-def]
            raise ValueError("simulated build failure")

    with pytest.raises(ValueError, match="simulated build failure"):
        BoomBuilder().build_from_planning_run(
            store, run_id, output_dir=output_dir, replace=True
        )

    assert output_dir.is_dir()
    assert marker.is_file()
    reloaded = ExecutionPackageLoader().load(output_dir, verify_workspace=False)
    assert reloaded.manifest["package_digest"] == first_digest


def test_input_tampering_rejected_at_validation(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T001006-001006"
    _planning_run(store, tmp_path, run_id, _plan_with_deps(run_id))
    output_dir = tmp_path / "pkg6"
    built = ExecutionPackageBuilder().build_from_planning_run(
        store, run_id, output_dir=output_dir
    )
    package = ExecutionPackageLoader().load(output_dir)
    (tmp_path / "docs" / "spec.md").write_text("tampered\n", encoding="utf-8")

    from top_down_planning.package.execution_validation import verify_package_authoritative_inputs

    with pytest.raises(ExecutionPackageError, match="docs/spec.md"):
        verify_package_authoritative_inputs(package)
