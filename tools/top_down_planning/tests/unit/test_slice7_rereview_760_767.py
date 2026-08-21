"""Slice 7 re-review regressions for TDP-CLI-760 residual and 765–767."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.persistence import PersistenceError
from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory
from top_down_planning.orchestrator.prepared_unit_executor import PreparedUnitExecutor
from top_down_planning.package.loader import ExecutionPackageError, ExecutionPackageLoader
from top_down_planning.persistence import FileRunStore
from tests.conftest import run_cli
from tests.helpers import accept_child_run, write_config
from tests.support.cli_fakes import _engine_patches, _patch_prepare_plan_validated
from tests.support.cli_fakes import _assert_operational_without_traceback
from tests.unit.test_slice7_rereview_739_747 import (
    _dependent_build_package,
    _execute_item_b_argv,
)
from tests.support.cli_fakes import _assert_no_traceback, _resume_check_argv
from tests.support.cli_fakes import _assert_structured_error, _stdout_json
from tests.unit.test_slice7_rereview_760_764 import (
    _bump_after_first_child_load,
    _pause_child_for_resume,
)


def _load_dependent_package(tmp_path: Path):
    store, output_dir, _ = _dependent_build_package(tmp_path)
    package = ExecutionPackageLoader().load(output_dir, verify_workspace=False)
    return store, package


def _accepted_item_a(tmp_path: Path):
    store, package = _load_dependent_package(tmp_path)
    child_id = PreparedRunFactory().create_child_run(
        store,
        package,
        package.units["item-a"],
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
    )
    accept_child_run(store, child_id)
    return store, package, child_id


def _execute_item_a_argv(package, store: FileRunStore, extra: list[str] | None = None) -> list[str]:
    return [
        "execute",
        "--manifest",
        str(package.manifest_path),
        "--unit",
        "item-a",
        "--runs-dir",
        str(store.root),
        *(extra or []),
        "--stream-json",
    ]


def test_execute_terminal_child_reuse_uses_one_child_snapshot(tmp_path: Path) -> None:
    store, package, child_id = _accepted_item_a(tmp_path)
    before = store.load_canonical_snapshot(child_id)
    before_rev = int(before.run["revision"])
    bump_after_child_read, snapshot_then_bump = _bump_after_first_child_load(child_id)

    def reuse_child(self, *args, **kwargs):
        return child_id

    argv = _execute_item_a_argv(package, store)
    with (
        patch.object(PreparedUnitExecutor, "create_or_load_child_run", reuse_child),
        patch.object(FileRunStore, "load_run", bump_after_child_read),
        patch.object(FileRunStore, "load_canonical_snapshot", snapshot_then_bump),
    ):
        result = run_cli(argv)

    _assert_no_traceback(result)
    payload = _stdout_json(result)
    assert payload.get("error", {}).get("code") != "sub_tdp_lineage_mismatch"
    assert result.exit_code == 0
    assert payload["run_id"] == child_id
    after = store.load_canonical_snapshot(child_id)
    observed = int(payload.get("run_revision") or after.run["revision"])
    assert observed in {before_rev, before_rev + 1}
    assert int(after.run["revision"]) in {before_rev, before_rev + 1}


@pytest.mark.parametrize(
    "exc, code",
    [
        (
            ExecutionPackageError("terminal delivery invalid", code="sub_tdp_lineage_mismatch"),
            "sub_tdp_lineage_mismatch",
        ),
        (PersistenceError("corrupt terminal child"), "corrupt_run"),
        (PermissionError("denied"), "operational_error"),
    ],
)
@pytest.mark.parametrize("stream_json", [True, False])
def test_execute_drive_errors_use_cli_normalization_boundary(
    tmp_path: Path, exc: BaseException, code: str, stream_json: bool
) -> None:
    store, package = _load_dependent_package(tmp_path)
    argv = _execute_item_a_argv(package, store)
    if not stream_json:
        argv = argv[:-1]

    def raise_drive(self, *args, **kwargs):
        raise exc

    with patch.object(PreparedUnitExecutor, "drive_child_run", raise_drive):
        result = run_cli(argv)

    _assert_no_traceback(result)
    assert result.exit_code == 1
    if stream_json:
        _assert_structured_error(result, code)
    elif code == "operational_error":
        _assert_operational_without_traceback(result)
    else:
        assert "Traceback" not in result.stdout + result.stderr


def _deny_bound_package_reload():
    real = ExecutionPackageLoader.load

    def wrapper(self, output_dir, verify_workspace=True, **kwargs):
        if verify_workspace is False:
            raise PermissionError("denied")
        return real(self, output_dir, verify_workspace=verify_workspace, **kwargs)

    return patch.object(ExecutionPackageLoader, "load", wrapper)


def test_resume_bound_manifest_permission_error_is_operational(tmp_path: Path) -> None:
    store, package, child_id = _accepted_item_a(tmp_path)
    child_b = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        "item-b",
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
        explicit_upstream={"item-a": child_id},
        explicit_upstream_only=True,
    )
    _pause_child_for_resume(store, child_b)
    argv = _resume_check_argv(child_b, store.root)
    with _deny_bound_package_reload():
        structured = run_cli([*argv, "--stream-json"])
        human = run_cli(argv)
    _assert_operational_without_traceback(structured)
    _assert_no_traceback(human)
    text = structured.stdout + structured.stderr + human.stdout + human.stderr
    assert "resume_preparation_blocked" not in text
    assert "sub_tdp_upstream_invalid" not in text
    assert "missing manifest_path" not in text


def test_execute_bound_manifest_permission_error_is_operational(tmp_path: Path) -> None:
    store, package, child_id = _accepted_item_a(tmp_path)
    argv = _execute_item_b_argv(package, store, ["--upstream", f"item-a={child_id}"])
    with _deny_bound_package_reload():
        structured = run_cli(argv)
        human = run_cli(argv[:-1])
    _assert_operational_without_traceback(structured)
    _assert_no_traceback(human)
    text = structured.stdout + structured.stderr + human.stdout + human.stderr
    assert "sub_tdp_upstream_invalid" not in text
    assert "missing manifest_path" not in text


@pytest.mark.parametrize("command", ["run", "prepare"])
@pytest.mark.parametrize("stream_json", [True, False])
def test_create_survives_post_publish_event_append_failure(
    tmp_path: Path, command: str, stream_json: bool
) -> None:
    config_path = write_config(
        tmp_path / "cfg.yaml",
        "run:\n  output_goal: Ship it.\n"
        f"project:\n  workspace: {tmp_path}\nprovider:\n  name: stub\n",
    )
    argv = [command, "--config", str(config_path), "--runs-dir", str(tmp_path / "runs")]
    if command == "prepare":
        argv.extend(["--output", str(tmp_path / "pkg")])
    if stream_json:
        argv.append("--stream-json")

    with ExitStack() as stack:
        stack.enter_context(
            patch.object(
                FileRunStore,
                "append_event",
                side_effect=PersistenceError("post-create event failed"),
            )
        )
        for item in _engine_patches(tmp_path):
            stack.enter_context(item)
        if command == "prepare":
            stack.enter_context(_patch_prepare_plan_validated())
        result = run_cli(argv)

    leftover = [
        path
        for path in (tmp_path / "runs").iterdir()
        if path.is_dir() and path.name.startswith("run-")
    ]
    assert leftover
    run_id = leftover[0].name
    events = FileRunStore(tmp_path / "runs").load_events(run_id)
    assert any(event.get("type") == "context_snapshot_collected" for event in events)
    _assert_no_traceback(result)
    if stream_json:
        payload = _stdout_json(result)
        assert payload.get("error", {}).get("code") != "corrupt_run"
        assert (
            payload.get("run_id") == run_id
            or payload.get("planning_run_id") == run_id
            or payload.get("ok") is True
        )
    assert result.exit_code == 0


@pytest.mark.parametrize("command", ["run", "prepare"])
def test_create_survives_creation_lock_cleanup_oserror(
    tmp_path: Path, command: str
) -> None:
    config_path = write_config(
        tmp_path / "cfg.yaml",
        "run:\n  output_goal: Ship it.\n"
        f"project:\n  workspace: {tmp_path}\nprovider:\n  name: stub\n",
    )
    argv = [
        command,
        "--config",
        str(config_path),
        "--runs-dir",
        str(tmp_path / "runs"),
        "--stream-json",
    ]
    if command == "prepare":
        argv.extend(["--output", str(tmp_path / "pkg")])
    real_unlink = Path.unlink

    def unlink_lock(self: Path, *args, **kwargs):
        if self.name.startswith(".creating-") and self.name.endswith(".lock"):
            raise PermissionError("denied")
        return real_unlink(self, *args, **kwargs)

    with ExitStack() as stack:
        stack.enter_context(patch.object(Path, "unlink", unlink_lock))
        for item in _engine_patches(tmp_path):
            stack.enter_context(item)
        if command == "prepare":
            stack.enter_context(_patch_prepare_plan_validated())
        result = run_cli(argv)

    leftover = [
        path
        for path in (tmp_path / "runs").iterdir()
        if path.is_dir() and path.name.startswith("run-")
    ]
    _assert_no_traceback(result)
    assert leftover
    payload = _stdout_json(result)
    assert payload.get("error", {}).get("code") != "operational_error"
    assert result.exit_code == 0
    assert (
        payload.get("run_id") == leftover[0].name
        or payload.get("planning_run_id") == leftover[0].name
        or payload.get("ok") is True
    )
