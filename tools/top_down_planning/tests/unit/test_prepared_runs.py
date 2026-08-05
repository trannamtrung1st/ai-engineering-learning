"""Tests for prepared run factory and lifecycle separation (proposal §22.2)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from top_down_planning.domain.run_kind import (
    RUN_KIND_PARENT_EXECUTION,
    RUN_KIND_SUB_TDP_EXECUTION,
    resolve_run_kind,
)
from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory
from top_down_planning.orchestrator.phases import PLAN_VALIDATED, PLANNING
from top_down_planning.package.builder import ExecutionPackageBuilder
from top_down_planning.package.loader import ExecutionPackageError, ExecutionPackageLoader
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, whole_plan_approval_record
from tests.unit.test_execution_package import _approved_parent_plan, _planning_run_at_validated


def _built_package(tmp_path: Path) -> tuple[FileRunStore, str, ExecutionPackageLoader]:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T000901-000901"
    _planning_run_at_validated(store, tmp_path, run_id)
    built = ExecutionPackageBuilder().build_from_planning_run(
        store,
        run_id,
        output_dir=tmp_path / "execution",
    )
    loaded = ExecutionPackageLoader().load(built.manifest_path.parent, verify_workspace=False)
    return store, run_id, loaded


def test_prepared_run_rejects_config_drift_from_package(tmp_path: Path) -> None:
    store, _, package = _built_package(tmp_path)
    drifted = create_run_kwargs(tmp_path)["resolved_config"]
    drifted.setdefault("run", {})["output_goal"] = "A different deliverable goal."
    with pytest.raises(ExecutionPackageError, match="digest mismatch"):
        PreparedRunFactory().create_parent_run(
            store,
            package,
            resolved_config=drifted,
            invocation={"command": "execute", "observability": {}},
        )


def test_prepared_parent_run_has_parent_execution_kind_and_inherited_review(tmp_path: Path) -> None:
    store, _, package = _built_package(tmp_path)
    config = create_run_kwargs(tmp_path)["resolved_config"]
    run_id = PreparedRunFactory().create_parent_run(
        store,
        package,
        resolved_config=config,
        invocation={"command": "execute", "observability": {}},
    )
    run = store.load_run(run_id)
    assert resolve_run_kind(run) == RUN_KIND_PARENT_EXECUTION
    assert run["phase"] == PLAN_VALIDATED
    review = store.list_reviews(run_id)[0]
    assert review.get("plan_review_inherited") is True
    assert str(run.get("package_binding", {}).get("package_id")) == package.manifest["package_id"]


def test_prepared_child_run_loads_full_unit_plan_not_minimal_stub(tmp_path: Path) -> None:
    store, planning_run_id, package = _built_package(tmp_path)
    config = create_run_kwargs(tmp_path)["resolved_config"]
    unit = package.units["item-foundation"]
    child_id = PreparedRunFactory().create_child_run(
        store,
        package,
        unit,
        resolved_config=config,
        invocation={"command": "execute", "observability": {}},
    )
    run = store.load_run(child_id)
    plan = store.load_plan_model(child_id)
    assert resolve_run_kind(run) == RUN_KIND_SUB_TDP_EXECUTION
    assert "item-storage" in plan.items
    assert plan.items["item-foundation"].title == "Foundation"
    reviews = store.list_reviews(child_id)
    assert reviews and reviews[0].get("plan_review_inherited") is True


def test_execute_cli_creates_no_planner_sessions(tmp_path: Path) -> None:
    from unittest.mock import patch

    from tests.conftest import run_cli

    from tests.helpers import write_config

    _, _, package = _built_package(tmp_path)
    config_path = tmp_path / "project.yaml"
    write_config(
        config_path,
        f"project:\n  workspace: {tmp_path}\n"
        "runtime:\n  runs_dir: runs\nprovider:\n  name: stub\n"
        "run:\n  output_goal: Goal.\n",
    )
    manifest = tmp_path / "execution" / "manifest.json"
    captured: dict[str, str] = {}

    def _noop_drive(args, **kwargs):
        captured["run_id"] = kwargs["run_id"]
        run = kwargs["store"].load_run(kwargs["run_id"])
        captured["phase"] = str(run.get("phase") or "")
        captured["run_kind"] = str(run.get("run_kind") or "")

    with (
        patch(
            "top_down_planning.orchestrator.prepared_run_factory.validate_resolved_config_against_package"
        ),
        patch("top_down_planning.cli.execute._drive_execution_run", side_effect=_noop_drive),
    ):
        result = run_cli(
            [
                "execute",
                "--manifest",
                str(manifest),
                "--config",
                str(config_path),
                "--runs-dir",
                str(tmp_path / "runs"),
                "--stream-json",
            ]
        )
    assert result.exit_code == 0, result.stderr
    assert captured["phase"] == PLAN_VALIDATED
    assert captured["run_kind"] == RUN_KIND_PARENT_EXECUTION
