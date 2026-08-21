"""Slice 7 re-review regressions for TDP-CLI-755–758."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core_tools.persistence import PersistenceError, RunNotFoundError
from core_tools.persistence.digests import digest_text
from core_tools.persistence.digests import digest_file as real_digest_file
from top_down_planning.orchestrator.engine import RunContinuationResult
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.commit import CommitSpec
from top_down_planning.persistence.snapshot_bindings import bind_run_digests_for_plan_update
from tests.conftest import CliResult, run_cli
from tests.helpers import write_config
from tests.support.run_builders import _built_package
from tests.support.run_builders import _create_paused_production_run
from tests.support.cli_fakes import _assert_operational_without_traceback
from tests.support.cli_fakes import (
    _assert_no_traceback,
    _assert_structured_error,
    _resume_check_argv,
    _stdout_json,
)


def _publish_valid_plan_run_revision(store: FileRunStore, run_id: str) -> None:
    run = store.load_run(run_id)
    plan = store.load_plan(run_id)
    new_plan = dict(plan)
    new_plan["revision"] = int(plan["revision"]) + 1
    new_run = bind_run_digests_for_plan_update(dict(run), new_plan)
    new_run["revision"] = int(run["revision"]) + 1
    store.commit(
        run_id,
        CommitSpec(
            run=new_run,
            run_expected_revision=int(run["revision"]),
            plan=new_plan,
            plan_expected_revision=int(plan["revision"]),
        ),
    )


def _assert_no_canonical_run(runs_dir: Path) -> None:
    if not runs_dir.exists():
        return
    leftover = [path for path in runs_dir.iterdir() if path.is_dir() and path.name.startswith("run-")]
    assert leftover == []


def test_resume_check_uses_one_canonical_snapshot_across_plan_run_bump(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_paused_production_run(store)
    before_run = store.load_run(run_id)
    before_rev = int(before_run["revision"])
    before_plan_digest = str(before_run["digests"]["plan"])

    from top_down_planning.cli.user import prepare_resume as real_prepare

    def prepare_after_valid_bump(store_obj, rid, candidate, consumed_limits=None, **kwargs):
        _publish_valid_plan_run_revision(store_obj, rid)
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
    with patch("top_down_planning.cli.user.prepare_resume", prepare_after_valid_bump):
        result = run_cli(argv)

    _assert_no_traceback(result)
    after = store.load_run(run_id)
    after_rev = int(after["revision"])
    after_plan_digest = str(after["digests"]["plan"])
    assert after_rev == before_rev + 1
    assert after_plan_digest != before_plan_digest

    payload = _stdout_json(result)
    assert payload.get("error", {}).get("code") != "resume_preparation_blocked"
    assert result.exit_code == 0
    assert "error" not in payload
    validation = payload["validation"]
    assert validation["plan_binding_valid"] is True
    expected_rev = int(payload["expected_run_revision"])
    assert expected_rev in {before_rev, after_rev}


def test_resume_check_prepared_plan_uses_snapshot_instead_of_plan_reload(
    tmp_path: Path,
) -> None:
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
            raise PersistenceError("corrupt plan")
        return real_load(self, run_id)

    argv = _resume_check_argv(parent_id, tmp_path / "runs")
    with patch.object(FileRunStore, "load_plan_model", load_plan):
        structured = run_cli([*argv, "--stream-json"])
        human = run_cli(argv)

    _assert_no_traceback(structured)
    _assert_no_traceback(human)
    assert structured.exit_code == 0
    assert human.exit_code == 0
    assert "resume_preparation_blocked" not in structured.stdout
    assert _stdout_json(structured).get("error", {}).get("code") != "corrupt_run"


def _file_reads_a_then_b(target: Path, version_a: str, version_b: str):
    original = Path.read_text

    def read_text(self: Path, *args, **kwargs):
        if self.resolve() == target.resolve():
            counts["n"] = int(counts["n"]) + 1
            if int(counts["n"]) == 1:
                return version_a
            return version_b
        return original(self, *args, **kwargs)

    counts = {"n": 0}
    return read_text, counts


def _engine_patches(tmp_path: Path):
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
    return [
        patch("top_down_planning.cli.user._build_run_engine", return_value=engine),
        patch("top_down_planning.cli.prepare._build_run_engine", return_value=engine),
        patch(
            "top_down_planning.cli.prepare.ExecutionPackageBuilder.build_from_planning_run",
            return_value=SimpleNamespace(
                package_id="pkg-x",
                manifest_path=tmp_path / "pkg" / "manifest.json",
                manifest={
                    "planning_run": {
                        "approved_plan_revision": 0,
                        "approved_plan_digest": "a" * 64,
                    }
                },
            ),
        ),
    ]


@pytest.mark.parametrize("command", ["run", "prepare"])
@pytest.mark.parametrize("stream_json", [True, False])
def test_create_run_output_goal_drift_is_stable_error(
    tmp_path: Path, command: str, stream_json: bool
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
    read_text, _counts = _file_reads_a_then_b(
        goal, "Goal version A.\n", "Goal version B.\n"
    )

    def create_wrapper(self, run_id, **kwargs):
        captured["plan_goal"] = kwargs["plan"].output_goal
        captured["digest"] = kwargs["output_goal_digest"]
        return real_create(self, run_id, **kwargs)

    argv = [command, "--config", str(config_path), "--runs-dir", str(tmp_path / "runs")]
    if command == "prepare":
        argv.extend(["--output", str(tmp_path / "pkg")])
    if stream_json:
        argv.append("--stream-json")
    with ExitStack() as stack:
        stack.enter_context(patch.object(Path, "read_text", read_text))
        stack.enter_context(patch.object(FileRunStore, "create_run", create_wrapper))
        for item in _engine_patches(tmp_path):
            stack.enter_context(item)
        result = run_cli(argv)

    _assert_no_traceback(result)
    assert captured["plan_goal"].strip() == "Goal version A."
    assert captured["digest"] == digest_text(captured["plan_goal"])
    assert result.exit_code != 0
    if stream_json:
        payload = _stdout_json(result)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "creation_snapshot_changed"
    _assert_no_canonical_run(tmp_path / "runs")


@pytest.mark.parametrize("command", ["run", "prepare"])
@pytest.mark.parametrize("stream_json", [True, False])
def test_create_run_input_ref_drift_is_stable_error(
    tmp_path: Path, command: str, stream_json: bool
) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("alpha", encoding="utf-8")
    config_path = write_config(
        tmp_path / "cfg.yaml",
        "run:\n  output_goal: Ship it.\n  input_refs:\n    - README.md\n"
        f"project:\n  workspace: {tmp_path}\nprovider:\n  name: stub\n",
    )
    read_text, _counts = _file_reads_a_then_b(readme, "alpha", "beta")
    digest_calls = {"n": 0}

    def digest_file_wrapper(path):
        if Path(path).resolve() == readme.resolve():
            digest_calls["n"] = int(digest_calls["n"]) + 1
            if int(digest_calls["n"]) == 1:
                return digest_text("alpha")
            return digest_text("beta")
        return real_digest_file(path)

    argv = [command, "--config", str(config_path), "--runs-dir", str(tmp_path / "runs")]
    if command == "prepare":
        argv.extend(["--output", str(tmp_path / "pkg")])
    if stream_json:
        argv.append("--stream-json")
    with ExitStack() as stack:
        stack.enter_context(patch.object(Path, "read_text", read_text))
        stack.enter_context(
            patch("core_tools.config.merge.digest_file", digest_file_wrapper)
        )
        for item in _engine_patches(tmp_path):
            stack.enter_context(item)
        result = run_cli(argv)

    _assert_no_traceback(result)
    assert result.exit_code != 0
    if stream_json:
        payload = _stdout_json(result)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "creation_snapshot_changed"
    _assert_no_canonical_run(tmp_path / "runs")


@pytest.mark.parametrize(
    "exc, code",
    [
        (PersistenceError("corrupt run.json"), "corrupt_run"),
        (RunNotFoundError("run-missing", "deleted"), "run_not_found"),
        (PermissionError("denied"), "operational_error"),
    ],
)
@pytest.mark.parametrize("stream_json", [True, False])
def test_resume_apply_persistence_errors_keep_run_access_codes(
    tmp_path: Path,
    exc: BaseException,
    code: str,
    stream_json: bool,
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_paused_production_run(store)
    prepared = {"done": False}
    from top_down_planning.cli.user import prepare_resume as real_prepare

    def prepare_then_mark(*args, **kwargs):
        result = real_prepare(*args, **kwargs)
        prepared["done"] = True
        return result

    real_load = FileRunStore.load_run

    def load_run_after_prepare(self, rid):
        if prepared["done"]:
            raise exc
        return real_load(self, rid)

    argv = ["resume", "--run", run_id, "--runs-dir", str(store.root)]
    if stream_json:
        argv.append("--stream-json")
    with (
        patch("top_down_planning.cli.user.prepare_resume", prepare_then_mark),
        patch.object(FileRunStore, "load_run", load_run_after_prepare),
    ):
        result = run_cli(argv)

    if stream_json:
        if code == "operational_error":
            _assert_operational_without_traceback(result)
        else:
            _assert_structured_error(result, code)
    else:
        _assert_no_traceback(result)
        assert result.exit_code != 0
