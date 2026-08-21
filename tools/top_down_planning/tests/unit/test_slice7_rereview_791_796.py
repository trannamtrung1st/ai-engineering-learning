"""Slice 7 re-review regressions for TDP-CLI-784 residual and 791–796."""

from __future__ import annotations

import multiprocessing
import os
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from top_down_planning.domain.run_kind import RUN_KIND_PLANNING
from top_down_planning.domain.run_ownership import RunOwnershipError, acquire_run_ownership
from top_down_planning.orchestrator.engine import RunContinuationResult
from top_down_planning.orchestrator.prepared_unit_executor import PreparedUnitExecutor
from top_down_planning.package.builder import ExecutionPackageBuilder
from top_down_planning.package.loader import ExecutionPackageLoader
from top_down_planning.package.store_persist import persist_package_in_store
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.commit import CommitSpec
from top_down_planning.persistence.snapshot_bindings import bind_run_digests_for_plan_update
from tests.conftest import run_cli
from tests.helpers import create_run_kwargs, write_config
from tests.support.run_builders import _approved_parent_plan, _planning_run_at_validated
from tests.support.run_builders import _built_package
from tests.support.cli_fakes import _assert_no_traceback
from tests.support.cli_fakes import _stdout_json
from tests.support.cli_fakes import _patch_prepare_plan_validated
from tests.unit.test_slice7_rereview_768_774 import _run_dirs
from tests.unit.test_slice7_rereview_784_790 import _planning_argv


def _rename_then_interrupt_when(predicate):
    real_rename = Path.rename

    def rename_then_interrupt(self, target):
        dest = Path(target)
        if predicate(self, dest):
            real_rename(self, dest)
            raise KeyboardInterrupt
        return real_rename(self, dest)

    return rename_then_interrupt


def test_package_promote_survives_interrupt_after_successful_rename(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T003001-003001"
    _planning_run_at_validated(store, tmp_path, run_id)
    output = tmp_path / "pkg"
    ExecutionPackageBuilder().build_from_planning_run(store, run_id, output_dir=output)
    prior = ExecutionPackageLoader().load(output, verify_workspace=False).manifest["package_id"]

    def is_promote(src: Path, dest: Path) -> bool:
        return src.name.startswith(".staging-") and dest.name == "pkg"

    with patch.object(Path, "rename", _rename_then_interrupt_when(is_promote)):
        result = run_cli(_planning_argv(tmp_path, run_id, output, ["--replace", "--stream-json"]))
    _assert_no_traceback(result)
    assert result.exit_code == 0
    payload = _stdout_json(result)
    assert payload["ok"] is True
    assert payload["package_id"] != prior
    assert ExecutionPackageLoader().load(output, verify_workspace=False).manifest["package_id"] == payload["package_id"]


def test_persist_package_survives_interrupt_after_successful_rename(tmp_path: Path) -> None:
    _, _, package = _built_package(tmp_path)
    store_root = tmp_path / "runs"

    def is_promote(src: Path, dest: Path) -> bool:
        return ".staging-" in src.name and dest.parent.name == ".execution_packages"

    with patch.object(Path, "rename", _rename_then_interrupt_when(is_promote)):
        persisted = persist_package_in_store(store_root, package)
    assert persisted.is_file()
    loaded = ExecutionPackageLoader().load(persisted.parent, verify_workspace=False)
    assert loaded.manifest["package_id"] == package.manifest["package_id"]


def test_create_run_returns_identity_when_interrupt_follows_publish(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "cfg.yaml",
        "run:\n  output_goal: Ship it.\n"
        f"project:\n  workspace: {tmp_path}\nprovider:\n  name: stub\n",
    )
    engine = MagicMock()
    engine.continue_run.return_value = RunContinuationResult(
        ok=True,
        run_id="pending",
        phase="planning",
        status="running",
        outcome=None,
        reason=None,
        cancelled=False,
        target_reached=True,
    )

    def is_publish(src: Path, dest: Path) -> bool:
        return src.name.startswith(".creating-") and dest.name.startswith("run-")

    argv = [
        "run",
        "--config",
        str(config_path),
        "--runs-dir",
        str(tmp_path / "runs"),
        "--stream-json",
    ]
    with (
        patch.object(Path, "rename", _rename_then_interrupt_when(is_publish)),
        patch("top_down_planning.cli.user._build_run_engine", return_value=engine),
    ):
        result = run_cli(argv)
    leftover = _run_dirs(tmp_path / "runs")
    _assert_no_traceback(result)
    assert leftover
    assert result.exit_code == 130
    payload = _stdout_json(result)
    assert payload.get("run_id") == leftover[0].name
    assert payload.get("ok") is False
    engine.continue_run.assert_not_called()
    assert not any(p.name.endswith(".lock") for p in (tmp_path / "runs").iterdir() if p.name.startswith(".creating-"))


def test_human_post_create_error_includes_run_identity(tmp_path: Path) -> None:
    engine = MagicMock()
    engine.continue_run.side_effect = PermissionError("denied")
    config_path = write_config(
        tmp_path / "cfg.yaml",
        "run:\n  output_goal: Ship it.\n"
        f"project:\n  workspace: {tmp_path}\nprovider:\n  name: stub\n",
    )
    argv = ["run", "--config", str(config_path), "--runs-dir", str(tmp_path / "runs")]
    with ExitStack() as stack:
        from tests.support.cli_fakes import _engine_patches

        for item in _engine_patches(tmp_path):
            stack.enter_context(item)
        stack.enter_context(patch("top_down_planning.cli.user._build_run_engine", return_value=engine))
        result = run_cli(argv)
    leftover = _run_dirs(tmp_path / "runs")
    assert leftover
    run_id = leftover[0].name
    _assert_no_traceback(result)
    text = result.stderr + result.stdout
    assert f"Run: {run_id}" in text
    assert "tdp status" in text or "Next:" in text


def test_fresh_package_build_failure_recovers_with_prepare_planning_run(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "cfg.yaml",
        "run:\n  output_goal: Ship it.\n"
        f"project:\n  workspace: {tmp_path}\nprovider:\n  name: stub\n",
    )
    engine = MagicMock()
    engine.continue_run.return_value = RunContinuationResult(
        ok=True,
        run_id="pending",
        phase="plan_validated",
        status="running",
        outcome=None,
        reason=None,
        cancelled=False,
        target_reached=True,
    )
    argv = [
        "prepare",
        "--config",
        str(config_path),
        "--runs-dir",
        str(tmp_path / "runs"),
        "--output",
        str(tmp_path / "pkg"),
        "--stream-json",
    ]
    with (
        patch("top_down_planning.cli.prepare._build_run_engine", return_value=engine),
        _patch_prepare_plan_validated(),
        patch(
            "top_down_planning.cli.prepare.ExecutionPackageBuilder.build_from_planning_run",
            side_effect=ValueError("materialize failed"),
        ),
    ):
        result = run_cli(argv)
    leftover = _run_dirs(tmp_path / "runs")
    assert leftover
    run_id = leftover[0].name
    payload = _stdout_json(result)
    assert payload["error"]["code"] == "package_build_failed"
    assert payload["recovery"]["command"] == "prepare"
    assert payload["recovery"]["planning_run_id"] == run_id


def test_unit_drive_ownership_conflict_is_normalized(tmp_path: Path) -> None:
    _, _, package = _built_package(tmp_path)
    argv = [
        "execute",
        "--manifest",
        str(package.manifest_path),
        "--unit",
        "item-foundation",
        "--runs-dir",
        str(tmp_path / "runs"),
        "--stream-json",
    ]

    def fail_drive(self, child_store, child_run_id, **kwargs):
        raise RunOwnershipError("owned", code="run_owned_by_live_process")

    with patch.object(PreparedUnitExecutor, "drive_child_run", fail_drive):
        result = run_cli(argv)
    leftover = _run_dirs(tmp_path / "runs")
    store = FileRunStore(tmp_path / "runs")
    children = [
        path.name
        for path in leftover
        if str(store.load_run(path.name).get("run_kind") or "") == "sub_tdp_execution"
    ]
    _assert_no_traceback(result)
    assert result.exit_code == 1
    payload = _stdout_json(result)
    assert payload["error"]["code"] == "run_owned_by_live_process"
    assert payload.get("run_id") == children[0]


def _hold_child_ownership(runs_dir: str, child_id: str, ready, release) -> None:
    store = FileRunStore(Path(runs_dir))
    acquire_run_ownership(child_id, run_dir=store.run_dir(child_id))
    ready.put("ready")
    release.get()


def test_concurrent_unit_execute_loser_emits_ownership_not_traceback(tmp_path: Path) -> None:
    store, _, package = _built_package(tmp_path)
    child_id = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        "item-foundation",
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
    )
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Queue()
    release = ctx.Queue()
    holder = ctx.Process(
        target=_hold_child_ownership,
        args=(str(store.root), child_id, ready, release),
    )
    holder.start()
    assert ready.get(timeout=5) == "ready"
    result = run_cli(
        [
            "execute",
            "--manifest",
            str(package.manifest_path),
            "--unit",
            "item-foundation",
            "--runs-dir",
            str(store.root),
            "--stream-json",
        ]
    )
    release.put("done")
    holder.join(timeout=5)
    _assert_no_traceback(result)
    assert result.exit_code == 1
    payload = _stdout_json(result)
    assert payload["error"]["code"] == "run_owned_by_live_process"
    assert payload.get("run_id") == child_id


@pytest.mark.parametrize("override", ["observability.color", "observability.color=rainbow"])
def test_configless_prepare_rejects_invalid_or_unparsed_set(tmp_path: Path, override: str) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T003002-003002"
    _planning_run_at_validated(store, tmp_path, run_id)
    result = run_cli(
        _planning_argv(tmp_path, run_id, tmp_path / "pkg", ["--set", override, "--stream-json"])
    )
    _assert_no_traceback(result)
    assert result.exit_code == 2
    payload = _stdout_json(result)
    assert payload["error"]["code"] == "config_error"
    assert not (tmp_path / "pkg").exists()


def test_fresh_prepare_uses_post_engine_snapshot_not_later_revision(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T003003-003003"
    _planning_run_at_validated(store, tmp_path, run_id)
    original = store.load_canonical_snapshot(run_id)
    config_path = write_config(
        tmp_path / "cfg.yaml",
        "run:\n  output_goal: Ship it.\n"
        f"project:\n  workspace: {tmp_path}\nprovider:\n  name: stub\n",
    )
    engine = MagicMock()
    engine.continue_run.return_value = RunContinuationResult(
        ok=True,
        run_id=run_id,
        phase="plan_validated",
        status="running",
        outcome=None,
        reason=None,
        cancelled=False,
        target_reached=True,
    )
    real_create = FileRunStore.create_run
    real_snapshot = FileRunStore.load_canonical_snapshot
    calls = {"n": 0}

    def reuse_existing(self, new_id, **kwargs):
        return self.load_run(run_id)

    def snapshot_then_bump(self, rid):
        snap = real_snapshot(self, rid)
        calls["n"] += 1
        if calls["n"] == 1:
            plan = dict(snap.plan)
            plan["revision"] = int(plan["revision"]) + 1
            bumped = bind_run_digests_for_plan_update(dict(snap.run), plan)
            bumped["revision"] = int(snap.run["revision"]) + 1
            self.commit(
                rid,
                CommitSpec(
                    run=bumped,
                    run_expected_revision=int(snap.run["revision"]),
                    plan=plan,
                    plan_expected_revision=int(snap.plan["revision"]),
                ),
            )
        return snap

    argv = [
        "prepare",
        "--config",
        str(config_path),
        "--runs-dir",
        str(tmp_path / "runs"),
        "--output",
        str(tmp_path / "pkg"),
        "--stream-json",
    ]
    with (
        patch.object(FileRunStore, "create_run", reuse_existing),
        patch("top_down_planning.cli.prepare._build_run_engine", return_value=engine),
        patch.object(FileRunStore, "load_canonical_snapshot", snapshot_then_bump),
    ):
        result = run_cli(argv)
    _assert_no_traceback(result)
    assert result.exit_code == 0
    payload = _stdout_json(result)
    package = ExecutionPackageLoader().load(tmp_path / "pkg", verify_workspace=False)
    assert payload["plan_revision"] == original.plan["revision"]
    assert package.manifest["planning_run"]["approved_plan_revision"] == original.plan["revision"]


def test_prepare_planning_run_accepts_tdp_runs_dir_without_config(tmp_path: Path, monkeypatch) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T003004-003004"
    _planning_run_at_validated(store, tmp_path, run_id)
    monkeypatch.setenv("TDP_RUNS_DIR", str(store.root))
    result = run_cli(
        [
            "prepare",
            "--planning-run",
            run_id,
            "--output",
            str(tmp_path / "pkg"),
            "--stream-json",
        ]
    )
    _assert_no_traceback(result)
    assert result.exit_code == 0
    assert _stdout_json(result)["planning_run_id"] == run_id


def test_builder_rejects_snapshot_for_different_planning_run(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_a = "run-20260101T003005-003005"
    run_b = "run-20260101T003006-003006"
    _planning_run_at_validated(store, tmp_path, run_a)
    kwargs = create_run_kwargs(tmp_path)
    store.create_run(
        run_b,
        plan=_approved_parent_plan(run_b),
        phase="plan_validated",
        run_extras={"run_kind": RUN_KIND_PLANNING},
        **kwargs,
    )
    snapshot_b = store.load_canonical_snapshot(run_b)
    with pytest.raises(ValueError, match="planning_run_id"):
        ExecutionPackageBuilder().build_from_planning_run(
            store, run_a, output_dir=tmp_path / "pkg", snapshot=snapshot_b
        )


def test_prepare_replace_reports_backup_cleanup_warning(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T003007-003007"
    _planning_run_at_validated(store, tmp_path, run_id)
    output = tmp_path / "pkg"
    ExecutionPackageBuilder().build_from_planning_run(store, run_id, output_dir=output)
    real_rmtree = __import__("shutil").rmtree

    def fail_backup(path, *args, **kwargs):
        if Path(path).name.startswith(".backup-"):
            raise OSError("backup busy")
        return real_rmtree(path, *args, **kwargs)

    with patch("top_down_planning.package.builder.shutil.rmtree", fail_backup):
        result = run_cli(_planning_argv(tmp_path, run_id, output, ["--replace", "--stream-json"]))
    payload = _stdout_json(result)
    assert payload["ok"] is True
    assert payload.get("cleanup_warning")
    assert ".backup-" in str(payload["cleanup_warning"])
