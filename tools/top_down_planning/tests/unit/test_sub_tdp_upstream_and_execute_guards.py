"""Guards for explicit upstream bindings and execute-time --set validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.cli.execute import (
    _validate_execute_presentation_sets,
    parse_upstream_bindings,
)
from top_down_planning.config import ConfigError
from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory
from top_down_planning.orchestrator.prepared_unit_executor import (
    PreparedUnitExecutor,
    validate_explicit_upstream_bindings,
)
from top_down_planning.package.loader import ExecutionPackageError, ExecutionPackageLoader
from tests.conftest import run_cli
from tests.helpers import create_run_kwargs
from tests.unit.test_prepared_runs import _built_package
from tests.unit.test_sub_tdp_defect_pass import _build_package


def test_parse_upstream_bindings_rejects_duplicate_unit() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        parse_upstream_bindings(
            [
                "item-a=run-20260101T000001-000001",
                "item-a=run-20260101T000002-000002",
            ]
        )


def test_validate_explicit_upstream_requires_complete_dependency_map(tmp_path: Path) -> None:
    store, output_dir, _ = _build_package(tmp_path)
    package = ExecutionPackageLoader().load(output_dir, verify_workspace=False)
    with pytest.raises(ExecutionPackageError, match="missing required"):
        validate_explicit_upstream_bindings(package, "item-b", {})


def test_validate_explicit_upstream_rejects_unknown_unit(tmp_path: Path) -> None:
    store, output_dir, _ = _build_package(tmp_path)
    package = ExecutionPackageLoader().load(output_dir, verify_workspace=False)
    with pytest.raises(ExecutionPackageError, match="not dependencies"):
        validate_explicit_upstream_bindings(
            package,
            "item-b",
            {"item-unknown": "run-1", "item-a": "run-2"},
        )


def test_direct_child_execution_creates_fresh_run_each_time(tmp_path: Path) -> None:
    store, _, package = _built_package(tmp_path)
    config = create_run_kwargs(tmp_path)["resolved_config"]
    executor = PreparedUnitExecutor()
    first = executor.create_or_load_child_run(
        store,
        package,
        "item-foundation",
        resolved_config=config,
        invocation={"command": "execute", "observability": {}},
    )
    second = executor.create_or_load_child_run(
        store,
        package,
        "item-foundation",
        resolved_config=config,
        invocation={"command": "execute", "observability": {}},
    )
    assert first != second


def test_execute_rejects_unsupported_set_override(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not allowed"):
        _validate_execute_presentation_sets(["provider.name=stub"])


def test_execute_upstream_without_unit_rejected(tmp_path: Path) -> None:
    store, _, package = _built_package(tmp_path)
    config = create_run_kwargs(tmp_path)["resolved_config"]
    parent_id = PreparedRunFactory().create_parent_run(
        store,
        package,
        resolved_config=config,
        invocation={"command": "execute", "observability": {}},
    )
    binding = store.load_run(parent_id)["package_binding"]
    manifest_path = binding["manifest_path"]
    config_path = tmp_path / "project.yaml"
    config_path.write_text(
        "runtime:\n  runs_dir: runs\n",
        encoding="utf-8",
    )
    result = run_cli(
        [
            "execute",
            "--manifest",
            str(manifest_path),
            "--upstream",
            "item-foundation=run-1",
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
