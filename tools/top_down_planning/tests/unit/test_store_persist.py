"""Package persistence inside the run store."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from top_down_planning.package.loader import ExecutionPackageLoader
from top_down_planning.package.store_persist import persist_package_in_store
from tests.unit.test_prepared_runs import _built_package


def test_persist_package_is_idempotent(tmp_path: Path) -> None:
    store, _, package = _built_package(tmp_path)
    first = persist_package_in_store(store.root, package)
    second = persist_package_in_store(store.root, package)
    assert first == second
    reloaded = ExecutionPackageLoader().load(first.parent, verify_workspace=False)
    assert reloaded.manifest["package_digest"] == package.manifest["package_digest"]


def test_failed_persist_replace_leaves_prior_package(tmp_path: Path) -> None:
    store, _, package = _built_package(tmp_path)
    manifest_path = persist_package_in_store(store.root, package)
    marker = manifest_path.parent / "marker.txt"
    marker.write_text("keep-me", encoding="utf-8")
    original_digest = package.manifest["package_digest"]
    package.manifest["package_digest"] = "f" * 64

    with patch(
        "top_down_planning.package.store_persist.shutil.copytree",
        side_effect=RuntimeError("simulated persist failure"),
    ):
        with pytest.raises(RuntimeError, match="simulated persist failure"):
            persist_package_in_store(store.root, package)

    assert manifest_path.is_file()
    assert marker.is_file()
    reloaded = ExecutionPackageLoader().load(manifest_path.parent, verify_workspace=False)
    assert reloaded.manifest["package_digest"] == original_digest


def test_loader_rejects_missing_inherited_plan_approval_file(tmp_path: Path) -> None:
    from top_down_planning.package.loader import ExecutionPackageError

    store, _, package = _built_package(tmp_path)
    manifest_path = package.manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    approval_file = manifest["planning_run"]["inherited_plan_approval_file"]
    (manifest_path.parent / approval_file).unlink()
    with pytest.raises(ExecutionPackageError, match="approval file missing"):
        ExecutionPackageLoader().load(manifest_path.parent, verify_workspace=False)
