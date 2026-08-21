"""Slice 7 re-review regressions for TDP-CLI-784–790 and residual 775/776/779/789."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core_tools.persistence import PersistenceError, RunNotFoundError, StoreRevisionConflictError
from top_down_planning.domain.run_kind import RUN_KIND_PARENT_EXECUTION, RUN_KIND_PLANNING
from top_down_planning.orchestrator.engine import RunContinuationResult
from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory
from top_down_planning.package.builder import ExecutionPackageBuilder
from top_down_planning.package.loader import ExecutionPackageError, ExecutionPackageLoader
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.commit import CommitSpec, StoreAuthorizationConflictError
from top_down_planning.persistence.snapshot_bindings import bind_run_digests_for_plan_update
from tests.conftest import run_cli
from tests.helpers import create_run_kwargs, whole_plan_approval_record, write_config
from tests.support.run_builders import _approved_parent_plan, _planning_run_at_validated
from tests.support.run_builders import _built_package
from tests.support.cli_fakes import _assert_no_traceback
from tests.support.cli_fakes import _assert_structured_error, _stdout_json
from tests.support.cli_fakes import _engine_patches
from tests.support.cli_fakes import _patch_prepare_plan_validated
from tests.unit.test_slice7_rereview_768_774 import _run_dirs


def _planning_argv(tmp_path: Path, run_id: str, output: Path, extra: list[str] | None = None) -> list[str]:
    return [
        "prepare",
        "--planning-run",
        run_id,
        "--runs-dir",
        str(tmp_path / "runs"),
        "--output",
        str(output),
        *(extra or []),
    ]


def test_prepare_replace_interrupt_before_publish_restores_prior_package(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T002001-002001"
    _planning_run_at_validated(store, tmp_path, run_id)
    output = tmp_path / "pkg"
    first = ExecutionPackageBuilder().build_from_planning_run(store, run_id, output_dir=output)
    prior_id = first.package_id
    real_rename = Path.rename
    seen = {"n": 0}

    def interrupt_before_promote(self, target):
        seen["n"] += 1
        if seen["n"] == 2:
            raise KeyboardInterrupt
        return real_rename(self, target)

    argv = _planning_argv(tmp_path, run_id, output, ["--replace", "--stream-json"])
    with patch.object(Path, "rename", interrupt_before_promote):
        result = run_cli(argv)
    _assert_no_traceback(result)
    assert result.exit_code == 130
    payload = _stdout_json(result)
    assert payload.get("ok") is False
    assert (output / "manifest.json").is_file()
    reloaded = ExecutionPackageLoader().load(output, verify_workspace=False)
    assert reloaded.manifest["package_id"] == prior_id
    leftovers = [p for p in output.parent.iterdir() if p.name.startswith(".backup-") or p.name.startswith(".staging-")]
    assert leftovers == []


def test_prepare_replace_interrupt_after_publish_keeps_new_package(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T002002-002002"
    _planning_run_at_validated(store, tmp_path, run_id)
    output = tmp_path / "pkg"
    ExecutionPackageBuilder().build_from_planning_run(store, run_id, output_dir=output)
    prior_id = ExecutionPackageLoader().load(output, verify_workspace=False).manifest["package_id"]
    real_rmtree = __import__("shutil").rmtree

    def interrupt_backup_cleanup(path, *args, **kwargs):
        if Path(path).name.startswith(".backup-"):
            raise KeyboardInterrupt
        return real_rmtree(path, *args, **kwargs)

    argv = _planning_argv(tmp_path, run_id, output, ["--replace", "--stream-json"])
    with patch("top_down_planning.package.builder.shutil.rmtree", interrupt_backup_cleanup):
        result = run_cli(argv)
    _assert_no_traceback(result)
    assert result.exit_code == 0
    payload = _stdout_json(result)
    assert payload["ok"] is True
    assert payload["package_id"] != prior_id
    reloaded = ExecutionPackageLoader().load(output, verify_workspace=False)
    assert reloaded.manifest["package_id"] == payload["package_id"]


@pytest.mark.parametrize("stream_json", [True, False])
def test_create_run_interrupt_cleans_staging(tmp_path: Path, stream_json: bool) -> None:
    config_path = write_config(
        tmp_path / "cfg.yaml",
        "run:\n  output_goal: Ship it.\n"
        f"project:\n  workspace: {tmp_path}\nprovider:\n  name: stub\n",
    )
    argv = ["run", "--config", str(config_path), "--runs-dir", str(tmp_path / "runs")]
    if stream_json:
        argv.append("--stream-json")
    real_rename = Path.rename

    def interrupt_publish(self, target):
        if ".creating-" in self.name and Path(target).name.startswith("run-"):
            raise KeyboardInterrupt
        return real_rename(self, target)

    with patch.object(Path, "rename", interrupt_publish):
        result = run_cli(argv)
    _assert_no_traceback(result)
    assert result.exit_code == 130
    leftover = [
        path
        for path in (tmp_path / "runs").iterdir()
        if path.name.startswith(".creating-") or path.name.startswith("run-")
    ]
    assert leftover == []


def test_parent_execute_emits_package_error_not_traceback(tmp_path: Path) -> None:
    _, _, package = _built_package(tmp_path)
    store = FileRunStore(tmp_path / "runs")
    factory = PreparedRunFactory()
    factory._create_prepared_run(
        store,
        package,
        plan=package.parent_plan,
        run_kind=RUN_KIND_PARENT_EXECUTION,
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
        selected_unit_id=None,
        unit_record=None,
    )
    factory._create_prepared_run(
        store,
        package,
        plan=package.parent_plan,
        run_kind=RUN_KIND_PARENT_EXECUTION,
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
        selected_unit_id=None,
        unit_record=None,
    )
    argv = [
        "execute",
        "--manifest",
        str(package.manifest_path),
        "--runs-dir",
        str(store.root),
        "--stream-json",
    ]
    result = run_cli(argv)
    _assert_no_traceback(result)
    assert result.exit_code == 1
    payload = _stdout_json(result)
    assert payload["error"]["code"] == "sub_tdp_ambiguous_upstream"


@pytest.mark.parametrize(
    "exc, code",
    [
        (StoreRevisionConflictError(1, 2), "run_revision_conflict"),
        (StoreAuthorizationConflictError("token revoked"), "store_authorization_conflict"),
    ],
)
@pytest.mark.parametrize("stream_json", [True, False])
def test_parent_only_conflicts_are_not_corrupt_run(
    tmp_path: Path, exc: BaseException, code: str, stream_json: bool
) -> None:
    _, _, package = _built_package(tmp_path)
    argv = [
        "execute",
        "--manifest",
        str(package.manifest_path),
        "--parent-only",
        "--runs-dir",
        str(tmp_path / "runs"),
    ]
    if stream_json:
        argv.append("--stream-json")
    with patch.object(FileRunStore, "save_run", side_effect=exc):
        result = run_cli(argv)
    leftover = _run_dirs(tmp_path / "runs")
    store = FileRunStore(tmp_path / "runs")
    parents = [
        path.name
        for path in leftover
        if str(store.load_run(path.name).get("run_kind") or "") == RUN_KIND_PARENT_EXECUTION
    ]
    _assert_no_traceback(result)
    assert result.exit_code == 1
    assert parents
    if stream_json:
        _assert_structured_error(result, code)
        payload = _stdout_json(result)
        assert payload.get("run_id") == parents[0]
        assert payload.get("recovery", {}).get("command") == "status"
    else:
        assert "corrupt_run" not in result.stdout + result.stderr


@pytest.mark.parametrize("planning_run_flag", [False, True])
@pytest.mark.parametrize(
    "exc, code",
    [
        (RunNotFoundError("run-missing", "gone"), "run_not_found"),
        (PersistenceError("unreadable snapshot"), "corrupt_run"),
        (StoreRevisionConflictError(3, 4), "run_revision_conflict"),
    ],
)
def test_prepare_materialize_persistence_errors_are_normalized(
    tmp_path: Path, planning_run_flag: bool, exc: BaseException, code: str
) -> None:
    run_id = "run-20260101T002003-002003"
    if planning_run_flag:
        store = FileRunStore(tmp_path / "runs")
        _planning_run_at_validated(store, tmp_path, run_id)
    config_path = write_config(
        tmp_path / "cfg.yaml",
        "run:\n  output_goal: Ship it.\n"
        f"project:\n  workspace: {tmp_path}\nprovider:\n  name: stub\n",
    )
    if planning_run_flag:
        argv = _planning_argv(tmp_path, run_id, tmp_path / "pkg", ["--stream-json"])
    else:
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
    real_snapshot = FileRunStore.load_canonical_snapshot

    def fail_snapshot(self, rid):
        raise exc

    with ExitStack() as stack:
        if not planning_run_flag:
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
            stack.enter_context(
                patch("top_down_planning.cli.prepare._build_run_engine", return_value=engine)
            )
            stack.enter_context(_patch_prepare_plan_validated())
            stack.enter_context(patch.object(FileRunStore, "load_canonical_snapshot", fail_snapshot))
        else:
            stack.enter_context(patch.object(FileRunStore, "load_canonical_snapshot", fail_snapshot))
        result = run_cli(argv)
    _assert_no_traceback(result)
    assert result.exit_code == 1
    payload = _stdout_json(result)
    assert payload["error"]["code"] == code
    leftover = _run_dirs(tmp_path / "runs")
    expected_id = run_id if planning_run_flag else leftover[0].name
    assert payload.get("planning_run_id") == expected_id or payload.get("run_id") == expected_id


def test_prepare_incomplete_identifies_run_and_resume_recovery(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "cfg.yaml",
        "run:\n  output_goal: Ship it.\n"
        f"project:\n  workspace: {tmp_path}\nprovider:\n  name: stub\n",
    )
    engine = MagicMock()
    engine.continue_run.return_value = RunContinuationResult(
        ok=False,
        run_id="pending",
        phase="planning",
        status="paused",
        outcome=None,
        reason="review pending",
        cancelled=False,
        target_reached=False,
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
    with ExitStack() as stack:
        for item in _engine_patches(tmp_path):
            stack.enter_context(item)
        stack.enter_context(patch("top_down_planning.cli.prepare._build_run_engine", return_value=engine))
        result = run_cli(argv)
    leftover = _run_dirs(tmp_path / "runs")
    assert leftover
    run_id = leftover[0].name
    _assert_no_traceback(result)
    payload = _stdout_json(result)
    assert payload["error"]["code"] == "prepare_incomplete"
    assert payload.get("planning_run_id") == run_id or payload.get("run_id") == run_id
    assert payload.get("recovery", {}).get("command") == "resume"


def test_prepare_planning_run_works_without_config_file(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T002004-002004"
    _planning_run_at_validated(store, tmp_path, run_id)
    result = run_cli(_planning_argv(tmp_path, run_id, tmp_path / "pkg", ["--stream-json"]))
    _assert_no_traceback(result)
    assert result.exit_code == 0
    payload = _stdout_json(result)
    assert payload["ok"] is True
    assert payload["planning_run_id"] == run_id
    assert (tmp_path / "pkg" / "manifest.json").is_file()


def test_prepare_rejects_non_file_input_ref(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    config = create_run_kwargs(tmp_path)["resolved_config"]
    config["run"]["input_refs"] = ["docs/missing-spec.md"]
    kwargs = create_run_kwargs(tmp_path, resolved_config=config)
    run_id = "run-20260101T002005-002005"
    store.create_run(
        run_id,
        plan=_approved_parent_plan(run_id),
        phase="plan_validated",
        run_extras={"run_kind": RUN_KIND_PLANNING},
        **kwargs,
    )
    store.save_review(run_id, whole_plan_approval_record(store, run_id))
    missing = tmp_path / "docs" / "missing-spec.md"
    if missing.is_file():
        missing.unlink()
    result = run_cli(_planning_argv(tmp_path, run_id, tmp_path / "pkg", ["--stream-json"]))
    _assert_no_traceback(result)
    assert result.exit_code == 1
    payload = _stdout_json(result)
    assert payload["error"]["code"] == "package_build_failed"
    assert not (tmp_path / "pkg").exists()


def test_prepare_replace_backup_cleanup_failure_still_succeeds(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T002006-002006"
    _planning_run_at_validated(store, tmp_path, run_id)
    output = tmp_path / "pkg"
    ExecutionPackageBuilder().build_from_planning_run(store, run_id, output_dir=output)
    real_rmtree = __import__("shutil").rmtree

    def fail_backup_cleanup(path, *args, **kwargs):
        if Path(path).name.startswith(".backup-"):
            raise OSError("backup busy")
        return real_rmtree(path, *args, **kwargs)

    with patch("top_down_planning.package.builder.shutil.rmtree", fail_backup_cleanup):
        result = run_cli(_planning_argv(tmp_path, run_id, output, ["--replace", "--stream-json"]))
    _assert_no_traceback(result)
    assert result.exit_code == 0
    payload = _stdout_json(result)
    assert payload["ok"] is True
    assert ExecutionPackageLoader().load(output, verify_workspace=False).manifest["package_id"] == payload["package_id"]


def test_prepare_planning_run_materializes_precheck_snapshot_not_later_revision(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T002007-002007"
    _planning_run_at_validated(store, tmp_path, run_id)
    original = store.load_canonical_snapshot(run_id)
    original_revision = original.plan["revision"]
    real_snapshot = FileRunStore.load_canonical_snapshot
    calls = {"n": 0}

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

    with patch.object(FileRunStore, "load_canonical_snapshot", snapshot_then_bump):
        result = run_cli(_planning_argv(tmp_path, run_id, tmp_path / "pkg", ["--stream-json"]))
    _assert_no_traceback(result)
    assert result.exit_code == 0
    payload = _stdout_json(result)
    package = ExecutionPackageLoader().load(tmp_path / "pkg", verify_workspace=False)
    assert payload["plan_revision"] == original_revision
    assert package.manifest["planning_run"]["approved_plan_revision"] == original_revision
    assert store.load_plan(run_id)["revision"] != original_revision


def test_corrupt_run_recovery_is_doctor_not_resume(tmp_path: Path) -> None:
    engine = MagicMock()
    engine.continue_run.side_effect = PersistenceError("journal torn")
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
        stack.enter_context(patch("top_down_planning.cli.user._build_run_engine", return_value=engine))
        result = run_cli(argv)
    leftover = _run_dirs(tmp_path / "runs")
    assert leftover
    run_id = leftover[0].name
    payload = _stdout_json(result)
    assert payload["error"]["code"] == "corrupt_run"
    assert payload.get("recovery", {}).get("command") == "doctor"
    assert payload.get("recovery", {}).get("run_id") == run_id
