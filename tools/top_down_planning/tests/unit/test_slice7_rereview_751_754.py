"""Slice 7 re-review regressions for TDP-CLI-751–754."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core_tools.persistence.digests import digest_text
from top_down_planning.cli.execute import _resolved_config_for_execute
from top_down_planning.config import ConfigError
from top_down_planning.orchestrator.engine import RunContinuationResult
from top_down_planning.orchestrator.phases import OUTPUT_VALIDATED
from top_down_planning.orchestrator.prepared_unit_executor import PreparedUnitExecutor
from top_down_planning.persistence import FileRunStore
from tests.conftest import CliResult, run_cli
from tests.helpers import accept_child_run, write_config
from tests.unit.test_prepared_runs import _built_package
from tests.unit.test_resume_cli import _create_paused_production_run
from tests.unit.test_slice7_rereview_739_747 import _assert_operational_without_traceback
from tests.unit.test_slice7_rereview_cli_schema import (
    _create_planning_run,
    _stdout_json,
)
from tests.unit.test_sub_tdp_attach_cli import _parent_with_orchestration


def _assert_no_traceback(result: CliResult) -> None:
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr


def test_terminal_resume_ok_status_outcome_share_one_run_revision(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_planning_run(store, "run-20260101T121101-121101")
    run = store.load_run(run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["status"] = "completed"
    run["phase"] = OUTPUT_VALIDATED
    run["outcome"] = "accepted"
    store.save_run(run_id, run, expected)

    real_load = FileRunStore.load_run
    mutated = {"done": False}

    def load_then_mutate_disk(self, rid):
        record = real_load(self, rid)
        if record.get("outcome") == "accepted" and not mutated["done"]:
            mutated["done"] = True
            updated = dict(record)
            updated["revision"] = int(record["revision"]) + 1
            updated["outcome"] = "rejected"
            self.save_run(rid, updated, int(record["revision"]))
        return record

    argv = ["resume", "--run", run_id, "--runs-dir", str(store.root), "--stream-json"]
    with patch.object(FileRunStore, "load_run", load_then_mutate_disk):
        result = run_cli(argv)

    _assert_no_traceback(result)
    payload = _stdout_json(result)
    ok = payload["ok"]
    outcome = payload["outcome"]
    assert not (ok is True and outcome == "rejected")
    if ok is True:
        assert payload["status"] == "completed"
        assert outcome == "accepted"
        assert result.exit_code == 0
    elif outcome == "rejected":
        assert ok is False
        assert result.exit_code == 1


def test_resume_check_consumed_limits_match_expected_run_revision(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_paused_production_run(store)
    before = store.load_run(run_id)
    before_rev = int(before["revision"])
    before_consumed = int(before["stop"]["details"]["consumed"])

    from top_down_planning.cli.user import prepare_resume as real_prepare

    def prepare_after_mutation(store_obj, rid, candidate, consumed_limits=None, **kwargs):
        current = store_obj.load_run(rid)
        updated = dict(current)
        updated["revision"] = int(current["revision"]) + 1
        stop = dict(updated["stop"])
        details = dict(stop["details"])
        details["consumed"] = before_consumed + 1
        stop["details"] = details
        updated["stop"] = stop
        store_obj.save_run(rid, updated, int(current["revision"]))
        return real_prepare(
            store_obj,
            rid,
            candidate,
            consumed_limits=consumed_limits,
            **kwargs,
        )

    argv = [
        "resume",
        "--run",
        run_id,
        "--runs-dir",
        str(store.root),
        "--check",
        "--stream-json",
    ]
    with patch("top_down_planning.cli.user.prepare_resume", prepare_after_mutation):
        result = run_cli(argv)

    _assert_no_traceback(result)
    payload = _stdout_json(result)
    expected_revision = int(payload["expected_run_revision"])
    consumed_rows = [
        row
        for row in payload.get("limit_diagnostics") or []
        if row.get("path") == "limits.production.max_batches"
    ]
    assert consumed_rows
    consumed = consumed_rows[0]["consumed"]
    coherent = {
        (before_rev, before_consumed),
        (before_rev + 1, before_consumed + 1),
    }
    assert (expected_revision, consumed) in coherent


def _resume_check_argv(run_id: str, runs_dir: Path) -> list[str]:
    return ["resume", "--run", run_id, "--runs-dir", str(runs_dir), "--check"]


def test_resume_evidence_permission_error_is_operational(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_paused_production_run(store)
    argv = _resume_check_argv(run_id, store.root)
    with (
        patch(
            "top_down_planning.domain.production.live_output_evidence_entries",
            return_value=[{"id": "ev-1", "snapshot_ref": "artifacts/x/y.bin", "sha256": "ab"}],
        ),
        patch(
            "top_down_planning.orchestrator.prepare_resume.verify_evidence_snapshot",
            side_effect=PermissionError("denied"),
        ),
    ):
        structured = run_cli([*argv, "--stream-json"])
        human = run_cli(argv)
    _assert_operational_without_traceback(structured)
    _assert_no_traceback(human)
    assert structured.stdout.strip().startswith("{")


def test_resume_prepared_plan_permission_error_is_operational(tmp_path: Path) -> None:
    _, _, package = _built_package(tmp_path)
    with patch(
        "top_down_planning.orchestrator.prepared_run_factory.validate_resolved_config_against_package"
    ):
        created = run_cli(
            [
                "execute",
                "--manifest",
                str(package.manifest_path),
                "--parent-only",
                "--runs-dir",
                str(tmp_path / "runs"),
                "--stream-json",
            ]
        )
    parent_id = _stdout_json(created)["run_id"]
    real_load = FileRunStore.load_plan_model

    def load_plan(self, run_id):
        if run_id == parent_id:
            raise PermissionError("denied")
        return real_load(self, run_id)

    argv = _resume_check_argv(parent_id, tmp_path / "runs")
    with patch.object(FileRunStore, "load_plan_model", load_plan):
        structured = run_cli([*argv, "--stream-json"])
        human = run_cli(argv)
    _assert_no_traceback(structured)
    _assert_no_traceback(human)
    assert structured.exit_code == 0
    assert human.exit_code == 0


def _attached_parent_and_child(tmp_path: Path) -> tuple[FileRunStore, str, str]:
    store, parent_id, package, config = _parent_with_orchestration(tmp_path)
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
    attached = run_cli(
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
            str(store.root),
            "--stream-json",
        ]
    )
    assert attached.exit_code == 0, attached.stderr
    return store, parent_id, child_id


def test_resume_parent_child_permission_error_is_operational(tmp_path: Path) -> None:
    store, parent_id, child_id = _attached_parent_and_child(tmp_path)
    real = FileRunStore.load_canonical_snapshot

    def wrapper(self, run_id, *args, **kwargs):
        if run_id == child_id:
            raise PermissionError("denied")
        return real(self, run_id, *args, **kwargs)

    argv = _resume_check_argv(parent_id, store.root)
    with patch.object(FileRunStore, "load_canonical_snapshot", wrapper):
        structured = run_cli([*argv, "--stream-json"])
        human = run_cli(argv)
    _assert_operational_without_traceback(structured)
    _assert_no_traceback(human)


def _goal_reads_a_then_b(goal: Path):
    original = Path.read_text
    counts: dict[str, object] = {"n": 0}

    def read_text(self: Path, *args, **kwargs):
        if self.resolve() == goal.resolve():
            counts["n"] = int(counts["n"]) + 1
            if counts["n"] == 1:
                return "Goal version A.\n"
            return "Goal version B.\n"
        return original(self, *args, **kwargs)

    return read_text, counts


@pytest.mark.parametrize("command", ["run", "prepare"])
def test_create_output_goal_text_and_digest_share_one_file_version(
    tmp_path: Path, command: str
) -> None:
    goal = tmp_path / "goal.md"
    goal.write_text("Goal version A.\n", encoding="utf-8")
    config_path = write_config(
        tmp_path / "cfg.yaml",
        f"run:\n  output_goal_file: goal.md\nproject:\n  workspace: {tmp_path}\n"
        "provider:\n  name: stub\n",
    )
    captured: dict = {}
    real_create = FileRunStore.create_run

    engine = MagicMock()
    engine.continue_run.return_value = RunContinuationResult(
        ok=True,
        run_id="run-placeholder",
        phase="planning",
        status="running",
        outcome=None,
        reason=None,
        cancelled=False,
        target_reached=True,
    )
    argv = [command, "--config", str(config_path), "--runs-dir", str(tmp_path / "runs")]
    if command == "prepare":
        argv.extend(["--output", str(tmp_path / "pkg")])
    read_text, _counts = _goal_reads_a_then_b(goal)

    def create_wrapper(self, run_id, **kwargs):
        captured["plan_goal"] = kwargs["plan"].output_goal
        captured["digest"] = kwargs["output_goal_digest"]
        return real_create(self, run_id, **kwargs)

    with (
        patch.object(Path, "read_text", read_text),
        patch.object(FileRunStore, "create_run", create_wrapper),
        patch("top_down_planning.cli.user._build_run_engine", return_value=engine),
        patch("top_down_planning.cli.prepare._build_run_engine", return_value=engine),
        patch(
            "top_down_planning.cli.prepare.ExecutionPackageBuilder.build_from_planning_run",
            return_value=SimpleNamespace(
                package_id="pkg-x",
                manifest_path=tmp_path / "pkg" / "manifest.json",
            ),
        ),
    ):
        result = run_cli(argv)

    _assert_no_traceback(result)
    assert "plan_goal" in captured
    assert captured["digest"] == digest_text(captured["plan_goal"])
    assert captured["plan_goal"].strip() == "Goal version A."
    assert result.exit_code != 0
    leftover = [
        path
        for path in (tmp_path / "runs").iterdir()
        if path.is_dir() and path.name.startswith("run-")
    ] if (tmp_path / "runs").exists() else []
    assert leftover == []


@pytest.mark.parametrize(
    "yaml_body",
    [
        "foo: {}\n",
        "run: {}\n",
        "observability:\n  unexpected: {}\n",
    ],
)
def test_execute_config_rejects_empty_unknown_mappings(tmp_path: Path, yaml_body: str) -> None:
    overlay = write_config(tmp_path / "overlay.yaml", yaml_body)
    with pytest.raises(ConfigError, match="not allowed"):
        _resolved_config_for_execute(
            Namespace(config=str(overlay), set=None),
            SimpleNamespace(resolved_config={"observability": {"log_level": "normal"}}),
        )

    _, _, package = _built_package(tmp_path)
    overlay_cli = write_config(tmp_path / "overlay-cli.yaml", yaml_body)
    argv = [
        "execute",
        "--manifest",
        str(package.manifest_path),
        "--config",
        str(overlay_cli),
        "--parent-only",
        "--runs-dir",
        str(tmp_path / "runs"),
    ]
    structured = run_cli([*argv, "--stream-json"])
    human = run_cli(argv)
    assert structured.exit_code == 2
    payload = _stdout_json(structured)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "config_error"
    _assert_no_traceback(structured)
    _assert_no_traceback(human)
    assert human.exit_code == 2
