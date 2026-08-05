"""Additional review-fix tests for execute runtime, synthesis, and attach."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from top_down_planning.domain.models import Plan, PlanItem, Scope
from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID
from top_down_planning.domain.run_kind import (
    RUN_KIND_PARENT_EXECUTION,
    RUN_KIND_SUB_TDP_EXECUTION,
    resolve_run_kind,
)
from top_down_planning.domain.sub_tdp_synthesis import synthesize_parent_production
from top_down_planning.domain.sub_tdp_units import SubTdpUnit
from top_down_planning.orchestrator.prepared_unit_executor import PreparedUnitExecutor
from top_down_planning.package.builder import ExecutionPackageBuilder
from top_down_planning.package.lineage import ExecutionLineageValidator
from top_down_planning.package.loader import ExecutionPackageError, ExecutionPackageLoader
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.sub_tdp_state import (
    initial_sub_tdp_state,
    load_sub_tdp_state,
    unit_dependencies_satisfied,
)
from top_down_planning.observability import map_audit_event
from tests.conftest import run_cli
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


def _simple_plan(run_id: str) -> Plan:
    return Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Ship.",
        input_refs=[],
        items={
            PLAN_ROOT_ITEM_ID: _item(
                PLAN_ROOT_ITEM_ID, parent_id=None, order_key="0", title="Root", kind="aggregate"
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


def _build_package(tmp_path: Path) -> tuple[FileRunStore, Path]:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T002001-002001"
    workspace = tmp_path
    plan = _simple_plan(run_id)
    kwargs = create_run_kwargs(workspace)
    store.create_run(run_id, plan=plan, phase="plan_validated", **kwargs)
    store.save_review(run_id, whole_plan_approval_record(store, run_id))
    output_dir = tmp_path / "pkg"
    ExecutionPackageBuilder().build_from_planning_run(store, run_id, output_dir=output_dir)
    return store, output_dir


def test_resolve_run_kind_rejects_invalid_explicit_kind() -> None:
    with pytest.raises(ValueError, match="invalid run_kind"):
        resolve_run_kind({"run_kind": "not_a_real_kind", "phase": "production"})


def test_resolve_run_kind_requires_explicit_kind() -> None:
    with pytest.raises(ValueError, match="run_kind is required"):
        resolve_run_kind({"phase": "production"})


def test_unit_dependencies_satisfied_rejects_unknown_unit() -> None:
    state = initial_sub_tdp_state(
        [
            SubTdpUnit(
                plan_item_id="item-a",
                title="A",
                outcome="A.",
                directory="01-a",
                ordinal=1,
            )
        ]
    )
    with pytest.raises(ValueError, match="unknown unit"):
        unit_dependencies_satisfied(state, {}, "item-missing")


def test_load_sub_tdp_state_returns_deep_copy() -> None:
    production = {
        "sub_tdps": {
            "units": [{"plan_item_id": "item-a", "status": "pending"}],
            "status": "running",
        }
    }
    loaded = load_sub_tdp_state(production)
    assert loaded is not None
    loaded["units"][0]["status"] = "completed"
    assert production["sub_tdps"]["units"][0]["status"] == "pending"


def test_synthesize_fails_when_child_disposition_missing() -> None:
    units = [
        SubTdpUnit(
            plan_item_id="item-a",
            title="A",
            outcome="A.",
            directory="01-a",
            ordinal=1,
        )
    ]
    plan = Plan(
        id="plan",
        revision=0,
        output_goal="Ship.",
        items={
            PLAN_ROOT_ITEM_ID: _item(
                PLAN_ROOT_ITEM_ID, parent_id=None, order_key="0", title="Root", kind="aggregate"
            ),
            "item-a": _item("item-a", parent_id=PLAN_ROOT_ITEM_ID, order_key="1", title="A"),
            "item-a-leaf": _item(
                "item-a-leaf", parent_id="item-a", order_key="1", title="Leaf"
            ),
        },
    )
    # Rebuild units so item-a is aggregate with leaf - actually item-a is work.
    # Use aggregate unit root with work descendant.
    plan.items["item-a"] = _item(
        "item-a", parent_id=PLAN_ROOT_ITEM_ID, order_key="1", title="A", kind="aggregate"
    )
    production = {
        "revision": 0,
        "output_revision": 0,
        "batches": [],
        "dispositions": {},
        "output_evidence": [],
        "amendment_requests": [],
        "pending_amendment_id": None,
        "reconciliation_reports": [],
        "completion_claim": None,
        "blocker_report": None,
        "sub_tdps": initial_sub_tdp_state(units),
    }
    child_run = {
        "id": "run-child",
        "status": "completed",
        "phase": "output_validated",
        "outcome": "accepted",
    }
    child_production = {
        "completion_claim": {"goal_met": True, "goal_assessment": "ok"},
        "output_evidence": [],
        "dispositions": {},
        "batches": [],
    }
    with pytest.raises(ValueError, match="disposition"):
        synthesize_parent_production(
            plan,
            production,
            child_runs=[(production["sub_tdps"]["units"][0], child_run, child_production)],
            parent_output_goal="Ship.",
        )


def test_synthesize_sets_integration_pending_not_goal_met() -> None:
    units = [
        SubTdpUnit(
            plan_item_id="item-a",
            title="A",
            outcome="A.",
            directory="01-a",
            ordinal=1,
        )
    ]
    plan = Plan(
        id="plan",
        revision=0,
        output_goal="Ship.",
        items={
            PLAN_ROOT_ITEM_ID: _item(
                PLAN_ROOT_ITEM_ID, parent_id=None, order_key="0", title="Root", kind="aggregate"
            ),
            "item-a": _item("item-a", parent_id=PLAN_ROOT_ITEM_ID, order_key="1", title="A"),
        },
    )
    production = {
        "revision": 0,
        "output_revision": 0,
        "batches": [],
        "dispositions": {},
        "output_evidence": [],
        "amendment_requests": [],
        "pending_amendment_id": None,
        "reconciliation_reports": [],
        "completion_claim": None,
        "blocker_report": None,
        "sub_tdps": initial_sub_tdp_state(units),
    }
    child_run = {
        "id": "run-child",
        "status": "completed",
        "phase": "output_validated",
        "outcome": "accepted",
    }
    child_production = {
        "completion_claim": {"goal_met": True, "goal_assessment": "Child done."},
        "output_evidence": [{"id": "ev-1", "batch_id": "child-batch-1", "path": "out.md"}],
        "dispositions": {
            "item-a": {"disposition": "completed", "evidence": "done"},
        },
        "batches": [],
    }
    synthesized = synthesize_parent_production(
        plan,
        production,
        child_runs=[(production["sub_tdps"]["units"][0], child_run, child_production)],
        parent_output_goal="Ship.",
    )
    assert synthesized["completion_claim"]["goal_met"] is False
    assert synthesized["completion_claim"]["status"] == "integration_pending"
    evidence = synthesized["output_evidence"][0]
    assert evidence["batch_id"] == "batch-integration-01"
    assert evidence["source_child_batch_id"] == "child-batch-1"
    assert evidence["source_child_evidence_id"] == "ev-1"


def test_map_audit_event_maps_sub_tdp_boundaries() -> None:
    for event_type, category in [
        ("sub_tdp_child_started", "sub-tdp:start"),
        ("sub_tdp_child_resumed", "sub-tdp:resume"),
        ("sub_tdp_child_completed", "sub-tdp:end"),
        ("sub_tdp_child_attached", "sub-tdp:attach"),
        ("sub_tdp_child_blocked", "sub-tdp:blocked"),
    ]:
        mapped = map_audit_event(
            {
                "type": event_type,
                "run_id": "run-parent",
                "child_run_id": "run-child",
                "unit_id": "item-a",
            }
        )
        assert mapped is not None
        assert mapped.category == category


def test_dependency_accepted_requires_same_package(tmp_path: Path) -> None:
    store, package_dir = _build_package(tmp_path)
    package = ExecutionPackageLoader().load(package_dir, verify_workspace=False)
    kwargs = create_run_kwargs(tmp_path)
    store.create_run(
        "run-20260101T002010-002010",
        plan=package.units["item-a"].plan,
        phase="output_validated",
        **kwargs,
        run_extras={
            "run_kind": RUN_KIND_SUB_TDP_EXECUTION,
            "package_binding": {
                "package_id": "tdp-package-other",
                "package_digest": "deadbeef",
                "selected_unit_id": "item-a",
                "unit_plan_digest": package.units["item-a"].plan_digest,
                "assigned_subtree_digest": package.units["item-a"].assigned_subtree_digest,
            },
        },
    )
    run = store.load_run("run-20260101T002010-002010")
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["status"] = "completed"
    run["phase"] = "output_validated"
    run["outcome"] = "accepted"
    store.save_run("run-20260101T002010-002010", run, expected)

    executor = PreparedUnitExecutor()
    with pytest.raises(PreparedUnitExecutor.DependencyUnmetError):
        executor._check_external_dependencies(package, "item-b", store)


def test_execute_unknown_unit_structured_error(tmp_path: Path) -> None:
    _, package_dir = _build_package(tmp_path)
    result = run_cli(
        [
            "execute",
            "--manifest",
            str(package_dir / "manifest.json"),
            "--unit",
            "item-missing",
            "--runs-dir",
            str(tmp_path / "runs"),
            "--stream-json",
        ]
    )
    assert result.exit_code == 1
    assert "unknown_unit" in result.stderr or "unknown unit" in result.stderr.lower() or (
        result.stdout and "unknown" in result.stdout.lower()
    )


def test_attach_rejected_during_whole_output_review(tmp_path: Path) -> None:
    store, package_dir = _build_package(tmp_path)
    package = ExecutionPackageLoader().load(package_dir, verify_workspace=False)
    parent_kwargs = create_run_kwargs(tmp_path)
    store.create_run(
        "run-20260101T002020-002020",
        plan=package.parent_plan,
        phase="whole_output_review",
        **parent_kwargs,
        run_extras={
            "run_kind": RUN_KIND_PARENT_EXECUTION,
            "package_binding": {
                "manifest_path": str(package.manifest_path),
                "package_id": package.manifest["package_id"],
                "package_digest": package.manifest["package_digest"],
            },
        },
    )
    production = store.load_production("run-20260101T002020-002020")
    from top_down_planning.persistence.sub_tdp_state import (
        initial_sub_tdp_state_from_package,
        merge_sub_tdp_state_into_production,
    )
    from top_down_planning.domain.sub_tdp_units import derive_sub_tdp_units

    state = initial_sub_tdp_state_from_package(
        package.manifest,
        manifest_path=str(package.manifest_path),
        units=derive_sub_tdp_units(package.parent_plan),
        package_units=package.units,
    )
    merged = merge_sub_tdp_state_into_production(production, state)
    store.save_production("run-20260101T002020-002020", {**merged, "revision": 1}, 0)

    child_kwargs = create_run_kwargs(tmp_path)
    store.create_run(
        "run-20260101T002021-002021",
        plan=package.units["item-a"].plan,
        phase="output_validated",
        **child_kwargs,
        run_extras={
            "run_kind": RUN_KIND_SUB_TDP_EXECUTION,
            "package_binding": {
                "package_id": package.manifest["package_id"],
                "package_digest": package.manifest["package_digest"],
                "selected_unit_id": "item-a",
                "unit_plan_digest": package.units["item-a"].plan_digest,
                "assigned_subtree_digest": package.units["item-a"].assigned_subtree_digest,
            },
        },
    )
    child = store.load_run("run-20260101T002021-002021")
    expected = int(child["revision"])
    child = dict(child)
    child["revision"] = expected + 1
    child["status"] = "completed"
    child["phase"] = "output_validated"
    child["outcome"] = "accepted"
    store.save_run("run-20260101T002021-002021", child, expected)

    result = run_cli(
        [
            "sub-tdp",
            "attach",
            "--parent",
            "run-20260101T002020-002020",
            "--child",
            "run-20260101T002021-002021",
            "--runs-dir",
            str(tmp_path / "runs"),
            "--stream-json",
        ]
    )
    assert result.exit_code != 0
