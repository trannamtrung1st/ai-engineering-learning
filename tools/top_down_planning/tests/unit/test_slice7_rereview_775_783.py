"""Slice 7 re-review regressions for TDP-CLI-775–783."""

from __future__ import annotations

import multiprocessing
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core_tools.persistence import PersistenceError, RunNotFoundError, StoreRevisionConflictError
from top_down_planning.domain.run_kind import RUN_KIND_PARENT_EXECUTION, RUN_KIND_PLANNING, RUN_KIND_SUB_TDP_EXECUTION
from top_down_planning.domain.run_ownership import RunOwnershipError
from top_down_planning.orchestrator.engine import RunContinuationResult
from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory
from top_down_planning.orchestrator.prepared_unit_executor import PreparedUnitExecutor
from top_down_planning.orchestrator.sub_tdp_child_driver import PreparedChildResult
from top_down_planning.package.builder import ExecutionPackageBuilder
from top_down_planning.package.loader import ExecutionPackageLoader
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.commit import StoreAuthorizationConflictError
from tests.conftest import run_cli
from tests.helpers import create_run_kwargs, write_config
from tests.unit.test_execution_package import _approved_parent_plan, _planning_run_at_validated
from tests.unit.test_prepared_runs import _built_package
from tests.unit.test_slice7_rereview_739_747 import (
    _assert_operational_without_traceback,
    _dependent_build_package,
)
from tests.unit.test_slice7_rereview_751_754 import _assert_no_traceback
from tests.unit.test_slice7_rereview_755_758 import _assert_structured_error, _stdout_json
from tests.unit.test_slice7_rereview_760_764 import _engine_patches, _pause_child_for_resume
from tests.unit.test_slice7_rereview_760_767 import _patch_prepare_plan_validated
from tests.unit.test_slice7_rereview_768_774 import (
    _publish_valid_paused_production_revision,
    _run_dirs,
)


def _create_parent_race_worker(runs_dir: str, manifest: str, barrier, queue) -> None:
    from pathlib import Path as WorkerPath

    from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory
    from top_down_planning.package.loader import ExecutionPackageLoader
    from top_down_planning.persistence import FileRunStore

    store = FileRunStore(WorkerPath(runs_dir))
    package = ExecutionPackageLoader().load(
        WorkerPath(manifest).parent, verify_workspace=False
    )
    barrier.wait()
    run_id = PreparedRunFactory().create_parent_run(
        store,
        package,
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
    )
    queue.put(run_id)


def test_package_builder_rejects_live_input_drift_after_snapshot(tmp_path: Path) -> None:
    spec = tmp_path / "docs" / "spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("approved bytes\n", encoding="utf-8")
    store = FileRunStore(tmp_path / "runs")
    config = create_run_kwargs(tmp_path)["resolved_config"]
    config["run"]["input_refs"] = ["docs/spec.md"]
    kwargs = create_run_kwargs(tmp_path, resolved_config=config)
    run_id = "run-20260101T001001-001001"
    store.create_run(
        run_id,
        plan=_approved_parent_plan(run_id),
        phase="plan_validated",
        run_extras={"run_kind": RUN_KIND_PLANNING},
        **kwargs,
    )
    from tests.helpers import whole_plan_approval_record

    store.save_review(run_id, whole_plan_approval_record(store, run_id))
    real_snapshot = FileRunStore.load_canonical_snapshot

    def snapshot_then_mutate(self, rid):
        snapshot = real_snapshot(self, rid)
        spec.write_text("changed after approval\n", encoding="utf-8")
        return snapshot

    output_dir = tmp_path / "pkg"
    with patch.object(FileRunStore, "load_canonical_snapshot", snapshot_then_mutate):
        with pytest.raises(ValueError, match="input"):
            ExecutionPackageBuilder().build_from_planning_run(
                store, run_id, output_dir=output_dir
            )
    assert not output_dir.exists()


def test_concurrent_parent_create_publishes_exactly_one_run(tmp_path: Path) -> None:
    _, _, package = _built_package(tmp_path)
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(2)
    queue = ctx.Queue()
    workers = [
        ctx.Process(
            target=_create_parent_race_worker,
            args=(str(tmp_path / "runs"), str(package.manifest_path), barrier, queue),
        )
        for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=15)
        assert worker.exitcode == 0
    ids = {queue.get(timeout=2), queue.get(timeout=2)}
    assert len(ids) == 1
    store = FileRunStore(tmp_path / "runs")
    parents = [
        path.name
        for path in _run_dirs(tmp_path / "runs")
        if str(store.load_run(path.name).get("run_kind") or "") == RUN_KIND_PARENT_EXECUTION
    ]
    assert parents == [next(iter(ids))]


def test_create_run_at_plan_validated_defaults_to_planning_kind(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T001101-001101"
    kwargs = create_run_kwargs(tmp_path)
    store.create_run(
        run_id,
        plan=_approved_parent_plan(run_id),
        phase="plan_validated",
        **kwargs,
    )
    assert store.load_run(run_id)["run_kind"] == RUN_KIND_PLANNING


@pytest.mark.parametrize(
    "exc, code",
    [
        (PersistenceError("corrupt continue"), "corrupt_run"),
        (RunNotFoundError("run-missing", "deleted"), "run_not_found"),
        (PermissionError("denied"), "operational_error"),
        (StoreRevisionConflictError(1, 2), "run_revision_conflict"),
        (StoreAuthorizationConflictError("token revoked"), "store_authorization_conflict"),
        (
            RunOwnershipError("owned", code="run_owned_by_live_process"),
            "run_owned_by_live_process",
        ),
    ],
)
def test_post_create_continue_run_errors_include_run_identity(
    tmp_path: Path, exc: BaseException, code: str
) -> None:
    engine = MagicMock()
    engine.continue_run.side_effect = exc
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
            patch("top_down_planning.cli.user._build_run_engine", return_value=engine)
        )
        result = run_cli(argv)
    leftover = _run_dirs(tmp_path / "runs")
    assert leftover
    run_id = leftover[0].name
    _assert_no_traceback(result)
    assert result.exit_code == 1
    payload = _stdout_json(result)
    _assert_structured_error(result, code)
    assert payload.get("run_id") == run_id
    recovery = payload.get("recovery") or {}
    if code == "run_not_found":
        assert not recovery.get("command")
    elif code == "corrupt_run":
        assert recovery.get("command") == "doctor"
        assert recovery.get("run_id") == run_id
    elif code in {
        "run_revision_conflict",
        "store_authorization_conflict",
        "run_owned_by_live_process",
        "operational_error",
    }:
        assert recovery.get("command") == "status"
        assert recovery.get("run_id") == run_id
    else:
        assert recovery.get("run_id") == run_id


def test_unit_drive_persistence_error_includes_child_run_id(tmp_path: Path) -> None:
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
        raise PersistenceError("drive failed")

    with patch.object(PreparedUnitExecutor, "drive_child_run", fail_drive):
        result = run_cli(argv)
    leftover = [
        path.name
        for path in _run_dirs(tmp_path / "runs")
        if path.name.startswith("run-")
    ]
    store = FileRunStore(tmp_path / "runs")
    children = [
        name
        for name in leftover
        if str(store.load_run(name).get("run_kind") or "") == RUN_KIND_SUB_TDP_EXECUTION
    ]
    assert len(children) == 1
    _assert_no_traceback(result)
    assert result.exit_code == 1
    payload = _stdout_json(result)
    assert payload["error"]["code"] == "corrupt_run"
    assert payload.get("run_id") == children[0]


def test_prepare_planning_run_ignores_deleted_live_goal_file(tmp_path: Path) -> None:
    goal = tmp_path / "goal.md"
    goal.write_text("Ship from file.\n", encoding="utf-8")
    store = FileRunStore(tmp_path / "runs")
    config = create_run_kwargs(tmp_path)["resolved_config"]
    config["run"] = {
        "output_goal_file": "goal.md",
        "input_refs": list((config.get("run") or {}).get("input_refs") or []),
    }
    kwargs = create_run_kwargs(tmp_path, resolved_config=config)
    run_id = "run-20260101T001101-001101"
    store.create_run(
        run_id,
        plan=_approved_parent_plan(run_id),
        phase="plan_validated",
        run_extras={"run_kind": RUN_KIND_PLANNING},
        **kwargs,
    )
    from tests.helpers import whole_plan_approval_record

    store.save_review(run_id, whole_plan_approval_record(store, run_id))
    goal.unlink()
    config_path = write_config(
        tmp_path / "cfg.yaml",
        "run:\n  output_goal_file: goal.md\n"
        f"project:\n  workspace: {tmp_path}\nprovider:\n  name: stub\n",
    )
    result = run_cli(
        [
            "prepare",
            "--config",
            str(config_path),
            "--runs-dir",
            str(store.root),
            "--output",
            str(tmp_path / "pkg"),
            "--planning-run",
            run_id,
            "--stream-json",
        ]
    )
    _assert_no_traceback(result)
    assert result.exit_code == 0
    payload = _stdout_json(result)
    assert payload["ok"] is True
    assert payload["planning_run_id"] == run_id
    assert (tmp_path / "pkg" / "manifest.json").exists()


def test_prepare_planning_run_rejects_semantic_set_override(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T001102-001102"
    _planning_run_at_validated(store, tmp_path, run_id)
    config_path = write_config(
        tmp_path / "cfg.yaml",
        "run:\n  output_goal: Ship it.\n"
        f"project:\n  workspace: {tmp_path}\nprovider:\n  name: stub\n",
    )
    result = run_cli(
        [
            "prepare",
            "--config",
            str(config_path),
            "--runs-dir",
            str(store.root),
            "--output",
            str(tmp_path / "pkg"),
            "--planning-run",
            run_id,
            "--set",
            "planning.max_depth=9",
            "--stream-json",
        ]
    )
    _assert_no_traceback(result)
    assert result.exit_code == 2
    payload = _stdout_json(result)
    assert payload["error"]["code"] == "config_error"


@pytest.mark.parametrize(
    "kind, factory",
    [
        (RUN_KIND_PARENT_EXECUTION, "parent"),
        (RUN_KIND_SUB_TDP_EXECUTION, "child"),
    ],
)
def test_prepare_planning_run_rejects_execution_run_kind(
    tmp_path: Path, kind: str, factory: str
) -> None:
    store, _, package = _built_package(tmp_path)
    if factory == "parent":
        run_id = PreparedRunFactory().create_parent_run(
            store,
            package,
            resolved_config=package.resolved_config,
            invocation={"command": "execute"},
        )
    else:
        run_id = PreparedRunFactory().create_child_run(
            store,
            package,
            package.units["item-foundation"],
            resolved_config=package.resolved_config,
            invocation={"command": "execute"},
        )
    assert str(store.load_run(run_id).get("run_kind") or "") == kind
    config_path = write_config(
        tmp_path / "cfg.yaml",
        "run:\n  output_goal: Ship it.\n"
        f"project:\n  workspace: {tmp_path}\nprovider:\n  name: stub\n",
    )
    result = run_cli(
        [
            "prepare",
            "--config",
            str(config_path),
            "--runs-dir",
            str(store.root),
            "--output",
            str(tmp_path / "pkg-from-exec"),
            "--planning-run",
            run_id,
            "--stream-json",
        ]
    )
    _assert_no_traceback(result)
    assert result.exit_code == 1
    payload = _stdout_json(result)
    assert payload["error"]["code"] == "invalid_planning_run"
    assert not (tmp_path / "pkg-from-exec").exists()


def test_prepare_success_metadata_uses_built_package_not_later_run_state(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T001201-001201"
    _planning_run_at_validated(store, tmp_path, run_id)
    real_build = ExecutionPackageBuilder.build_from_planning_run

    from top_down_planning.persistence.commit import CommitSpec
    from top_down_planning.persistence.snapshot_bindings import bind_run_digests_for_plan_update

    def build_then_bump(self, store_arg, planning_run_id, **kwargs):
        built = real_build(self, store_arg, planning_run_id, **kwargs)
        run = store_arg.load_run(planning_run_id)
        plan = store_arg.load_plan(planning_run_id)
        bumped_plan = dict(plan)
        bumped_plan["revision"] = int(plan["revision"]) + 1
        bumped_run = bind_run_digests_for_plan_update(dict(run), bumped_plan)
        bumped_run["revision"] = int(run["revision"]) + 1
        store_arg.commit(
            planning_run_id,
            CommitSpec(
                run=bumped_run,
                run_expected_revision=int(run["revision"]),
                plan=bumped_plan,
                plan_expected_revision=int(plan["revision"]),
            ),
        )
        return built

    config_path = write_config(
        tmp_path / "cfg.yaml",
        "run:\n  output_goal: Ship it.\n"
        f"project:\n  workspace: {tmp_path}\nprovider:\n  name: stub\n",
    )
    with patch.object(
        ExecutionPackageBuilder, "build_from_planning_run", build_then_bump
    ):
        result = run_cli(
            [
                "prepare",
                "--config",
                str(config_path),
                "--runs-dir",
                str(store.root),
                "--output",
                str(tmp_path / "pkg"),
                "--planning-run",
                run_id,
                "--stream-json",
            ]
        )
    _assert_no_traceback(result)
    assert result.exit_code == 0
    payload = _stdout_json(result)
    package = ExecutionPackageLoader().load(tmp_path / "pkg", verify_workspace=False)
    planning = package.manifest["planning_run"]
    assert payload["plan_revision"] == planning["approved_plan_revision"]
    assert payload["plan_digest"] == planning["approved_plan_digest"]
    live_plan = store.load_plan(run_id)
    assert payload["plan_revision"] != live_plan.get("revision")


def test_paused_child_resume_uses_snapshot_after_post_snapshot_bump(
    tmp_path: Path,
) -> None:
    store, output_dir, _ = _dependent_build_package(tmp_path)
    package = ExecutionPackageLoader().load(output_dir, verify_workspace=False)
    child_id = PreparedRunFactory().create_child_run(
        store,
        package,
        package.units["item-a"],
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
    )
    _pause_child_for_resume(store, child_id)
    real_snapshot = FileRunStore.load_canonical_snapshot
    bumped = {"done": False}

    def snapshot_then_bump(self, rid):
        snapshot = real_snapshot(self, rid)
        if rid == child_id and not bumped["done"]:
            bumped["done"] = True
            _publish_valid_paused_production_revision(self, rid)
        return snapshot

    engine = MagicMock()
    engine.continue_run.return_value = RunContinuationResult(
        ok=False,
        run_id=child_id,
        phase="plan_validated",
        status="paused",
        outcome=None,
        reason="limit reached",
        cancelled=False,
        target_reached=False,
    )
    argv = [
        "execute",
        "--manifest",
        str(package.manifest_path),
        "--unit",
        "item-a",
        "--runs-dir",
        str(store.root),
        "--stream-json",
    ]
    with (
        patch.object(FileRunStore, "load_canonical_snapshot", snapshot_then_bump),
        patch(
            "top_down_planning.orchestrator.sub_tdp_child_driver.apply_resume_plan_atomically",
            return_value={"ok": True},
        ),
        patch("top_down_planning.cli.execute._build_run_engine", return_value=engine),
        patch(
            "top_down_planning.orchestrator.engine.RunEngine.continue_run",
            engine.continue_run,
        ),
    ):
        result = run_cli(argv)
    _assert_no_traceback(result)
    assert bumped["done"] is True
    text = result.stdout + result.stderr
    assert "resume_preparation_blocked" not in text
    payload = _stdout_json(result)
    assert payload.get("error", {}).get("code") != "resume_preparation_blocked"
    assert payload.get("run_id") == child_id


def test_prepared_create_rolls_back_when_inherited_review_staging_fails(
    tmp_path: Path,
) -> None:
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
    real_write = None
    from core_tools.persistence import atomic_write_json as real_atomic

    real_write = real_atomic

    def fail_review_stage(path, payload, **kwargs):
        if "reviews" in Path(path).parts:
            raise PersistenceError("review stage failed")
        return real_write(path, payload, **kwargs)

    with (
        patch("top_down_planning.persistence.file_store.atomic_write_json", fail_review_stage),
        patch.object(
            PreparedUnitExecutor,
            "drive_child_run",
            lambda self, child_store, child_run_id, **kwargs: PreparedChildResult.from_run(
                child_store.load_run(child_run_id), ok=True
            ),
        ),
    ):
        first = run_cli(argv)
    leftover = _run_dirs(tmp_path / "runs")
    children = []
    store = FileRunStore(tmp_path / "runs")
    for path in leftover:
        try:
            run = store.load_run(path.name)
        except Exception:
            continue
        if str(run.get("run_kind") or "") == RUN_KIND_SUB_TDP_EXECUTION:
            children.append(path.name)
    _assert_no_traceback(first)
    assert first.exit_code != 0
    assert children == []
    second = run_cli(argv)
    _assert_no_traceback(second)
    after = [
        path.name
        for path in _run_dirs(tmp_path / "runs")
        if str(store.load_run(path.name).get("run_kind") or "") == RUN_KIND_SUB_TDP_EXECUTION
    ]
    assert len(after) == 1


@pytest.mark.parametrize("command", ["run", "prepare"])
def test_guidance_file_permission_error_is_operational(tmp_path: Path, command: str) -> None:
    from tests.unit.test_slice7_rereview_739_750 import _run_or_prepare_argv

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
    payload = _stdout_json(structured)
    assert payload["error"]["code"] == "operational_error"
