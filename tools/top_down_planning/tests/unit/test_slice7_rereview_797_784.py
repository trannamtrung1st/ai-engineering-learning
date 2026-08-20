"""Slice 7 re-review regressions for residual 784/775/789/796 and new 797."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core_tools.persistence import PersistenceError
from top_down_planning.domain.run_ownership import RunOwnershipError
from top_down_planning.orchestrator.engine import RunContinuationResult
from top_down_planning.package.builder import ExecutionPackageBuilder
from top_down_planning.package.loader import ExecutionPackageLoader
from top_down_planning.persistence import FileRunStore
from tests.conftest import run_cli
from tests.helpers import write_config
from tests.unit.test_execution_package import _planning_run_at_validated
from tests.unit.test_prepared_runs import _built_package
from tests.unit.test_slice7_rereview_751_754 import _assert_no_traceback
from tests.unit.test_slice7_rereview_755_758 import _stdout_json
from tests.unit.test_slice7_rereview_760_764 import _engine_patches
from tests.unit.test_slice7_rereview_768_774 import _run_dirs
from tests.unit.test_slice7_rereview_784_790 import _planning_argv
from tests.unit.test_slice7_rereview_791_796 import _rename_then_interrupt_when


def _fail_backup_rename(exc):
    real_rename = Path.rename

    def rename(self, target):
        dest = Path(target)
        if dest.name.startswith(".backup-"):
            raise exc
        return real_rename(self, dest)

    return rename


@pytest.mark.parametrize("exc", [PermissionError("cannot backup"), KeyboardInterrupt])
def test_prepare_replace_fails_when_backup_rename_does_not_move(tmp_path: Path, exc) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T004001-004001"
    _planning_run_at_validated(store, tmp_path, run_id)
    output = tmp_path / "pkg"
    prior = ExecutionPackageBuilder().build_from_planning_run(store, run_id, output_dir=output)
    argv = _planning_argv(tmp_path, run_id, output, ["--replace", "--stream-json"])
    with patch.object(Path, "rename", _fail_backup_rename(exc)):
        result = run_cli(argv)
    _assert_no_traceback(result)
    assert result.exit_code != 0
    payload = _stdout_json(result)
    assert payload.get("ok") is False
    assert payload.get("package_id") != prior.package_id
    reloaded = ExecutionPackageLoader().load(output, verify_workspace=False)
    assert reloaded.manifest["package_id"] == prior.package_id


def test_create_run_interrupt_after_publish_exits_130_without_engine(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "cfg.yaml",
        "run:\n  output_goal: Ship it.\n"
        f"project:\n  workspace: {tmp_path}\nprovider:\n  name: stub\n",
    )
    engine = MagicMock()

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
    assert not any(
        path.name.endswith(".lock")
        for path in (tmp_path / "runs").iterdir()
        if path.name.startswith(".creating-")
    )


def test_pre_publish_interrupt_does_not_advertise_generated_run_id(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "cfg.yaml",
        "run:\n  output_goal: Ship it.\n"
        f"project:\n  workspace: {tmp_path}\nprovider:\n  name: stub\n",
    )
    real_rename = Path.rename

    def interrupt_before_publish(self, target):
        dest = Path(target)
        if self.name.startswith(".creating-") and dest.name.startswith("run-"):
            raise KeyboardInterrupt
        return real_rename(self, dest)

    argv = ["run", "--config", str(config_path), "--runs-dir", str(tmp_path / "runs")]
    with patch.object(Path, "rename", interrupt_before_publish):
        result = run_cli(argv)
    _assert_no_traceback(result)
    assert result.exit_code == 130
    assert not _run_dirs(tmp_path / "runs")
    text = result.stderr + result.stdout
    assert "Run:" not in text


def test_post_create_observability_failure_includes_published_run_id(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "cfg.yaml",
        "run:\n  output_goal: Ship it.\n"
        f"project:\n  workspace: {tmp_path}\nprovider:\n  name: stub\n",
    )
    argv = [
        "run",
        "--config",
        str(config_path),
        "--runs-dir",
        str(tmp_path / "runs"),
        "--stream-json",
    ]
    with ExitStack() as stack:
        for item in _engine_patches(tmp_path):
            stack.enter_context(item)
        stack.enter_context(
            patch(
                "top_down_planning.cli.user.build_observability_context",
                side_effect=PermissionError("transcript denied"),
            )
        )
        result = run_cli(argv)
    leftover = _run_dirs(tmp_path / "runs")
    assert leftover
    _assert_no_traceback(result)
    payload = _stdout_json(result)
    assert payload["error"]["code"] == "operational_error"
    assert payload.get("run_id") == leftover[0].name


def test_final_load_run_failure_includes_published_run_id(tmp_path: Path) -> None:
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
    real_load = FileRunStore.load_run
    continued = {"done": False}

    def continue_then_mark(*args, **kwargs):
        continued["done"] = True
        return engine.continue_run.return_value

    def load_after_continue(self, rid):
        if continued["done"]:
            raise PersistenceError("canonical read failed")
        return real_load(self, rid)

    engine.continue_run.side_effect = continue_then_mark
    argv = [
        "run",
        "--config",
        str(config_path),
        "--runs-dir",
        str(tmp_path / "runs"),
        "--stream-json",
    ]
    with (
        patch("top_down_planning.cli.user._build_run_engine", return_value=engine),
        patch.object(FileRunStore, "load_run", load_after_continue),
    ):
        result = run_cli(argv)
    leftover = _run_dirs(tmp_path / "runs")
    assert leftover
    payload = _stdout_json(result)
    assert payload["error"]["code"] == "corrupt_run"
    assert payload.get("run_id") == leftover[0].name


def test_parent_execute_ownership_recovers_with_status_not_resume(tmp_path: Path) -> None:
    store, _, package = _built_package(tmp_path)
    engine = MagicMock()
    engine.continue_run.side_effect = RunOwnershipError(
        "owned", code="run_owned_by_live_process"
    )
    argv = [
        "execute",
        "--manifest",
        str(package.manifest_path),
        "--runs-dir",
        str(store.root),
        "--stream-json",
    ]
    with patch("top_down_planning.cli.execute._build_run_engine", return_value=engine):
        result = run_cli(argv)
    leftover = _run_dirs(store.root)
    parents = [
        path.name
        for path in leftover
        if str(FileRunStore(store.root).load_run(path.name).get("run_kind") or "")
        == "parent_execution"
    ]
    _assert_no_traceback(result)
    payload = _stdout_json(result)
    assert payload["error"]["code"] == "run_owned_by_live_process"
    assert payload["recovery"]["command"] == "status"
    assert payload["recovery"]["run_id"] == parents[0]
    assert payload["recovery"]["runs_dir"] == str(store.root)


def test_human_prepare_recovery_includes_store_and_output(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T004003-004003"
    _planning_run_at_validated(store, tmp_path, run_id)
    output = tmp_path / "pkg"
    with patch(
        "top_down_planning.cli.prepare.ExecutionPackageBuilder.build_from_planning_run",
        side_effect=ValueError("materialize failed"),
    ):
        result = run_cli(_planning_argv(tmp_path, run_id, output, ["--replace"]))
    _assert_no_traceback(result)
    text = result.stderr + result.stdout
    assert f"--planning-run {run_id}" in text
    assert f"--runs-dir {store.root}" in text
    assert f"--output {output.resolve()}" in text
    assert "--replace" in text


def test_prepare_replace_cleanup_warning_appears_in_human_success(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T004004-004004"
    _planning_run_at_validated(store, tmp_path, run_id)
    output = tmp_path / "pkg"
    ExecutionPackageBuilder().build_from_planning_run(store, run_id, output_dir=output)
    real_rmtree = __import__("shutil").rmtree

    def fail_backup(path, *args, **kwargs):
        if Path(path).name.startswith(".backup-"):
            raise OSError("backup busy")
        return real_rmtree(path, *args, **kwargs)

    with patch("top_down_planning.package.builder.shutil.rmtree", fail_backup):
        result = run_cli(_planning_argv(tmp_path, run_id, output, ["--replace"]))
    assert result.exit_code == 0
    text = result.stdout + result.stderr
    assert ".backup-" in text
    assert "Prepared package" in text
