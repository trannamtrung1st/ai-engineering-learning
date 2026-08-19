"""Slice 7 re-review regressions for residual 739/744 and TDP-CLI-748–750."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.persistence import PersistenceError
from top_down_planning.domain.resume_plan import ResumePlan, ResumePlanValidation
from top_down_planning.orchestrator.phases import OUTPUT_VALIDATED
from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory
from top_down_planning.package.loader import ExecutionPackageLoader
from top_down_planning.persistence import FileRunStore
from tests.conftest import CliResult, run_cli
from tests.helpers import whole_plan_approval_record, write_config
from tests.unit.test_prepared_runs import _built_package
from tests.unit.test_resume_cli import _create_paused_production_run
from tests.unit.test_slice7_rereview_739_747 import (
    _assert_operational_without_traceback,
    _execute_item_b_argv,
)
from tests.unit.test_slice7_rereview_cli_schema import (
    _create_planning_run,
    _stdout_json,
    _wipe_txn_dirs,
)
from tests.unit.test_sub_tdp_defect_pass import _build_package as _dependent_build_package


def _assert_no_traceback(result: CliResult) -> None:
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr


def _already_completed_plan(run_id: str, revision: int) -> ResumePlan:
    return ResumePlan(
        run_id=run_id,
        expected_run_revision=revision,
        state_transition=None,
        config_changes={},
        session_policy={},
        validation=ResumePlanValidation(
            contract_digest_valid=True,
            plan_binding_valid=True,
            approval_binding_valid=True,
            evidence_binding_valid=True,
            context_binding_valid=True,
        ),
        already_completed=True,
        message="run already completed",
    )


def _fail_load_run_after(flag: dict[str, bool], exc: BaseException):
    real_load = FileRunStore.load_run

    def load_wrapper(self, run_id):
        if flag["armed"]:
            raise exc
        return real_load(self, run_id)

    return load_wrapper


@pytest.mark.parametrize("exc", [PersistenceError("late read"), PermissionError("denied")])
def test_terminal_resume_late_load_run_is_traceback_free(tmp_path: Path, exc: BaseException) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_planning_run(store, "run-20260101T111101-111101")
    run = store.load_run(run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["status"] = "completed"
    run["phase"] = OUTPUT_VALIDATED
    run["outcome"] = "accepted"
    store.save_run(run_id, run, expected)

    armed = {"armed": False}
    real_load = FileRunStore.load_run

    def load_and_arm(self, rid):
        if armed["armed"]:
            raise exc
        record = real_load(self, rid)
        if record.get("status") == "completed":
            armed["armed"] = True
        return record

    argv = ["resume", "--run", run_id, "--runs-dir", str(store.root)]
    with patch.object(FileRunStore, "load_run", load_and_arm):
        structured = run_cli([*argv, "--stream-json"])
        human = run_cli(argv)

    _assert_no_traceback(structured)
    _assert_no_traceback(human)
    assert structured.stdout.strip().startswith("{")
    payload = _stdout_json(structured)
    assert payload["ok"] in {True, False}
    assert payload.get("error", {}).get("code") != "unhandled"
    if structured.exit_code != 0:
        assert payload["ok"] is False
        assert payload["error"]["code"] in {"operational_error", "corrupt_run"}


@pytest.mark.parametrize("exc", [PersistenceError("late read"), PermissionError("denied")])
def test_already_completed_resume_late_load_run_is_traceback_free(
    tmp_path: Path, exc: BaseException
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_paused_production_run(store)
    run = store.load_run(run_id)
    armed = {"armed": False}

    def prepare_wrapper(*args, **kwargs):
        armed["armed"] = True
        return _already_completed_plan(run_id, int(run["revision"]))

    argv = ["resume", "--run", run_id, "--runs-dir", str(store.root)]
    with (
        patch("top_down_planning.cli.user.prepare_resume", prepare_wrapper),
        patch.object(FileRunStore, "load_run", _fail_load_run_after(armed, exc)),
    ):
        structured = run_cli([*argv, "--stream-json"])
        human = run_cli(argv)

    _assert_no_traceback(structured)
    _assert_no_traceback(human)
    assert structured.stdout.strip().startswith("{")
    payload = _stdout_json(structured)
    assert payload["ok"] in {True, False}
    if "error" in payload:
        assert payload["error"]["code"] in {"operational_error", "corrupt_run"}
    else:
        assert payload.get("already_completed") is True


@pytest.mark.parametrize("exc", [PersistenceError("late read"), PermissionError("denied")])
def test_execute_parent_only_late_load_run_is_traceback_free(
    tmp_path: Path, exc: BaseException
) -> None:
    _, _, package = _built_package(tmp_path)
    armed = {"armed": False}
    real_create = PreparedRunFactory.create_parent_run

    def create_wrapper(self, *args, **kwargs):
        run_id = real_create(self, *args, **kwargs)
        armed["armed"] = True
        return run_id

    argv = [
        "execute",
        "--manifest",
        str(package.manifest_path),
        "--parent-only",
        "--runs-dir",
        str(tmp_path / "runs"),
    ]
    with (
        patch(
            "top_down_planning.orchestrator.prepared_run_factory.validate_resolved_config_against_package"
        ),
        patch.object(PreparedRunFactory, "create_parent_run", create_wrapper),
        patch.object(FileRunStore, "load_run", _fail_load_run_after(armed, exc)),
    ):
        structured = run_cli([*argv, "--stream-json"])
        human = run_cli(argv)

    _assert_no_traceback(structured)
    _assert_no_traceback(human)
    assert structured.stdout.strip().startswith("{")
    payload = _stdout_json(structured)
    assert payload["ok"] is False
    assert payload["error"]["code"] in {"operational_error", "corrupt_run"}


def test_validate_approval_mode_uses_snapshot_reviews_not_later_live_reads(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_planning_run(store, "run-20260101T111201-111201")
    store.save_review(run_id, whole_plan_approval_record(store, run_id))
    _wipe_txn_dirs(store.run_dir(run_id))

    real_snapshot = FileRunStore.load_canonical_snapshot

    def snapshot_then_drop_reviews(self, rid):
        snap = real_snapshot(self, rid)
        reviews_dir = self.reviews_dir(rid)
        if reviews_dir.is_dir():
            for path in reviews_dir.glob("*.json"):
                path.unlink()
        return snap

    with patch.object(FileRunStore, "load_canonical_snapshot", snapshot_then_drop_reviews):
        result = run_cli(
            ["validate", "--run", run_id, "--runs-dir", str(store.root), "--stream-json"]
        )

    _assert_no_traceback(result)
    payload = _stdout_json(result)
    assert payload["plan"]["mode"] == "approval"


def test_validate_approval_digests_use_snapshot_config_not_later_live_config(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_planning_run(store, "run-20260101T111202-111202")
    store.save_review(run_id, whole_plan_approval_record(store, run_id))
    _wipe_txn_dirs(store.run_dir(run_id))
    baseline = run_cli(
        ["validate", "--run", run_id, "--runs-dir", str(store.root), "--stream-json"]
    )
    baseline_payload = _stdout_json(baseline)
    baseline_codes = [issue["code"] for issue in baseline_payload["plan"]["issues"]]

    real_snapshot = FileRunStore.load_canonical_snapshot

    def snapshot_then_rewrite_config(self, rid):
        snap = real_snapshot(self, rid)
        config_path = self.run_dir(rid) / "resolved-config.yaml"
        config_path.write_text("version: 1\nrun:\n  output_goal: Drifted goal.\n", encoding="utf-8")
        return snap

    with patch.object(FileRunStore, "load_canonical_snapshot", snapshot_then_rewrite_config):
        result = run_cli(
            ["validate", "--run", run_id, "--runs-dir", str(store.root), "--stream-json"]
        )

    _assert_no_traceback(result)
    payload = _stdout_json(result)
    assert payload["plan"]["mode"] == baseline_payload["plan"]["mode"]
    assert [issue["code"] for issue in payload["plan"]["issues"]] == baseline_codes


def _run_or_prepare_argv(command: str, config_path: Path, runs_dir: Path) -> list[str]:
    argv = [command, "--config", str(config_path), "--runs-dir", str(runs_dir)]
    if command == "prepare":
        argv.extend(["--output", str(runs_dir.parent / "pkg")])
    return argv


@pytest.mark.parametrize("command", ["run", "prepare"])
def test_output_goal_file_permission_error_is_operational(tmp_path: Path, command: str) -> None:
    goal = tmp_path / "goal.md"
    goal.write_text("Deliver from file.\n", encoding="utf-8")
    config_path = write_config(
        tmp_path / "cfg.yaml",
        f"run:\n  output_goal_file: goal.md\nproject:\n  workspace: {tmp_path}\nprovider:\n  name: stub\n",
    )
    original = Path.read_text

    def _read_text(self: Path, *args, **kwargs):
        if self.resolve() == goal.resolve():
            raise PermissionError("denied")
        return original(self, *args, **kwargs)

    argv = _run_or_prepare_argv(command, config_path, tmp_path / "runs")
    with patch.object(Path, "read_text", _read_text):
        structured = run_cli([*argv, "--stream-json"])
        human = run_cli(argv)
    _assert_operational_without_traceback(structured)
    _assert_no_traceback(human)
    assert structured.stdout.strip().startswith("{")


@pytest.mark.parametrize("command", ["run", "prepare"])
def test_output_goal_file_invalid_utf8_is_config_error(tmp_path: Path, command: str) -> None:
    goal = tmp_path / "goal.md"
    goal.write_bytes(b"\xff\xfe")
    config_path = write_config(
        tmp_path / "cfg.yaml",
        f"run:\n  output_goal_file: goal.md\nproject:\n  workspace: {tmp_path}\nprovider:\n  name: stub\n",
    )
    argv = _run_or_prepare_argv(command, config_path, tmp_path / "runs")
    structured = run_cli([*argv, "--stream-json"])
    human = run_cli(argv)
    assert structured.exit_code == 2
    payload = _stdout_json(structured)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "config_error"
    _assert_no_traceback(structured)
    _assert_no_traceback(human)


@pytest.mark.parametrize("command", ["run", "prepare"])
def test_guidance_file_permission_error_is_operational(tmp_path: Path, command: str) -> None:
    guide = tmp_path / "guide.md"
    guide.write_text("Be careful.\n", encoding="utf-8")
    config_path = write_config(
        tmp_path / "cfg.yaml",
        (
            f"run:\n  output_goal: Goal.\nproject:\n  workspace: {tmp_path}\n"
            "provider:\n  name: stub\nagent_context:\n  default:\n    guidance:\n"
            "      - file: guide.md\n"
        ),
    )
    original = Path.read_text

    def _read_text(self: Path, *args, **kwargs):
        if self.resolve() == guide.resolve():
            raise PermissionError("denied")
        return original(self, *args, **kwargs)

    argv = _run_or_prepare_argv(command, config_path, tmp_path / "runs")
    with patch.object(Path, "read_text", _read_text):
        structured = run_cli([*argv, "--stream-json"])
        human = run_cli(argv)
    _assert_operational_without_traceback(structured)
    _assert_no_traceback(human)
    assert structured.stdout.strip().startswith("{")


@pytest.mark.parametrize("command", ["run", "prepare"])
def test_guidance_file_invalid_utf8_is_config_error(tmp_path: Path, command: str) -> None:
    guide = tmp_path / "guide.md"
    guide.write_bytes(b"\xff\xfe")
    config_path = write_config(
        tmp_path / "cfg.yaml",
        (
            f"run:\n  output_goal: Goal.\nproject:\n  workspace: {tmp_path}\n"
            "provider:\n  name: stub\nagent_context:\n  default:\n    guidance:\n"
            "      - file: guide.md\n"
        ),
    )
    argv = _run_or_prepare_argv(command, config_path, tmp_path / "runs")
    structured = run_cli([*argv, "--stream-json"])
    human = run_cli(argv)
    assert structured.exit_code == 2
    payload = _stdout_json(structured)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "config_error"
    _assert_no_traceback(structured)
    _assert_no_traceback(human)


@pytest.mark.parametrize("method", ["load_run", "load_production", "load_plan_model"])
def test_explicit_upstream_permission_error_is_operational(
    tmp_path: Path, method: str
) -> None:
    store, output_dir, _ = _dependent_build_package(tmp_path)
    package = ExecutionPackageLoader().load(output_dir, verify_workspace=False)
    unit_a = package.units["item-a"]
    dep_id = PreparedRunFactory().create_child_run(
        store,
        package,
        unit_a,
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
    )
    real = getattr(FileRunStore, method)

    def wrapper(self, run_id, *args, **kwargs):
        if run_id == dep_id:
            raise PermissionError("denied")
        return real(self, run_id, *args, **kwargs)

    argv = _execute_item_b_argv(package, store, ["--upstream", f"item-a={dep_id}"])
    with patch.object(FileRunStore, method, wrapper):
        structured = run_cli(argv)
        human = run_cli(argv[:-1])
    _assert_operational_without_traceback(structured)
    _assert_no_traceback(human)


def test_explicit_baseline_permission_error_is_operational(tmp_path: Path) -> None:
    store, output_dir, _ = _dependent_build_package(tmp_path)
    package = ExecutionPackageLoader().load(output_dir, verify_workspace=False)
    unit_a = package.units["item-a"]
    baseline_id = PreparedRunFactory().create_child_run(
        store,
        package,
        unit_a,
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
    )
    real_load = FileRunStore.load_run

    def wrapper(self, run_id):
        if run_id == baseline_id:
            raise PermissionError("denied")
        return real_load(self, run_id)

    argv = _execute_item_b_argv(
        package,
        store,
        ["--upstream", f"item-a={baseline_id}", "--baseline", baseline_id],
    )
    with patch.object(FileRunStore, "load_run", wrapper):
        structured = run_cli(argv)
    _assert_operational_without_traceback(structured)


def test_status_missing_production_does_not_call_a_planning_run_parent(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_planning_run(store, "run-20260101T111301-111301")
    (store.run_dir(run_id) / "production.json").unlink()
    _wipe_txn_dirs(store.run_dir(run_id))
    structured = run_cli(
        ["status", "--run", run_id, "--runs-dir", str(store.root), "--stream-json"]
    )
    human = run_cli(["status", "--run", run_id, "--runs-dir", str(store.root)])
    assert structured.exit_code == 1
    payload = _stdout_json(structured)
    assert payload["error"]["code"] == "corrupt_run"
    assert "parent execution run" not in payload["error"]["message"]
    assert "parent execution run" not in human.stdout
    assert "parent execution run" not in human.stderr
    _assert_no_traceback(structured)
    _assert_no_traceback(human)
