"""Slice 7 re-review regressions for TDP-CLI-768–774."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core_tools.persistence import PersistenceError, RunNotFoundError
from top_down_planning.domain.run_ownership import RunOwnershipError
from top_down_planning.orchestrator.engine import RunContinuationResult
from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory
from top_down_planning.orchestrator.prepared_unit_executor import PreparedUnitExecutor
from top_down_planning.orchestrator.sub_tdp_child_driver import PreparedChildResult
from top_down_planning.package.builder import ExecutionPackageBuilder
from top_down_planning.package.execution_validation import validate_resolved_config_against_package
from top_down_planning.package.loader import ExecutionPackageLoader
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.commit import CommitSpec
from top_down_planning.persistence.snapshot_bindings import (
    bind_run_digests_for_config_update,
    bind_run_digests_for_production_update,
)
from tests.conftest import run_cli
from tests.helpers import accept_child_run, create_run_kwargs, write_config
from tests.support.run_builders import _planning_run_at_validated
from tests.support.run_builders import _built_package
from tests.support.cli_fakes import _assert_operational_without_traceback
from tests.unit.test_slice7_rereview_739_747 import (
    _dependent_build_package,
    _execute_item_b_argv,
)
from tests.support.cli_fakes import _assert_no_traceback
from tests.support.cli_fakes import _assert_structured_error, _stdout_json
from tests.support.cli_fakes import _engine_patches
from tests.unit.test_slice7_rereview_760_764 import _pause_child_for_resume
from tests.support.cli_fakes import _patch_prepare_plan_validated


def _publish_valid_config_run_revision(store: FileRunStore, run_id: str) -> None:
    run = FileRunStore.load_run(store, run_id)
    config = dict(FileRunStore.load_resolved_config(store, run_id))
    planning = dict(config.get("planning") or {})
    planning["max_depth"] = int(planning.get("max_depth") or 3) + 1
    config["planning"] = planning
    workspace = Path(str(run.get("workspace") or store.root))
    updated = bind_run_digests_for_config_update(dict(run), config, workspace=workspace)
    expected = int(run["revision"])
    updated["revision"] = expected + 1
    store.commit(
        run_id,
        CommitSpec(
            run=updated,
            run_expected_revision=expected,
            resolved_config=config,
        ),
    )


def _freeze_then_bump_snapshot(run_id: str):
    frozen: dict[str, object] = {}
    real_snapshot = FileRunStore.load_canonical_snapshot
    real_load_run = FileRunStore.load_run
    real_load_config = FileRunStore.load_resolved_config
    frozen_run: dict[str, dict] = {}
    frozen_config: dict[str, dict] = {}
    bumped = {"done": False}

    def snapshot_then_bump(self, rid):
        if rid != run_id:
            return real_snapshot(self, rid)
        if rid not in frozen:
            frozen[rid] = real_snapshot(self, rid)
            if not bumped["done"]:
                bumped["done"] = True
                _publish_valid_config_run_revision(self, rid)
        return frozen[rid]

    def load_run_then_bump(self, rid, *args, **kwargs):
        if rid != run_id:
            return real_load_run(self, rid)
        if rid not in frozen_run:
            frozen_run[rid] = real_load_run(self, rid)
            if not bumped["done"]:
                bumped["done"] = True
                _publish_valid_config_run_revision(self, rid)
        return frozen_run[rid]

    def load_config_live(self, rid, *args, **kwargs):
        if rid != run_id:
            return real_load_config(self, rid)
        if rid not in frozen_config:
            frozen_config[rid] = real_load_config(self, rid)
        if bumped["done"]:
            return real_load_config(self, rid)
        return frozen_config[rid]

    return snapshot_then_bump, load_run_then_bump, load_config_live


def test_package_builder_uses_one_planning_snapshot(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T000801-000801"
    _planning_run_at_validated(store, tmp_path, run_id)
    snapshot_then_bump, load_run_then_bump, load_config_live = _freeze_then_bump_snapshot(
        run_id
    )
    output_dir = tmp_path / "pkg"
    with (
        patch.object(FileRunStore, "load_canonical_snapshot", snapshot_then_bump),
        patch.object(FileRunStore, "load_run", load_run_then_bump),
        patch.object(FileRunStore, "load_resolved_config", load_config_live),
    ):
        built = ExecutionPackageBuilder().build_from_planning_run(
            store, run_id, output_dir=output_dir
        )
    package = ExecutionPackageLoader().load(output_dir, verify_workspace=False)
    validate_resolved_config_against_package(
        package.resolved_config,
        package,
        workspace=package.workspace_path,
    )
    assert built.manifest_path.exists()


def _publish_valid_paused_production_revision(store: FileRunStore, run_id: str) -> None:
    run = FileRunStore.load_run(store, run_id)
    production = FileRunStore.load_production(store, run_id)
    new_production = dict(production)
    new_production["revision"] = int(production["revision"]) + 1
    new_run = bind_run_digests_for_production_update(dict(run), new_production)
    expected = int(run["revision"])
    new_run["revision"] = expected + 1
    store.commit(
        run_id,
        CommitSpec(
            run=new_run,
            run_expected_revision=expected,
            production=new_production,
            production_expected_revision=int(production["revision"]),
        ),
    )


def test_paused_child_resume_uses_driver_snapshot(tmp_path: Path) -> None:
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
    assert result.exit_code in {0, 1}
    payload = _stdout_json(result)
    assert payload.get("error", {}).get("code") != "resume_preparation_blocked"
    assert payload.get("run_id") == child_id


@pytest.mark.parametrize("command", ["run", "prepare", "execute"])
@pytest.mark.parametrize(
    "exc, code",
    [
        (PersistenceError("corrupt continue"), "corrupt_run"),
        (RunNotFoundError("run-missing", "deleted"), "run_not_found"),
        (PermissionError("denied"), "operational_error"),
        (
            RunOwnershipError("owned", code="run_owned_by_live_process"),
            "run_owned_by_live_process",
        ),
    ],
)
@pytest.mark.parametrize("stream_json", [True, False])
def test_continue_run_errors_use_cli_normalization_boundary(
    tmp_path: Path, command: str, exc: BaseException, code: str, stream_json: bool
) -> None:
    engine = MagicMock()
    engine.continue_run.side_effect = exc
    if command == "execute":
        _, _, package = _built_package(tmp_path)
        argv = [
            "execute",
            "--manifest",
            str(package.manifest_path),
            "--runs-dir",
            str(tmp_path / "runs"),
        ]
    else:
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
        for item in _engine_patches(tmp_path):
            stack.enter_context(item)
        stack.enter_context(
            patch("top_down_planning.cli.user._build_run_engine", return_value=engine)
        )
        stack.enter_context(
            patch("top_down_planning.cli.prepare._build_run_engine", return_value=engine)
        )
        stack.enter_context(
            patch("top_down_planning.cli.execute._build_run_engine", return_value=engine)
        )
        if command == "prepare":
            stack.enter_context(_patch_prepare_plan_validated())
        result = run_cli(argv)
    _assert_no_traceback(result)
    assert result.exit_code == 1
    if stream_json:
        _assert_structured_error(result, code)
    elif code == "operational_error":
        _assert_operational_without_traceback(result)
    else:
        assert "Traceback" not in result.stdout + result.stderr


def test_factory_live_wrapper_permission_error_is_operational(tmp_path: Path) -> None:
    store, output_dir, _ = _dependent_build_package(tmp_path)
    package = ExecutionPackageLoader().load(output_dir, verify_workspace=False)
    child_id = PreparedRunFactory().create_child_run(
        store,
        package,
        package.units["item-a"],
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
    )
    accept_child_run(store, child_id)
    argv = _execute_item_b_argv(package, store, ["--upstream", f"item-a={child_id}"])

    def deny_revalidation(store_arg, wrapper):
        raise PermissionError("denied")

    with patch(
        "top_down_planning.package.lineage.verify_upstream_wrapper_matches_live_delivery",
        deny_revalidation,
    ):
        structured = run_cli(argv)
        human = run_cli(argv[:-1])
    _assert_operational_without_traceback(structured)
    _assert_no_traceback(human)
    text = structured.stdout + structured.stderr + human.stdout + human.stderr
    assert "sub_tdp_upstream_invalid" not in text


def _run_dirs(runs_root: Path) -> list[Path]:
    if not runs_root.exists():
        return []
    return [
        path
        for path in runs_root.iterdir()
        if path.is_dir() and path.name.startswith("run-")
    ]


def test_prepared_create_survives_inherited_review_write_failure(tmp_path: Path) -> None:
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
    from core_tools.persistence import atomic_write_json as real_atomic

    def fail_review_stage(path, payload, **kwargs):
        if "reviews" in Path(path).parts:
            raise PersistenceError("review stage failed")
        return real_atomic(path, payload, **kwargs)

    def reuse_drive(self, child_store, child_run_id, **kwargs):
        return PreparedChildResult.from_run(child_store.load_run(child_run_id), ok=True)

    with patch.object(PreparedUnitExecutor, "drive_child_run", reuse_drive):
        with patch(
            "top_down_planning.persistence.file_store.atomic_write_json",
            fail_review_stage,
        ):
            first = run_cli(argv)
        leftover = _run_dirs(tmp_path / "runs")
        store = FileRunStore(tmp_path / "runs")
        children = []
        for path in leftover:
            try:
                run = store.load_run(path.name)
            except Exception:
                continue
            if str(run.get("run_kind") or "") == "sub_tdp_execution":
                children.append(path.name)
        _assert_no_traceback(first)
        assert first.exit_code != 0
        assert children == []
        second = run_cli(argv)
    _assert_no_traceback(second)
    after = [
        path.name
        for path in _run_dirs(tmp_path / "runs")
        if str(store.load_run(path.name).get("run_kind") or "") == "sub_tdp_execution"
    ]
    assert len(after) == 1
    assert store.list_reviews(after[0])


def test_parent_only_post_create_failure_identifies_run_and_retry_reuses_it(
    tmp_path: Path,
) -> None:
    _, _, package = _built_package(tmp_path)
    argv = [
        "execute",
        "--manifest",
        str(package.manifest_path),
        "--parent-only",
        "--runs-dir",
        str(tmp_path / "runs"),
        "--stream-json",
    ]
    real_save = FileRunStore.save_run
    failed = {"n": 0}

    def fail_phase_save(self, run_id, run, expected_revision):
        failed["n"] += 1
        if failed["n"] == 1:
            raise PersistenceError("phase save failed")
        return real_save(self, run_id, run, expected_revision)

    with patch.object(FileRunStore, "save_run", fail_phase_save):
        first = run_cli(argv)
    parents = []
    store = FileRunStore(tmp_path / "runs")
    for path in _run_dirs(tmp_path / "runs"):
        run = store.load_run(path.name)
        if str(run.get("run_kind") or "") == "parent_execution":
            parents.append(path.name)
    assert len(parents) == 1
    _assert_no_traceback(first)
    if first.exit_code != 0:
        payload = _stdout_json(first)
        assert payload.get("run_id") == parents[0]
    second = run_cli(argv)
    _assert_no_traceback(second)
    parents_after = []
    for path in _run_dirs(tmp_path / "runs"):
        run = store.load_run(path.name)
        if str(run.get("run_kind") or "") == "parent_execution":
            parents_after.append(path.name)
    assert parents_after == parents


def test_prepare_package_build_failure_identifies_planning_run_for_retry(
    tmp_path: Path,
) -> None:
    config_path = write_config(
        tmp_path / "cfg.yaml",
        "run:\n  output_goal: Ship it.\n"
        f"project:\n  workspace: {tmp_path}\nprovider:\n  name: stub\n",
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
        stack.enter_context(_patch_prepare_plan_validated())
        stack.enter_context(
            patch(
                "top_down_planning.cli.prepare.ExecutionPackageBuilder.build_from_planning_run",
                side_effect=ValueError("materialize failed"),
            )
        )
        first = run_cli(argv)
    leftover = _run_dirs(tmp_path / "runs")
    assert leftover
    planning_run_id = leftover[0].name
    _assert_no_traceback(first)
    assert first.exit_code == 1
    payload = _stdout_json(first)
    assert payload["error"]["code"] == "package_build_failed"
    assert payload.get("planning_run_id") == planning_run_id
    from top_down_planning.orchestrator.phases import PLAN_VALIDATED

    store = FileRunStore(tmp_path / "runs")
    persisted = dict(store.load_run(planning_run_id))
    expected = int(persisted["revision"])
    persisted["revision"] = expected + 1
    persisted["phase"] = PLAN_VALIDATED
    store.save_run(planning_run_id, persisted, expected)
    retry = [
        "prepare",
        "--config",
        str(config_path),
        "--runs-dir",
        str(tmp_path / "runs"),
        "--output",
        str(tmp_path / "pkg"),
        "--planning-run",
        planning_run_id,
        "--stream-json",
    ]
    with ExitStack() as stack:
        for item in _engine_patches(tmp_path):
            stack.enter_context(item)
        stack.enter_context(_patch_prepare_plan_validated())
        stack.enter_context(
            patch(
                "top_down_planning.cli.prepare.ExecutionPackageBuilder.build_from_planning_run",
                return_value=SimpleNamespace(
                    package_id="pkg-retry",
                    manifest_path=tmp_path / "pkg" / "manifest.json",
                    manifest={
                        "planning_run": {
                            "approved_plan_revision": 0,
                            "approved_plan_digest": "a" * 64,
                        }
                    },
                ),
            )
        )
        second = run_cli(retry)
    _assert_no_traceback(second)
    assert second.exit_code == 0
    leftover_after = _run_dirs(tmp_path / "runs")
    assert [path.name for path in leftover_after] == [planning_run_id]


def test_create_run_rejects_partial_journal_metadata_in_initial_events(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T000001-000001"
    kwargs = create_run_kwargs(tmp_path)
    from top_down_planning.domain.models import Plan, PlanItem

    with pytest.raises(PersistenceError, match="journal"):
        store.create_run(
            run_id,
            plan=Plan(
                id="plan-x",
                revision=0,
                output_goal="Goal.",
                items={
                    "item-root": PlanItem(
                        id="item-root",
                        parent_id=None,
                        order_key="0000000000",
                        title="Root",
                        kind="aggregate",
                    )
                },
            ),
            initial_events=[{"type": "context_snapshot_collected", "txn_id": "partial"}],
            **kwargs,
        )
    assert not (store.root / run_id).exists()
