"""Slice 7 re-review regressions for TDP-CLI-760 residual and 762–764."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core_tools.persistence import PersistenceError
from top_down_planning.orchestrator.engine import RunContinuationResult
from top_down_planning.orchestrator.phases import PLAN_VALIDATED
from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory
from top_down_planning.orchestrator.prepared_unit_executor import PreparedUnitExecutor
from top_down_planning.orchestrator.sub_tdp_child_driver import PreparedChildResult
from top_down_planning.package.lineage import accepted_result_digest, accepted_result_record
from top_down_planning.package.loader import ExecutionPackageLoader
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.commit import CommitSpec
from top_down_planning.persistence.snapshot_bindings import (
    bind_run_digests_for_production_update,
)
from tests.conftest import run_cli
from tests.helpers import accept_child_run, write_config
from tests.unit.test_slice7_rereview_739_747 import (
    _assert_operational_without_traceback,
    _dependent_build_package,
    _execute_item_b_argv,
)
from tests.unit.test_slice7_rereview_751_754 import _assert_no_traceback, _resume_check_argv
from tests.unit.test_slice7_rereview_755_758 import _assert_structured_error, _stdout_json


def _publish_valid_child_run_production_revision(
    store: FileRunStore,
    run_id: str,
    *,
    load_run=None,
    load_production=None,
) -> None:
    from top_down_planning.domain.reviews import find_whole_output_approval
    from top_down_planning.package.builder import digest_review_record
    from top_down_planning.persistence.review_commit import (
        review_record_revision,
        save_review_with_expected_revision,
    )

    read_run = load_run or FileRunStore.load_run
    read_production = load_production or FileRunStore.load_production
    run = read_run(store, run_id)
    production = read_production(store, run_id)
    new_production = dict(production)
    new_production["revision"] = int(production["revision"]) + 1
    claim = dict(new_production.get("completion_claim") or {})
    claim["goal_assessment"] = str(claim.get("goal_assessment") or "") + " bumped"
    new_production["completion_claim"] = claim
    new_run = bind_run_digests_for_production_update(dict(run), new_production)
    approval = find_whole_output_approval(
        FileRunStore.list_reviews(store, run_id),
        int(new_production.get("output_revision") or 0),
    )
    if approval is None:
        raise AssertionError("accepted child missing whole-output approval")
    updated_approval = dict(approval)
    approved = dict(updated_approval.get("approved_digests") or {})
    approved["output"] = str((new_run.get("digests") or {}).get("output") or "")
    updated_approval["approved_digests"] = approved
    save_review_with_expected_revision(
        store,
        run_id,
        updated_approval,
        expected_revision=review_record_revision(approval),
    )
    stored_approval = FileRunStore.load_review(
        store, run_id, str(updated_approval.get("id") or "")
    )
    binding = dict(new_run.get("package_binding") or {})
    binding["whole_output_review_digest"] = digest_review_record(stored_approval)
    new_run["package_binding"] = binding
    new_run["revision"] = int(run["revision"]) + 1
    store.commit(
        run_id,
        CommitSpec(
            run=new_run,
            run_expected_revision=int(run["revision"]),
            production=new_production,
            production_expected_revision=int(production["revision"]),
        ),
    )


def _accepted_dependency_package(tmp_path: Path):
    store, output_dir, _ = _dependent_build_package(tmp_path)
    package = ExecutionPackageLoader().load(output_dir, verify_workspace=False)
    dep_id = PreparedRunFactory().create_child_run(
        store,
        package,
        package.units["item-a"],
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
    )
    accept_child_run(store, dep_id)
    return store, package, dep_id


def _pause_child_for_resume(store: FileRunStore, run_id: str) -> None:
    run = store.load_run(run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["status"] = "paused"
    run["stop"] = {
        "code": "limit_exhausted",
        "category": "operational",
        "phase": PLAN_VALIDATED,
        "message": "limit reached",
        "details": {
            "limit": "limits.production.max_batches",
            "consumed": 1,
            "configured": 1,
        },
    }
    store.save_run(run_id, run, expected)


def _bump_after_first_child_load(child_id: str):
    bumped = {"done": False}
    frozen_run: dict[str, dict] = {}
    frozen_snap: dict[str, object] = {}
    real_load_run = FileRunStore.load_run
    real_load_production = FileRunStore.load_production
    real_snapshot = FileRunStore.load_canonical_snapshot

    def bump_after_child_read(self, rid, *args, **kwargs):
        if rid == child_id:
            if rid not in frozen_run:
                frozen_run[rid] = real_load_run(self, rid)
                if not bumped["done"]:
                    bumped["done"] = True
                    _publish_valid_child_run_production_revision(
                        self,
                        rid,
                        load_run=real_load_run,
                        load_production=real_load_production,
                    )
            return frozen_run[rid]
        return real_load_run(self, rid)

    def snapshot_then_bump(self, rid):
        if rid == child_id:
            if rid not in frozen_snap:
                frozen_snap[rid] = real_snapshot(self, rid)
                if not bumped["done"]:
                    bumped["done"] = True
                    _publish_valid_child_run_production_revision(
                        self,
                        rid,
                        load_run=real_load_run,
                        load_production=real_load_production,
                    )
            return frozen_snap[rid]
        return real_snapshot(self, rid)

    return bump_after_child_read, snapshot_then_bump


def _skip_drive():
    def drive(self, child_store, child_run_id, **kwargs):
        return PreparedChildResult.from_run(child_store.load_run(child_run_id), ok=True)

    return patch.object(PreparedUnitExecutor, "drive_child_run", drive)


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


def _assert_lineage_not_rejected(result) -> None:
    _assert_no_traceback(result)
    text = result.stdout + result.stderr
    assert "sub_tdp_upstream_invalid" not in text
    assert "sub_tdp_dependency_unmet" not in text
    if result.stdout.strip().startswith("{"):
        payload = _stdout_json(result)
        assert payload.get("error", {}).get("code") not in {
            "sub_tdp_upstream_invalid",
            "sub_tdp_dependency_unmet",
            "resume_preparation_blocked",
            "resume_apply_blocked",
        }


def test_resume_check_baseline_wrapper_uses_one_child_snapshot(tmp_path: Path) -> None:
    store, package, dep_id = _accepted_dependency_package(tmp_path)
    child_b = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        "item-b",
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
        explicit_upstream={"item-a": dep_id},
        explicit_upstream_only=True,
    )
    _pause_child_for_resume(store, child_b)
    before = store.load_canonical_snapshot(dep_id)
    before_digest = accepted_result_digest(
        accepted_result_record(
            child_run=before.run,
            child_production=before.production,
            unit_id="item-a",
            unit_plan_digest=package.units["item-a"].plan_digest,
            package_id=str(package.manifest.get("package_id") or ""),
            package_digest=str(package.manifest.get("package_digest") or ""),
            assigned_subtree_digest=package.units["item-a"].assigned_subtree_digest,
        )
    )
    bump_after_child_read, snapshot_then_bump = _bump_after_first_child_load(dep_id)
    argv = [*_resume_check_argv(child_b, store.root), "--stream-json"]
    with (
        patch.object(FileRunStore, "load_run", bump_after_child_read),
        patch.object(FileRunStore, "load_canonical_snapshot", snapshot_then_bump),
    ):
        result = run_cli(argv)

    _assert_lineage_not_rejected(result)
    assert result.exit_code == 0
    after = store.load_canonical_snapshot(dep_id)
    after_digest = accepted_result_digest(
        accepted_result_record(
            child_run=after.run,
            child_production=after.production,
            unit_id="item-a",
            unit_plan_digest=package.units["item-a"].plan_digest,
            package_id=str(package.manifest.get("package_id") or ""),
            package_digest=str(package.manifest.get("package_digest") or ""),
            assigned_subtree_digest=package.units["item-a"].assigned_subtree_digest,
        )
    )
    wrapper = (store.load_run(child_b).get("package_binding") or {}).get(
        "workspace_baseline_accepted_results"
    ) or []
    observed = {str(item.get("accepted_result_digest") or "") for item in wrapper}
    assert observed & {before_digest, after_digest}


def test_resume_apply_upstream_wrapper_uses_one_child_snapshot(tmp_path: Path) -> None:
    store, package, dep_id = _accepted_dependency_package(tmp_path)
    child_b = PreparedUnitExecutor().create_or_load_child_run(
        store,
        package,
        "item-b",
        resolved_config=package.resolved_config,
        invocation={"command": "execute"},
        explicit_upstream={"item-a": dep_id},
        explicit_upstream_only=True,
    )
    _pause_child_for_resume(store, child_b)
    bump_after_child_read, snapshot_then_bump = _bump_after_first_child_load(dep_id)
    engine = MagicMock()
    engine.continue_run.return_value = RunContinuationResult(
        ok=True,
        run_id=child_b,
        phase=PLAN_VALIDATED,
        status="running",
        outcome=None,
        reason=None,
        cancelled=False,
        target_reached=True,
    )
    argv = ["resume", "--run", child_b, "--runs-dir", str(store.root), "--stream-json"]
    with (
        patch.object(FileRunStore, "load_run", bump_after_child_read),
        patch.object(FileRunStore, "load_canonical_snapshot", snapshot_then_bump),
        patch("top_down_planning.cli.user._build_run_engine", return_value=engine),
    ):
        result = run_cli(argv)

    _assert_lineage_not_rejected(result)
    assert result.exit_code == 0


def test_execute_explicit_upstream_uses_one_child_snapshot(tmp_path: Path) -> None:
    store, package, dep_id = _accepted_dependency_package(tmp_path)
    before = store.load_canonical_snapshot(dep_id)
    bump_after_child_read, snapshot_then_bump = _bump_after_first_child_load(dep_id)
    argv = _execute_item_b_argv(package, store, ["--upstream", f"item-a={dep_id}"])
    with (
        _skip_drive(),
        patch.object(FileRunStore, "load_run", bump_after_child_read),
        patch.object(FileRunStore, "load_canonical_snapshot", snapshot_then_bump),
    ):
        result = run_cli(argv)

    _assert_lineage_not_rejected(result)
    created = _stdout_json(result)["run_id"]
    wrapper = (store.load_run(created).get("package_binding") or {}).get(
        "upstream_accepted_results"
    )[0]
    after = store.load_canonical_snapshot(dep_id)
    before_digest = accepted_result_digest(
        accepted_result_record(
            child_run=before.run,
            child_production=before.production,
            unit_id="item-a",
            unit_plan_digest=package.units["item-a"].plan_digest,
            package_id=str(package.manifest.get("package_id") or ""),
            package_digest=str(package.manifest.get("package_digest") or ""),
            assigned_subtree_digest=package.units["item-a"].assigned_subtree_digest,
        )
    )
    after_digest = accepted_result_digest(
        accepted_result_record(
            child_run=after.run,
            child_production=after.production,
            unit_id="item-a",
            unit_plan_digest=package.units["item-a"].plan_digest,
            package_id=str(package.manifest.get("package_id") or ""),
            package_digest=str(package.manifest.get("package_digest") or ""),
            assigned_subtree_digest=package.units["item-a"].assigned_subtree_digest,
        )
    )
    assert wrapper["accepted_result_digest"] in {before_digest, after_digest}


def test_execute_automatic_dependency_discovery_uses_one_child_snapshot(
    tmp_path: Path,
) -> None:
    store, package, dep_id = _accepted_dependency_package(tmp_path)
    bump_after_child_read, snapshot_then_bump = _bump_after_first_child_load(dep_id)
    argv = _execute_item_b_argv(package, store, [])
    with (
        _skip_drive(),
        patch.object(FileRunStore, "load_run", bump_after_child_read),
        patch.object(FileRunStore, "load_canonical_snapshot", snapshot_then_bump),
    ):
        result = run_cli(argv)

    _assert_lineage_not_rejected(result)
    payload = _stdout_json(result)
    assert payload.get("error", {}).get("code") != "sub_tdp_dependency_unmet"
    created = payload["run_id"]
    wrapper = (store.load_run(created).get("package_binding") or {}).get(
        "upstream_accepted_results"
    )[0]
    assert wrapper["accepted_result"]["child_run_id"] == dep_id


def test_matching_child_permission_error_during_creation_key_discovery_creates_no_second_child(
    tmp_path: Path,
) -> None:
    store, package, _ = _accepted_dependency_package(tmp_path)
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
    real = FileRunStore.load_run
    real_snap = FileRunStore.load_canonical_snapshot

    def deny_match(self, rid):
        if rid == first:
            raise PermissionError("denied")
        return real(self, rid)

    def deny_match_snap(self, rid):
        if rid == first:
            raise PermissionError("denied")
        return real_snap(self, rid)

    with (
        patch.object(FileRunStore, "load_run", deny_match),
        patch.object(FileRunStore, "load_canonical_snapshot", deny_match_snap),
    ):
        with pytest.raises(PermissionError):
            PreparedUnitExecutor().create_or_load_child_run(
                store,
                package,
                "item-a",
                resolved_config=package.resolved_config,
                invocation={"command": "execute"},
                parent_run_id=parent_id,
            )
    after_ids = {path.name for path in store.root.iterdir() if path.name.startswith("run-")}
    assert after_ids == before_ids


@pytest.mark.parametrize("stream_json", [True, False])
def test_accepted_dependency_permission_error_is_operational_and_creates_no_child(
    tmp_path: Path, stream_json: bool
) -> None:
    store, package, dep_id = _accepted_dependency_package(tmp_path)
    before_ids = {path.name for path in store.root.iterdir() if path.name.startswith("run-")}
    real_run = FileRunStore.load_run
    real_snap = FileRunStore.load_canonical_snapshot

    def deny_dep_run(self, rid):
        if rid == dep_id:
            raise PermissionError("denied")
        return real_run(self, rid)

    def deny_dep_snap(self, rid):
        if rid == dep_id:
            raise PermissionError("denied")
        return real_snap(self, rid)

    argv = _execute_item_b_argv(package, store, [])
    if not stream_json:
        argv = argv[:-1]
    with (
        patch.object(FileRunStore, "load_run", deny_dep_run),
        patch.object(FileRunStore, "load_canonical_snapshot", deny_dep_snap),
    ):
        result = run_cli(argv)
    after_ids = {path.name for path in store.root.iterdir() if path.name.startswith("run-")}
    assert after_ids == before_ids
    if stream_json:
        _assert_operational_without_traceback(result)
    else:
        _assert_no_traceback(result)
        assert result.exit_code == 1
        assert "sub_tdp_dependency_unmet" not in result.stdout + result.stderr


@pytest.mark.parametrize("stream_json", [True, False])
def test_accepted_dependency_persistence_error_is_corrupt_run_not_unmet(
    tmp_path: Path, stream_json: bool
) -> None:
    store, package, dep_id = _accepted_dependency_package(tmp_path)
    real_run = FileRunStore.load_run
    real_snap = FileRunStore.load_canonical_snapshot

    def corrupt_dep_run(self, rid):
        if rid == dep_id:
            raise PersistenceError("corrupt accepted dependency")
        return real_run(self, rid)

    def corrupt_dep_snap(self, rid):
        if rid == dep_id:
            raise PersistenceError("corrupt accepted dependency")
        return real_snap(self, rid)

    argv = _execute_item_b_argv(package, store, [])
    if not stream_json:
        argv = argv[:-1]
    with (
        patch.object(FileRunStore, "load_run", corrupt_dep_run),
        patch.object(FileRunStore, "load_canonical_snapshot", corrupt_dep_snap),
    ):
        result = run_cli(argv)
    if stream_json:
        _assert_structured_error(result, "corrupt_run")
    else:
        _assert_no_traceback(result)
        assert result.exit_code == 1
        assert "sub_tdp_dependency_unmet" not in result.stdout + result.stderr


@pytest.mark.parametrize("flag", ["upstream", "baseline"])
@pytest.mark.parametrize(
    "exc, code",
    [
        (PermissionError("denied"), "operational_error"),
        (PersistenceError("corrupt child"), "corrupt_run"),
    ],
)
@pytest.mark.parametrize("stream_json", [True, False])
def test_explicit_upstream_and_baseline_access_errors_keep_run_access_codes(
    tmp_path: Path, flag: str, exc: BaseException, code: str, stream_json: bool
) -> None:
    store, package, dep_id = _accepted_dependency_package(tmp_path)
    real_run = FileRunStore.load_run
    real_prod = FileRunStore.load_production
    real_plan = FileRunStore.load_plan_model
    real_snap = FileRunStore.load_canonical_snapshot

    def fail_dep_run(self, rid):
        if rid == dep_id:
            raise exc
        return real_run(self, rid)

    def fail_dep_prod(self, rid):
        if rid == dep_id:
            raise exc
        return real_prod(self, rid)

    def fail_dep_plan(self, rid):
        if rid == dep_id:
            raise exc
        return real_plan(self, rid)

    def fail_dep_snap(self, rid):
        if rid == dep_id:
            raise exc
        return real_snap(self, rid)

    extra = ["--upstream", f"item-a={dep_id}"]
    if flag == "baseline":
        extra.extend(["--baseline", dep_id])
    argv = _execute_item_b_argv(package, store, extra)
    if not stream_json:
        argv = argv[:-1]
    with (
        patch.object(FileRunStore, "load_run", fail_dep_run),
        patch.object(FileRunStore, "load_production", fail_dep_prod),
        patch.object(FileRunStore, "load_plan_model", fail_dep_plan),
        patch.object(FileRunStore, "load_canonical_snapshot", fail_dep_snap),
    ):
        result = run_cli(argv)
    _assert_no_traceback(result)
    assert result.exit_code == 1
    text = result.stdout + result.stderr
    assert "sub_tdp_upstream_invalid" not in text
    assert "sub_tdp_baseline_invalid" not in text
    if stream_json:
        _assert_structured_error(result, code)
    elif code == "operational_error":
        _assert_operational_without_traceback(result)


@pytest.mark.parametrize("command", ["run", "prepare"])
@pytest.mark.parametrize("stream_json", [True, False])
def test_post_publish_create_run_read_failure_is_corrupt_run(
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
    real_load = FileRunStore.load_run
    real_snapshot = FileRunStore.load_canonical_snapshot

    def load_run_after_publish(self, rid):
        if (self.root / rid).is_dir():
            raise PersistenceError("post-publish canonical read failed")
        return real_load(self, rid)

    def load_snapshot_after_publish(self, rid):
        if (self.root / rid).is_dir():
            raise PersistenceError("post-publish canonical read failed")
        return real_snapshot(self, rid)

    with ExitStack() as stack:
        stack.enter_context(patch.object(FileRunStore, "load_run", load_run_after_publish))
        stack.enter_context(
            patch.object(FileRunStore, "load_canonical_snapshot", load_snapshot_after_publish)
        )
        for item in _engine_patches(tmp_path):
            stack.enter_context(item)
        result = run_cli(argv)

    leftover = [
        path
        for path in (tmp_path / "runs").iterdir()
        if path.is_dir() and path.name.startswith("run-")
    ]
    assert leftover
    _assert_no_traceback(result)
    assert result.exit_code != 0
    if stream_json:
        payload = _stdout_json(result)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "corrupt_run"
        assert payload["error"]["code"] != "run_creation_failed"
