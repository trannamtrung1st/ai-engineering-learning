"""Tests for tdp sub-tdp attach CLI."""

from __future__ import annotations

from pathlib import Path

from top_down_planning.domain.run_kind import RUN_KIND_PARENT_EXECUTION, RUN_KIND_SUB_TDP_EXECUTION
from top_down_planning.orchestrator.phases import SUB_TDPS
from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.sub_tdp_state import (
    initial_sub_tdp_state_from_package,
    load_sub_tdp_state,
    merge_sub_tdp_state_into_production,
)
from tests.conftest import run_cli
from tests.helpers import accept_child_run, create_run_kwargs
from tests.unit.test_prepared_runs import _built_package
from tests.unit.test_sub_tdp_defect_pass import _build_package as _dependent_build_package


def _parent_with_orchestration(tmp_path: Path):
    store, _, package = _built_package(tmp_path)
    config = create_run_kwargs(tmp_path)["resolved_config"]
    parent_id = PreparedRunFactory().create_parent_run(
        store,
        package,
        resolved_config=config,
        invocation={"command": "execute", "observability": {}},
    )
    run = store.load_run(parent_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["phase"] = SUB_TDPS
    run["status"] = "paused"
    run["stop"] = {
        "code": "sub_tdps_awaiting_children",
        "category": "operational",
        "phase": SUB_TDPS,
        "message": "waiting for children",
        "role": None,
        "details": {},
    }
    store.save_run(parent_id, run, expected)

    from top_down_planning.domain.sub_tdp_units import SubTdpUnit

    units = [
        SubTdpUnit(
            plan_item_id=unit.unit_id,
            title=unit.title,
            outcome="",
            directory=unit.plan_file.parent.name,
            ordinal=unit.ordinal,
        )
        for unit in sorted(package.units.values(), key=lambda item: item.ordinal)
    ]
    production = store.load_production(parent_id)
    parent_binding = store.load_run(parent_id).get("package_binding") or {}
    state = initial_sub_tdp_state_from_package(
        package.manifest,
        manifest_path=str(
            parent_binding.get("manifest_path") or package.manifest_path
        ),
        units=units,
        package_units=package.units,
    )
    merged = merge_sub_tdp_state_into_production(production, state)
    expected_revision = int(production["revision"])
    merged["revision"] = expected_revision + 1
    store.save_production(parent_id, merged, expected_revision)
    return store, parent_id, package, config


def test_sub_tdp_attach_updates_orchestration(tmp_path: Path) -> None:
    store, parent_id, package, config = _parent_with_orchestration(tmp_path)
    from top_down_planning.orchestrator.prepared_unit_executor import PreparedUnitExecutor

    child_id = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        "item-foundation",
        resolved_config=config,
        invocation={"command": "execute", "observability": {}},
        parent_run_id=parent_id,
    )
    accept_child_run(store, child_id)

    config_path = tmp_path / "project.yaml"
    config_path.write_text(
        "runtime:\n  runs_dir: runs\nprovider:\n  name: stub\n"
        "run:\n  output_goal: Ship the product.\n",
        encoding="utf-8",
    )
    result = run_cli(
        [
            "sub-tdp",
            "attach",
            "--parent",
            parent_id,
            "--child",
            child_id,
            "--config",
            str(config_path),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--stream-json",
        ]
    )
    assert result.exit_code == 0, result.stderr
    payload = result.json()
    assert payload["plan_item_id"] == "item-foundation"
    production = store.load_production(parent_id)
    state = load_sub_tdp_state(production)
    assert state is not None
    unit_record = state["units"][0]
    assert unit_record["child_run_id"] == child_id
    assert unit_record["status"] == "completed"
    assert store.load_run(parent_id).get("run_kind") == RUN_KIND_PARENT_EXECUTION
    assert store.load_run(child_id).get("run_kind") == RUN_KIND_SUB_TDP_EXECUTION


def test_sub_tdp_attach_rejects_lineage_mismatch(tmp_path: Path) -> None:
    store, parent_id, _, _ = _parent_with_orchestration(tmp_path)
    other_package_dir = tmp_path / "execution-other"
    from top_down_planning.package.builder import ExecutionPackageBuilder
    from tests.unit.test_execution_package import _planning_run_at_validated

    planning_store = FileRunStore(tmp_path / "runs")
    planning_run_id = "run-20260101T001101-001101"
    _planning_run_at_validated(planning_store, tmp_path, planning_run_id)
    ExecutionPackageBuilder().build_from_planning_run(
        planning_store,
        planning_run_id,
        output_dir=other_package_dir,
    )
    from top_down_planning.package.loader import ExecutionPackageLoader

    other_package = ExecutionPackageLoader().load(other_package_dir, verify_workspace=False)
    child_id = PreparedRunFactory().create_child_run(
        store,
        other_package,
        other_package.units["item-foundation"],
        resolved_config=create_run_kwargs(tmp_path)["resolved_config"],
        invocation={"command": "execute", "observability": {}},
    )
    run = store.load_run(child_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["status"] = "completed"
    run["phase"] = "output_validated"
    run["outcome"] = "accepted"
    store.save_run(child_id, run, expected)

    config_path = tmp_path / "project.yaml"
    config_path.write_text(
        "runtime:\n  runs_dir: runs\nrun:\n  output_goal: Ship the product.\n",
        encoding="utf-8",
    )
    result = run_cli(
        [
            "sub-tdp",
            "attach",
            "--parent",
            parent_id,
            "--child",
            child_id,
            "--config",
            str(config_path),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--stream-json",
        ]
    )
    assert result.exit_code == 1


def test_sub_tdp_attach_rejects_conflicting_completed_child(tmp_path: Path) -> None:
    store, parent_id, package, _config = _parent_with_orchestration(tmp_path)
    first_child_id = PreparedRunFactory().create_child_run(
        store,
        package,
        package.units["item-foundation"],
        resolved_config=create_run_kwargs(tmp_path)["resolved_config"],
        invocation={"command": "execute", "observability": {}},
    )
    second_child_id = PreparedRunFactory().create_child_run(
        store,
        package,
        package.units["item-foundation"],
        resolved_config=create_run_kwargs(tmp_path)["resolved_config"],
        invocation={"command": "execute", "observability": {}},
    )
    for child_id in (first_child_id, second_child_id):
        accept_child_run(store, child_id)

    production = store.load_production(parent_id)
    state = load_sub_tdp_state(production)
    assert state is not None
    state["units"][0]["child_run_id"] = first_child_id
    state["units"][0]["status"] = "completed"
    merged = merge_sub_tdp_state_into_production(production, state)
    expected_revision = int(production["revision"])
    merged["revision"] = expected_revision + 1
    store.save_production(parent_id, merged, expected_revision)

    config_path = tmp_path / "project.yaml"
    config_path.write_text(
        "runtime:\n  runs_dir: runs\nrun:\n  output_goal: Ship the product.\n",
        encoding="utf-8",
    )
    result = run_cli(
        [
            "sub-tdp",
            "attach",
            "--parent",
            parent_id,
            "--child",
            second_child_id,
            "--config",
            str(config_path),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--stream-json",
        ]
    )
    assert result.exit_code == 1


def test_sub_tdp_attach_rejects_running_parent(tmp_path: Path) -> None:
    store, parent_id, package, _config = _parent_with_orchestration(tmp_path)
    run = store.load_run(parent_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["status"] = "running"
    run["stop"] = None
    store.save_run(parent_id, run, expected)

    child_id = PreparedRunFactory().create_child_run(
        store,
        package,
        package.units["item-foundation"],
        resolved_config=create_run_kwargs(tmp_path)["resolved_config"],
        invocation={"command": "execute", "observability": {}},
    )
    accept_child_run(store, child_id)

    result = run_cli(
        [
            "sub-tdp",
            "attach",
            "--parent",
            parent_id,
            "--child",
            child_id,
            "--runs-dir",
            str(tmp_path / "runs"),
            "--stream-json",
        ]
    )
    assert result.exit_code == 1
    payload = result.json()
    assert payload.get("ok") is False
    err = payload.get("error") or {}
    assert err.get("code") == "sub_tdp_attach_rejected"
    assert "paused" in str(err.get("message") or "").lower()


def test_sub_tdp_attach_rejects_dependent_child_without_upstream_wrappers(
    tmp_path: Path,
) -> None:
    """Dependent attach must reject child runs missing upstream_accepted_results."""

    from top_down_planning.domain.sub_tdp_units import SubTdpUnit
    from top_down_planning.orchestrator.prepared_unit_executor import PreparedUnitExecutor
    from top_down_planning.package.loader import ExecutionPackageLoader

    store, output_dir, _plan = _dependent_build_package(tmp_path)
    package = ExecutionPackageLoader().load(output_dir, verify_workspace=False)
    config = create_run_kwargs(tmp_path)["resolved_config"]
    parent_id = PreparedRunFactory().create_parent_run(
        store,
        package,
        resolved_config=config,
        invocation={"command": "execute", "observability": {}},
    )
    run = store.load_run(parent_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["phase"] = SUB_TDPS
    run["status"] = "paused"
    run["stop"] = {
        "code": "sub_tdps_awaiting_children",
        "category": "operational",
        "phase": SUB_TDPS,
        "message": "waiting for children",
        "role": None,
        "details": {},
    }
    store.save_run(parent_id, run, expected)

    units = [
        SubTdpUnit(
            plan_item_id=unit.unit_id,
            title=unit.title,
            outcome="",
            directory=unit.plan_file.parent.name,
            ordinal=unit.ordinal,
        )
        for unit in sorted(package.units.values(), key=lambda item: item.ordinal)
    ]
    production = store.load_production(parent_id)
    parent_binding = store.load_run(parent_id).get("package_binding") or {}
    state = initial_sub_tdp_state_from_package(
        package.manifest,
        manifest_path=str(
            parent_binding.get("manifest_path") or package.manifest_path
        ),
        units=units,
        package_units=package.units,
    )
    merged = merge_sub_tdp_state_into_production(production, state)
    expected_revision = int(production["revision"])
    merged["revision"] = expected_revision + 1
    store.save_production(parent_id, merged, expected_revision)

    executor = PreparedUnitExecutor()
    child_a_id = executor.create_or_load_child_run(
        store,
        package,
        "item-a",
        resolved_config=config,
        invocation={"command": "execute"},
        parent_run_id=parent_id,
    )
    accept_child_run(store, child_a_id)

    config_path = tmp_path / "project.yaml"
    config_path.write_text(
        "runtime:\n  runs_dir: runs\nprovider:\n  name: stub\n"
        "run:\n  output_goal: Ship.\n",
        encoding="utf-8",
    )
    attach_a = run_cli(
        [
            "sub-tdp",
            "attach",
            "--parent",
            parent_id,
            "--child",
            child_a_id,
            "--config",
            str(config_path),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--stream-json",
        ]
    )
    assert attach_a.exit_code == 0, attach_a.stderr

    from top_down_planning.package.lineage import (
        accepted_result_record,
        upstream_accepted_result_binding,
    )

    a_accepted = accepted_result_record(
        child_run=store.load_run(child_a_id),
        child_production=store.load_production(child_a_id),
        unit_id="item-a",
        unit_plan_digest=package.units["item-a"].plan_digest,
        package_id=str(package.manifest.get("package_id") or ""),
        package_digest=str(package.manifest.get("package_digest") or ""),
        assigned_subtree_digest=package.units["item-a"].assigned_subtree_digest,
    )
    wrapper = upstream_accepted_result_binding(
        a_accepted,
        upstream_contract_digest=package.units["item-a"].assigned_subtree_digest,
    )
    child_b_id = PreparedRunFactory().create_child_run(
        store,
        package,
        package.units["item-b"],
        resolved_config=config,
        invocation={
            "command": "execute",
            "sub_tdp": {"parent_run_id": parent_id, "unit_id": "item-b"},
        },
        upstream_accepted_results=[wrapper],
    )
    # Strip upstream wrappers to simulate a dependency-invalid child at attach time.
    run = store.load_run(child_b_id)
    expected = int(run["revision"])
    run = dict(run)
    binding = dict(run.get("package_binding") or {})
    binding["upstream_accepted_results"] = []
    binding["workspace_baseline_accepted_results"] = []
    binding["baseline_accepted_result_digests"] = []
    run["package_binding"] = binding
    run["revision"] = expected + 1
    store.save_run(child_b_id, run, expected)
    accept_child_run(store, child_b_id)

    config_path = tmp_path / "project.yaml"
    config_path.write_text(
        "runtime:\n  runs_dir: runs\nprovider:\n  name: stub\n"
        "run:\n  output_goal: Ship.\n",
        encoding="utf-8",
    )
    result = run_cli(
        [
            "sub-tdp",
            "attach",
            "--parent",
            parent_id,
            "--child",
            child_b_id,
            "--config",
            str(config_path),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--stream-json",
        ]
    )
    assert result.exit_code != 0
    payload = result.json()
    assert payload.get("ok") is False
    err = payload.get("error") or {}
    assert err.get("code") == "sub_tdp_attach_rejected"
    assert "item-a" in str(err.get("message") or "").lower()
