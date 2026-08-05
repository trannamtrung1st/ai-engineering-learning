"""Tests for prepared execution packages (proposal §22.1–22.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.domain.models import Plan, PlanItem, Scope
from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID
from top_down_planning.domain.sub_tdp_units import derive_sub_tdp_units
from top_down_planning.domain.unit_plan import build_unit_plan_snapshot, collect_assigned_item_ids
from top_down_planning.package.builder import ExecutionPackageBuilder
from top_down_planning.package.loader import ExecutionPackageError, ExecutionPackageLoader
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, whole_plan_approval_record


def _approved_parent_plan(run_id: str) -> Plan:
    root = PlanItem(
        id=PLAN_ROOT_ITEM_ID,
        parent_id=None,
        order_key="0000000000",
        title="Deliver",
        outcome="Deliver the output.",
        kind="aggregate",
    )
    foundation = PlanItem(
        id="item-foundation",
        parent_id=PLAN_ROOT_ITEM_ID,
        order_key="0000000000",
        title="Foundation",
        outcome="Persist state reliably.",
        kind="work",
        scope=Scope(includes=["storage"]),
    )
    storage = PlanItem(
        id="item-storage",
        parent_id="item-foundation",
        order_key="0000000001",
        title="Storage layer",
        outcome="Implement storage.",
        kind="work",
        scope=Scope(includes=["db"]),
    )
    return Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Ship the product.",
        input_refs=["docs/spec.md"],
        items={
            PLAN_ROOT_ITEM_ID: root,
            "item-foundation": foundation,
            "item-storage": storage,
        },
    )


def _planning_run_at_validated(store: FileRunStore, workspace: Path, run_id: str) -> None:
    config = create_run_kwargs(workspace)["resolved_config"]
    kwargs = create_run_kwargs(workspace, resolved_config=config)
    store.create_run(
        run_id,
        plan=_approved_parent_plan(run_id),
        phase="plan_validated",
        **kwargs,
    )
    store.save_review(run_id, whole_plan_approval_record(store, run_id))


def test_package_builder_materializes_manifest_and_unit_subtrees(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T000801-000801"
    _planning_run_at_validated(store, tmp_path, run_id)
    plan = store.load_plan_model(run_id)

    built = ExecutionPackageBuilder().build_from_planning_run(
        store,
        run_id,
        output_dir=tmp_path / ".tdp" / "execution",
    )

    assert built.manifest_path.name == "manifest.json"
    loaded = ExecutionPackageLoader().load(built.manifest_path.parent, verify_workspace=False)
    unit = loaded.units["item-foundation"]
    assigned = collect_assigned_item_ids(plan, "item-foundation")
    assert "item-storage" in assigned
    assert "item-storage" in unit.plan.items
    assert unit.plan.items["item-foundation"].outcome == "Persist state reliably."


def test_unit_snapshot_retains_descendant_contract_fields(tmp_path: Path) -> None:
    plan = _approved_parent_plan("run-test")
    unit = derive_sub_tdp_units(plan)[0]
    snapshot = build_unit_plan_snapshot(plan, unit, package_id="pkg-test")
    assert snapshot.input_refs == ["docs/spec.md"]
    assert snapshot.items["item-storage"].scope.includes == ["db"]


def test_unit_snapshot_root_passes_final_plan_validation() -> None:
    """Prepared unit plans must not keep the seeded Root placeholder.

    After whole-output approval, acceptance re-runs deterministic plan
    validation on the child plan. A seeded item-root (title=Root, empty
    outcome) blocks Sub-TDP completion even when the unit work item is sound.
    """

    from top_down_planning.domain.validators import validate_plan

    plan = _approved_parent_plan("run-test")
    unit = derive_sub_tdp_units(plan)[0]
    snapshot = build_unit_plan_snapshot(plan, unit, package_id="pkg-test")

    root = snapshot.items[PLAN_ROOT_ITEM_ID]
    assert root.title != "Root"
    assert root.outcome.strip()
    assert root.title == unit.title
    assert root.outcome == unit.outcome

    result = validate_plan(snapshot, mode="final")
    assert result.ok, [issue.message for issue in result.issues]


def test_package_validation_rejects_tampered_plan_digest(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T000802-000802"
    _planning_run_at_validated(store, tmp_path, run_id)
    output_dir = tmp_path / "package"
    ExecutionPackageBuilder().build_from_planning_run(store, run_id, output_dir=output_dir)

    unit_plan_path = output_dir / "units" / "01-foundation" / "plan.json"
    unit_plan_path.write_text(unit_plan_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(ExecutionPackageError, match="digest mismatch"):
        ExecutionPackageLoader().load(output_dir, verify_workspace=False)


def test_package_builder_rejects_incomplete_unit_coverage(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T000803-000803"
    plan = _approved_parent_plan(run_id)
    orphan = PlanItem(
        id="item-orphan",
        parent_id=PLAN_ROOT_ITEM_ID,
        order_key="0000000002",
        title="Orphan",
        outcome="Never assigned.",
        kind="work",
        scope=Scope(includes=["x"]),
    )
    plan.items["item-orphan"] = orphan
    config = create_run_kwargs(tmp_path)["resolved_config"]
    store.create_run(
        run_id,
        plan=plan,
        phase="plan_validated",
        **create_run_kwargs(tmp_path, resolved_config=config),
    )
    store.save_review(run_id, whole_plan_approval_record(store, run_id))

    builder = ExecutionPackageBuilder()
    units = derive_sub_tdp_units(plan)[:1]
    with pytest.raises(ValueError, match="not assigned to any unit"):
        builder._validate_unit_coverage(plan, units)
