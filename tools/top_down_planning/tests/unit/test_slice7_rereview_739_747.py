"""Slice 7 re-review regressions for TDP-CLI-739 residual and 743–747."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core_tools.persistence import PersistenceError
from top_down_planning.orchestrator.engine import RunContinuationResult
from top_down_planning.orchestrator.phases import PLAN_VALIDATED, PRODUCTION
from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory
from top_down_planning.orchestrator.prepared_unit_executor import PreparedUnitExecutor
from top_down_planning.package.loader import ExecutionPackageLoader
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.commit import CommitSpec
from tests.conftest import CliResult, run_cli
from tests.helpers import accept_child_run, create_run_kwargs, write_config
from tests.support.run_builders import _built_package
from tests.support.run_builders import _create_paused_production_run
from tests.support.run_builders import _create_planning_run
from tests.support.cli_fakes import _stdout_json
from tests.support.run_builders import _parent_with_orchestration
from tests.support.run_builders import _build_package as _dependent_build_package
from tests.support.cli_fakes import _assert_operational_without_traceback


def _fail_load_run_after_continue(continue_fn):
    continued = {"done": False}
    real_load = FileRunStore.load_run
    real_snapshot = FileRunStore.load_canonical_snapshot

    def continue_wrapper(*args, **kwargs):
        result = continue_fn(*args, **kwargs)
        continued["done"] = True
        return result

    def load_wrapper(self, run_id):
        if continued["done"]:
            continued["done"] = False
            raise PermissionError("denied")
        return real_load(self, run_id)

    def snapshot_wrapper(self, run_id):
        if continued["done"]:
            continued["done"] = False
            raise PermissionError("denied")
        return real_snapshot(self, run_id)

    return continue_wrapper, load_wrapper, snapshot_wrapper


def test_run_final_load_run_oserror_is_operational_not_traceback(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "run.yaml",
        "run:\n  output_goal: Goal.\nprovider:\n  name: stub\n",
    )
    continuation = RunContinuationResult(
        ok=True,
        run_id="pending",
        phase="planning",
        status="running",
        outcome=None,
        cancelled=False,
        target_reached=True,
    )
    engine = MagicMock()
    continue_wrapper, load_wrapper, _snapshot_wrapper = _fail_load_run_after_continue(
        lambda *args, **kwargs: continuation
    )
    engine.continue_run.side_effect = continue_wrapper

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
        patch.object(FileRunStore, "load_run", load_wrapper),
    ):
        structured = run_cli(argv)
        human = run_cli(argv[:-1])
    _assert_operational_without_traceback(structured)
    _assert_operational_without_traceback(human)


def test_resume_final_load_run_oserror_is_operational_not_traceback(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_paused_production_run(store)
    continuation = RunContinuationResult(
        ok=True,
        run_id=run_id,
        phase=PRODUCTION,
        status="running",
        outcome=None,
        cancelled=False,
        target_reached=False,
    )
    engine = MagicMock()
    continue_wrapper, load_wrapper, _snapshot_wrapper = _fail_load_run_after_continue(
        lambda *args, **kwargs: continuation
    )
    engine.continue_run.side_effect = continue_wrapper

    argv = ["resume", "--run", run_id, "--runs-dir", str(store.root), "--stream-json"]
    with (
        patch("top_down_planning.cli.user.apply_resume_plan_atomically"),
        patch("top_down_planning.cli.user._build_run_engine", return_value=engine),
        patch.object(FileRunStore, "load_run", load_wrapper),
    ):
        structured = run_cli(argv)
        human = run_cli(argv[:-1])
    _assert_operational_without_traceback(structured)
    _assert_operational_without_traceback(human)


def test_prepare_final_load_run_oserror_is_operational_not_traceback(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "prep.yaml",
        "run:\n  output_goal: Goal.\nprovider:\n  name: stub\n",
    )
    runs_dir = tmp_path / "runs"
    output_dir = tmp_path / "pkg"
    built = SimpleNamespace(
        package_id="pkg-prepare-1",
        manifest_path=output_dir / "manifest.json",
        manifest={
            "planning_run": {
                "approved_plan_revision": 0,
                "approved_plan_digest": "a" * 64,
            }
        },
    )
    continuation = SimpleNamespace(cancelled=False, reason=None)

    def _continue(run_id: str, until: str = "validated"):
        store = FileRunStore(runs_dir)
        run = FileRunStore.load_run(store, run_id)
        expected = int(run["revision"])
        run = dict(run)
        run["revision"] = expected + 1
        run["phase"] = PLAN_VALIDATED
        store.save_run(run_id, run, expected)
        return continuation

    engine = MagicMock()
    continue_wrapper, load_wrapper, snapshot_wrapper = _fail_load_run_after_continue(_continue)
    engine.continue_run.side_effect = continue_wrapper

    argv = [
        "prepare",
        "--config",
        str(config_path),
        "--runs-dir",
        str(runs_dir),
        "--output",
        str(output_dir),
        "--stream-json",
    ]
    with (
        patch("top_down_planning.cli.prepare._build_run_engine", return_value=engine),
        patch(
            "top_down_planning.cli.prepare.ExecutionPackageBuilder.build_from_planning_run",
            return_value=built,
        ),
        patch.object(FileRunStore, "load_run", load_wrapper),
        patch.object(FileRunStore, "load_canonical_snapshot", snapshot_wrapper),
    ):
        structured = run_cli(argv)
        human = run_cli(argv[:-1])
    _assert_operational_without_traceback(structured)
    _assert_operational_without_traceback(human)


def test_execute_final_load_run_oserror_is_operational_not_traceback(tmp_path: Path) -> None:
    store, _, package = _built_package(tmp_path)
    continuation = RunContinuationResult(
        ok=True,
        run_id="pending",
        phase=PLAN_VALIDATED,
        status="running",
        outcome=None,
        cancelled=False,
        target_reached=True,
    )
    engine = MagicMock()
    continue_wrapper, load_wrapper, _snapshot_wrapper = _fail_load_run_after_continue(
        lambda *args, **kwargs: continuation
    )
    engine.continue_run.side_effect = continue_wrapper

    argv = [
        "execute",
        "--manifest",
        str(package.manifest_path),
        "--runs-dir",
        str(store.root),
        "--stream-json",
    ]
    with (
        patch("top_down_planning.cli.execute._build_run_engine", return_value=engine),
        patch.object(FileRunStore, "load_run", load_wrapper),
    ):
        structured = run_cli(argv)
        human = run_cli(argv[:-1])
    _assert_operational_without_traceback(structured)
    _assert_operational_without_traceback(human)


def test_cancelled_run_still_exits_130_when_final_load_run_fails(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_paused_production_run(store)
    continuation = RunContinuationResult(
        ok=False,
        run_id=run_id,
        phase=PRODUCTION,
        status="paused",
        outcome=None,
        cancelled=True,
        target_reached=False,
        reason="cancelled by user",
    )
    engine = MagicMock()
    continue_wrapper, load_wrapper, _snapshot_wrapper = _fail_load_run_after_continue(
        lambda *args, **kwargs: continuation
    )
    engine.continue_run.side_effect = continue_wrapper

    argv = ["resume", "--run", run_id, "--runs-dir", str(store.root), "--stream-json"]
    with (
        patch("top_down_planning.cli.user.apply_resume_plan_atomically"),
        patch("top_down_planning.cli.user._build_run_engine", return_value=engine),
        patch.object(FileRunStore, "load_run", load_wrapper),
    ):
        structured = run_cli(argv)

    assert structured.exit_code == 130
    payload = _stdout_json(structured)
    assert payload["ok"] is False
    assert payload["cancelled"] is True
    assert "Traceback" not in structured.stdout
    assert "Traceback" not in structured.stderr

    continue_wrapper, load_wrapper, _snapshot_wrapper = _fail_load_run_after_continue(
        lambda *args, **kwargs: continuation
    )
    engine.continue_run.side_effect = continue_wrapper
    with (
        patch("top_down_planning.cli.user.apply_resume_plan_atomically"),
        patch("top_down_planning.cli.user._build_run_engine", return_value=engine),
        patch.object(FileRunStore, "load_run", load_wrapper),
    ):
        human = run_cli(["resume", "--run", run_id, "--runs-dir", str(store.root)])

    assert human.exit_code == 130
    assert "Traceback" not in human.stdout
    assert "Traceback" not in human.stderr


def test_command_interrupt_still_exits_130_when_final_load_run_fails(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_paused_production_run(store)
    engine = MagicMock()
    interrupted = {"v": False}

    def _interrupt(*args, **kwargs):
        interrupted["v"] = True
        raise KeyboardInterrupt

    engine.continue_run.side_effect = _interrupt
    real_load = FileRunStore.load_run
    after = {"n": 0}

    def load_wrapper(self, rid):
        if interrupted["v"]:
            after["n"] += 1
            if after["n"] >= 2:
                raise PermissionError("denied")
        return real_load(self, rid)

    argv = ["resume", "--run", run_id, "--runs-dir", str(store.root), "--stream-json"]
    with (
        patch("top_down_planning.cli.user.apply_resume_plan_atomically"),
        patch("top_down_planning.cli.user._build_run_engine", return_value=engine),
        patch.object(FileRunStore, "load_run", load_wrapper),
    ):
        structured = run_cli(argv)

    assert structured.exit_code == 130
    payload = _stdout_json(structured)
    assert payload["ok"] is False
    assert "Traceback" not in structured.stdout
    assert "Traceback" not in structured.stderr


@pytest.mark.parametrize("target", ["manifest.json", "parent/plan.json"])
def test_execute_package_permission_error_is_operational(tmp_path: Path, target: str) -> None:
    _, _, package = _built_package(tmp_path)
    original = Path.read_text

    def _read_text(self: Path, *args, **kwargs):
        if self.as_posix().endswith(target):
            raise PermissionError("denied")
        return original(self, *args, **kwargs)

    argv = [
        "execute",
        "--manifest",
        str(package.manifest_path),
        "--runs-dir",
        str(tmp_path / "runs"),
        "--stream-json",
    ]
    with patch.object(Path, "read_text", _read_text):
        structured = run_cli(argv)
        human = run_cli(argv[:-1])
    _assert_operational_without_traceback(structured)
    _assert_operational_without_traceback(human)


def test_execute_malformed_manifest_remains_package_invalid(tmp_path: Path) -> None:
    _, _, package = _built_package(tmp_path)
    package.manifest_path.write_text("{not-json", encoding="utf-8")
    result = run_cli(
        [
            "execute",
            "--manifest",
            str(package.manifest_path),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--stream-json",
        ]
    )
    assert result.exit_code == 1
    payload = _stdout_json(result)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "package_json_invalid"
    assert "Traceback" not in result.stdout


@pytest.mark.parametrize("target", ["manifest.json", "parent/plan.json"])
def test_attach_package_permission_error_is_operational(tmp_path: Path, target: str) -> None:
    store, parent_id, package, _config = _parent_with_orchestration(tmp_path)
    child_id = PreparedRunFactory().create_child_run(
        store,
        package,
        package.units["item-foundation"],
        resolved_config=create_run_kwargs(tmp_path)["resolved_config"],
        invocation={"command": "execute"},
    )
    original = Path.read_text

    def _read_text(self: Path, *args, **kwargs):
        if self.as_posix().endswith(target):
            raise PermissionError("denied")
        return original(self, *args, **kwargs)

    argv = [
        "sub-tdp",
        "attach",
        "--parent",
        parent_id,
        "--child",
        child_id,
        "--runs-dir",
        str(store.root),
        "--stream-json",
    ]
    with patch.object(Path, "read_text", _read_text):
        structured = run_cli(argv)
        human = run_cli(argv[:-1])
    _assert_operational_without_traceback(structured)
    _assert_operational_without_traceback(human)


def test_attach_malformed_manifest_remains_attach_rejected(tmp_path: Path) -> None:
    store, parent_id, package, _config = _parent_with_orchestration(tmp_path)
    child_id = PreparedRunFactory().create_child_run(
        store,
        package,
        package.units["item-foundation"],
        resolved_config=create_run_kwargs(tmp_path)["resolved_config"],
        invocation={"command": "execute"},
    )
    Path(package.manifest_path).write_text("{not-json", encoding="utf-8")
    result = run_cli(
        [
            "sub-tdp",
            "attach",
            "--parent",
            parent_id,
            "--child",
            child_id,
            "--runs-dir",
            str(store.root),
            "--stream-json",
        ]
    )
    assert result.exit_code == 1
    payload = _stdout_json(result)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "sub_tdp_attach_rejected"
    assert "Traceback" not in result.stdout


def _inject_commit_after_first_lock(store: FileRunStore, run_id: str):
    real_with = FileRunStore._with_recovered_run
    injected = {"done": False, "in_bump": False}

    from top_down_planning.domain.models import Plan
    from top_down_planning.persistence.digests import compute_plan_digest

    def bump() -> None:
        run = store.load_run(run_id)
        plan = store.load_plan(run_id)
        next_run = dict(run)
        next_run["revision"] = int(run["revision"]) + 1
        next_plan = dict(plan)
        next_plan["revision"] = int(plan["revision"]) + 1
        digests = dict(next_run.get("digests") or {})
        digests["plan"] = compute_plan_digest(Plan.from_dict(next_plan))
        next_run["digests"] = digests
        store.commit(
            run_id,
            CommitSpec(
                run=next_run,
                run_expected_revision=int(run["revision"]),
                plan=next_plan,
                plan_expected_revision=int(plan["revision"]),
            ),
        )

    @contextmanager
    def wrapped(self, rid: str):
        with real_with(self, rid) as validated:
            yield validated
        if injected["in_bump"] or injected["done"] or rid != run_id:
            return
        injected["done"] = True
        injected["in_bump"] = True
        try:
            bump()
        finally:
            injected["in_bump"] = False

    return wrapped


@pytest.mark.parametrize("command", ["status", "inspect", "validate"])
def test_observation_commands_do_not_mix_pre_and_post_commit_snapshots(
    tmp_path: Path, command: str
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_planning_run(store, "run-20260101T101001-101001")
    before_run = store.load_run(run_id)
    before_plan = store.load_plan(run_id)
    pre = (int(before_run["revision"]), int(before_plan["revision"]))
    post = (pre[0] + 1, pre[1] + 1)

    argv = [command, "--run", run_id, "--runs-dir", str(store.root), "--stream-json"]
    with patch.object(
        FileRunStore, "_with_recovered_run", _inject_commit_after_first_lock(store, run_id)
    ):
        result = run_cli(argv)

    assert result.exit_code == 0
    payload = _stdout_json(result)
    if command == "status":
        observed = (
            int(payload["run"]["revision"]),
            int(payload["run"]["plan_revision"]),
        )
        assert observed in {pre, post}
    elif command == "inspect":
        observed_plan = int(payload["revision"])
        assert observed_plan in {pre[1], post[1]}
    else:
        observed_plan = int(payload["plan"]["revision"])
        assert observed_plan in {pre[1], post[1]}


def _corrupt_artifact(run_dir: Path, name: str) -> None:
    (run_dir / name).write_text("{not-json", encoding="utf-8")


def _execute_item_b_argv(package, store: FileRunStore, extra: list[str]) -> list[str]:
    return [
        "execute",
        "--manifest",
        str(package.manifest_path),
        "--unit",
        "item-b",
        "--runs-dir",
        str(store.root),
        *extra,
        "--stream-json",
    ]


@pytest.mark.parametrize("artifact", ["run.json", "plan.json", "production.json"])
def test_execute_explicit_upstream_corrupt_artifacts_are_stable_errors(
    tmp_path: Path, artifact: str
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
    _corrupt_artifact(store.run_dir(dep_id), artifact)
    argv = _execute_item_b_argv(
        package, store, ["--upstream", f"item-a={dep_id}"]
    )
    structured = run_cli(argv)
    human = run_cli(argv[:-1])
    assert structured.exit_code == 1
    payload = _stdout_json(structured)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "corrupt_run"
    assert "Traceback" not in structured.stdout
    assert "Traceback" not in structured.stderr
    assert human.exit_code == 1
    assert "Traceback" not in human.stdout
    assert "Traceback" not in human.stderr


def test_execute_explicit_baseline_corrupt_run_is_stable_error(tmp_path: Path) -> None:
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
    _corrupt_artifact(store.run_dir(baseline_id), "run.json")
    argv = _execute_item_b_argv(
        package,
        store,
        ["--upstream", f"item-a={baseline_id}", "--baseline", baseline_id],
    )
    # Upstream itself is also corrupt; either upstream or baseline classification is stable.
    structured = run_cli(argv)
    assert structured.exit_code == 1
    payload = _stdout_json(structured)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "corrupt_run"
    assert "Traceback" not in structured.stdout


def _write_unrelated_corrupt_run(store: FileRunStore) -> None:
    bad_id = "run-20260101T109999-109999"
    run_dir = store.root / bad_id
    run_dir.mkdir()
    (run_dir / "run.json").write_text("{not-json", encoding="utf-8")


def test_unrelated_corrupt_run_does_not_hide_discovery_access_errors(tmp_path: Path) -> None:
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
    accept_child_run(store, dep_id)
    _write_unrelated_corrupt_run(store)
    argv = _execute_item_b_argv(package, store, [])
    result = run_cli(argv)
    assert result.exit_code == 1
    payload = _stdout_json(result)
    assert payload["error"]["code"] == "corrupt_run"


def test_unrelated_corrupt_run_does_not_skip_creation_key_discovery(tmp_path: Path) -> None:
    store, output_dir, _ = _dependent_build_package(tmp_path)
    package = ExecutionPackageLoader().load(output_dir, verify_workspace=False)
    parent_id = PreparedRunFactory().create_parent_run(
        store,
        package,
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
    )
    first = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        "item-a",
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
        parent_run_id=parent_id,
    )
    before_ids = {path.name for path in store.root.iterdir() if path.name.startswith("run-")}
    _write_unrelated_corrupt_run(store)
    with pytest.raises(PersistenceError):
        PreparedUnitExecutor().create_or_load_child_run(
            store,
            package,
            "item-a",
            resolved_config=package.resolved_config,
            invocation={"command": "execute"},
            parent_run_id=parent_id,
        )
    after_ids = {path.name for path in store.root.iterdir() if path.name.startswith("run-")}
    assert after_ids == before_ids | {"run-20260101T109999-109999"}
    assert first in after_ids


def test_explicit_corrupt_upstream_is_rejected_not_skipped(tmp_path: Path) -> None:
    store, output_dir, _ = _dependent_build_package(tmp_path)
    package = ExecutionPackageLoader().load(output_dir, verify_workspace=False)
    bad_id = "run-20260101T109998-109998"
    run_dir = store.root / bad_id
    run_dir.mkdir()
    (run_dir / "run.json").write_text("{not-json", encoding="utf-8")
    argv = _execute_item_b_argv(package, store, ["--upstream", f"item-a={bad_id}"])
    result = run_cli(argv)
    assert result.exit_code == 1
    payload = _stdout_json(result)
    assert payload["error"]["code"] == "corrupt_run"


def test_unreadable_config_file_is_operational_error(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "run.yaml",
        "run:\n  output_goal: Goal.\nprovider:\n  name: stub\n",
    )
    original = Path.read_text

    def _read_text(self: Path, *args, **kwargs):
        if self.resolve() == config_path.resolve():
            raise PermissionError("denied")
        return original(self, *args, **kwargs)

    argv = [
        "run",
        "--config",
        str(config_path),
        "--runs-dir",
        str(tmp_path / "runs"),
        "--stream-json",
    ]
    with patch.object(Path, "read_text", _read_text):
        structured = run_cli(argv)
        human = run_cli(argv[:-1])
    _assert_operational_without_traceback(structured)
    _assert_operational_without_traceback(human)


def test_malformed_config_yaml_remains_config_error(tmp_path: Path) -> None:
    config_path = write_config(tmp_path / "bad.yaml", "run: [\n")
    result = run_cli(
        [
            "run",
            "--config",
            str(config_path),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--stream-json",
        ]
    )
    assert result.exit_code == 2
    payload = _stdout_json(result)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "config_error"
    assert "Traceback" not in result.stdout
