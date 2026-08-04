"""Tests for tdp sub-tdp attach CLI."""

from __future__ import annotations

from pathlib import Path

from top_down_planning.domain.models import Plan, PlanItem, Scope
from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID
from top_down_planning.domain.sub_tdp_units import SubTdpUnit
from top_down_planning.orchestrator.phases import SUB_TDPS
from top_down_planning.orchestrator.sub_tdp_child_driver import (
    child_runs_store_path,
    create_child_run,
    child_unit_directory,
    load_child_resolved_config,
)
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.sub_tdp_state import initial_sub_tdp_state
from tests.conftest import run_cli
from tests.helpers import create_run_kwargs, whole_plan_approval_record
from top_down_planning.orchestrator.sub_tdp_artifact_writer import write_sub_tdp_artifacts


def _parent_plan(run_id: str) -> Plan:
    root = PlanItem(
        id=PLAN_ROOT_ITEM_ID,
        parent_id=None,
        order_key="0000000000",
        title="Deliver",
        outcome="Deliver the output.",
        kind="aggregate",
    )
    first = PlanItem(
        id="item-a",
        parent_id=PLAN_ROOT_ITEM_ID,
        order_key="0000000000",
        title="Persistence foundation",
        outcome="Persist state reliably.",
        kind="work",
        scope=Scope(includes=["storage"]),
    )
    return Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Ship the product.",
        items={PLAN_ROOT_ITEM_ID: root, "item-a": first},
    )


def test_sub_tdp_attach_updates_orchestration(tmp_path: Path) -> None:
    workspace = tmp_path
    runs_dir = tmp_path / "runs"
    store = FileRunStore(runs_dir)
    run_id = "run-20260101T001001-001001"
    config = create_run_kwargs(workspace)["resolved_config"]
    config["execution"] = {"mode": "sub_tdps"}
    kwargs = create_run_kwargs(workspace, resolved_config=config)
    store.create_run(
        run_id,
        plan=_parent_plan(run_id),
        phase=SUB_TDPS,
        **kwargs,
    )
    store.save_review(run_id, whole_plan_approval_record(store, run_id))

    units = [
        SubTdpUnit(
            plan_item_id="item-a",
            title="Persistence foundation",
            outcome="Persist state reliably.",
            directory="01-persistence-foundation",
            ordinal=1,
        ),
    ]
    write_sub_tdp_artifacts(workspace, units, parent_config=config)
    production = store.load_production(run_id)
    expected_production_revision = int(production["revision"])
    production = dict(production)
    production["sub_tdps"] = initial_sub_tdp_state(units)
    production["revision"] = expected_production_revision + 1
    store.save_production(run_id, production, expected_production_revision)

    unit = units[0]
    child_store = FileRunStore(child_runs_store_path(workspace, unit))
    child_config = load_child_resolved_config(child_unit_directory(workspace, unit))
    child_run_id = create_child_run(
        child_store,
        unit,
        child_config=child_config,
        workspace=workspace,
    )
    child_run = child_store.load_run(child_run_id)
    expected = int(child_run["revision"])
    child_run = dict(child_run)
    child_run["revision"] = expected + 1
    child_run["status"] = "completed"
    child_run["phase"] = "output_validated"
    child_run["outcome"] = "accepted"
    child_store.save_run(child_run_id, child_run, expected)

    config_path = tmp_path / "config.yaml"
    config_path.write_text("execution:\n  mode: sub_tdps\n", encoding="utf-8")

    result = run_cli(
        [
            "sub-tdp",
            "attach",
            "--parent",
            run_id,
            "--unit",
            "item-a",
            "--child",
            child_run_id,
            "--config",
            str(config_path),
            "--runs-dir",
            str(runs_dir),
            "--stream-json",
        ]
    )
    assert result.exit_code == 0, result.stderr
    payload = result.json()
    assert payload["ok"] is True
    assert payload["unit_status"] == "completed"

    updated = store.load_production(run_id)
    unit_record = updated["sub_tdps"]["units"][0]
    assert unit_record["child_run_id"] == child_run_id
    assert unit_record.get("summary")


def test_sub_tdp_attach_rejects_workspace_mismatch(tmp_path: Path) -> None:
    workspace = tmp_path
    runs_dir = tmp_path / "runs"
    store = FileRunStore(runs_dir)
    run_id = "run-20260101T001002-001002"
    config = create_run_kwargs(workspace)["resolved_config"]
    config["execution"] = {"mode": "sub_tdps"}
    kwargs = create_run_kwargs(workspace, resolved_config=config)
    store.create_run(
        run_id,
        plan=_parent_plan(run_id),
        phase=SUB_TDPS,
        **kwargs,
    )
    units = [
        SubTdpUnit(
            plan_item_id="item-a",
            title="Persistence foundation",
            outcome="Persist state reliably.",
            directory="01-persistence-foundation",
            ordinal=1,
        ),
    ]
    production = store.load_production(run_id)
    expected_production_revision = int(production["revision"])
    production = dict(production)
    production["sub_tdps"] = initial_sub_tdp_state(units)
    production["revision"] = expected_production_revision + 1
    store.save_production(run_id, production, expected_production_revision)

    other_workspace = tmp_path / "other"
    other_workspace.mkdir()
    unit = units[0]
    child_store = FileRunStore(child_runs_store_path(other_workspace, unit))
    root = write_sub_tdp_artifacts(other_workspace, units, parent_config=config)
    child_config = load_child_resolved_config(root / unit.directory)
    child_run_id = create_child_run(
        child_store,
        unit,
        child_config=child_config,
        workspace=other_workspace,
    )

    config_path = tmp_path / "config.yaml"
    config_path.write_text("execution:\n  mode: sub_tdps\n", encoding="utf-8")

    result = run_cli(
        [
            "sub-tdp",
            "attach",
            "--parent",
            run_id,
            "--unit",
            "item-a",
            "--child",
            child_run_id,
            "--config",
            str(config_path),
            "--runs-dir",
            str(runs_dir),
            "--stream-json",
        ]
    )
    assert result.exit_code == 1
    payload = result.json()
    assert payload.get("error", {}).get("code") == "sub_tdp_attach_rejected"


def test_sub_tdp_attach_rejects_completed_parent(tmp_path: Path) -> None:
    workspace = tmp_path
    runs_dir = tmp_path / "runs"
    store = FileRunStore(runs_dir)
    run_id = "run-20260101T001003-001003"
    config = create_run_kwargs(workspace)["resolved_config"]
    config["execution"] = {"mode": "sub_tdps"}
    kwargs = create_run_kwargs(workspace, resolved_config=config)
    store.create_run(
        run_id,
        plan=_parent_plan(run_id),
        phase=SUB_TDPS,
        **kwargs,
    )
    run = store.load_run(run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["status"] = "completed"
    run["outcome"] = "accepted"
    run["stop"] = None
    store.save_run(run_id, run, expected)
    config_path = tmp_path / "config.yaml"
    config_path.write_text("execution:\n  mode: sub_tdps\n", encoding="utf-8")
    result = run_cli(
        [
            "sub-tdp",
            "attach",
            "--parent",
            run_id,
            "--unit",
            "item-a",
            "--child",
            "run-child-01",
            "--config",
            str(config_path),
            "--runs-dir",
            str(runs_dir),
            "--stream-json",
        ]
    )
    assert result.exit_code == 1
    payload = result.json()
    assert payload.get("error", {}).get("code") == "sub_tdp_attach_rejected"
