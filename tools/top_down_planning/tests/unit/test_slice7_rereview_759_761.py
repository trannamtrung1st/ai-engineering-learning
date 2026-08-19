"""Slice 7 re-review regressions for TDP-CLI-755 residual and 759–761."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.persistence import PersistenceError
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.orchestrator.resume_stop_validators import (
    validate_review_incomplete_stop,
)
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.commit import CommitSpec
from top_down_planning.persistence.snapshot_bindings import (
    bind_run_digests_for_production_update,
)
from tests.conftest import run_cli
from tests.helpers import make_review_loop, save_review_payload
from tests.unit.test_prepared_runs import _built_package
from tests.unit.test_resume_cli import _create_paused_production_run
from tests.unit.test_slice7_rereview_739_747 import _assert_operational_without_traceback
from tests.unit.test_slice7_rereview_751_754 import (
    _assert_no_traceback,
    _attached_parent_and_child,
    _resume_check_argv,
)
from tests.unit.test_slice7_rereview_755_758 import _assert_structured_error
from tests.unit.test_slice7_rereview_cli_schema import _create_planning_run, _stdout_json


def _fail_same_run(run_id: str, label: str, real):
    def wrapper(self, rid, *args, **kwargs):
        if rid == run_id:
            raise PersistenceError(f"unexpected same-run {label} reread")
        return real(self, rid, *args, **kwargs)

    return wrapper


@pytest.mark.parametrize("make_run", ["paused_production", "parent_execute"])
def test_resume_check_uses_captured_snapshot_without_same_run_rereads(
    tmp_path: Path, make_run: str
) -> None:
    if make_run == "paused_production":
        store = FileRunStore(tmp_path / "runs")
        run_id = _create_paused_production_run(store)
        runs_dir = store.root
    else:
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
        run_id = _stdout_json(created)["run_id"]
        runs_dir = tmp_path / "runs"

    argv = [*_resume_check_argv(run_id, runs_dir), "--stream-json"]
    real_plan = FileRunStore.load_plan
    real_plan_model = FileRunStore.load_plan_model
    real_production = FileRunStore.load_production
    real_review = FileRunStore.load_review
    with (
        patch.object(FileRunStore, "load_plan", _fail_same_run(run_id, "load_plan", real_plan)),
        patch.object(
            FileRunStore,
            "load_plan_model",
            _fail_same_run(run_id, "load_plan_model", real_plan_model),
        ),
        patch.object(
            FileRunStore,
            "load_production",
            _fail_same_run(run_id, "load_production", real_production),
        ),
        patch.object(
            FileRunStore, "load_review", _fail_same_run(run_id, "load_review", real_review)
        ),
    ):
        result = run_cli(argv)

    _assert_no_traceback(result)
    assert result.exit_code == 0
    payload = _stdout_json(result)
    assert "error" not in payload


def _create_review_incomplete_paused_run(store: FileRunStore) -> str:
    run_id = _create_planning_run(store, "run-20260101T131101-131101")
    loop = make_review_loop(
        id="review-focused-plan-slice7",
        type="focused_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "focused_plan", "item_ids": ["item-root"]},
        status="review_incomplete",
        revise_at="blocker",
        finding_set_id="fs-01",
        review_incomplete={
            "stage": "discovery",
            "finding_set_id": "fs-01",
            "reason": "missing inputs",
        },
    )
    save_review_payload(store, run_id, loop.to_dict())
    run = store.load_run(run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["status"] = "paused"
    run["stop"] = {
        "code": "review_incomplete",
        "category": "operational",
        "phase": PLANNING,
        "message": "review incomplete",
        "details": {"loop_id": loop.id},
    }
    store.save_run(run_id, run, expected)
    return run_id


def test_review_incomplete_validator_propagates_review_access_errors(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_review_incomplete_paused_run(store)
    stop = store.load_run(run_id)["stop"]
    with patch.object(FileRunStore, "load_review", side_effect=PermissionError("denied")):
        with pytest.raises(PermissionError):
            validate_review_incomplete_stop(store, run_id, stop)
    with patch.object(
        FileRunStore, "load_review", side_effect=PersistenceError("corrupt review")
    ):
        with pytest.raises(PersistenceError):
            validate_review_incomplete_stop(store, run_id, stop)


@pytest.mark.parametrize(
    "exc, code",
    [
        (PermissionError("denied"), "operational_error"),
        (PersistenceError("corrupt review"), "corrupt_run"),
    ],
)
@pytest.mark.parametrize("stream_json", [True, False])
def test_resume_review_access_errors_keep_run_access_codes(
    tmp_path: Path, exc: BaseException, code: str, stream_json: bool
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_review_incomplete_paused_run(store)
    prepared = {"done": False}
    from top_down_planning.cli.user import prepare_resume as real_prepare

    def prepare_then_mark(*args, **kwargs):
        result = real_prepare(*args, **kwargs)
        prepared["done"] = True
        return result

    real_load = FileRunStore.load_review

    def load_review_after_prepare(self, rid, review_id):
        if prepared["done"] and rid == run_id:
            raise exc
        return real_load(self, rid, review_id)

    check_argv = _resume_check_argv(run_id, store.root)
    apply_argv = ["resume", "--run", run_id, "--runs-dir", str(store.root)]
    if stream_json:
        check_argv = [*check_argv, "--stream-json"]
        apply_argv.append("--stream-json")

    with patch.object(FileRunStore, "load_review", load_review_after_prepare):
        check_result = run_cli(check_argv)
        with patch("top_down_planning.cli.user.prepare_resume", prepare_then_mark):
            apply_result = run_cli(apply_argv)

    _assert_no_traceback(check_result)
    assert check_result.exit_code == 0
    if stream_json:
        check_payload = _stdout_json(check_result)
        assert check_payload.get("error", {}).get("code") != "resume_preparation_blocked"
        if code == "operational_error":
            _assert_operational_without_traceback(apply_result)
        else:
            _assert_structured_error(apply_result, code)
    else:
        _assert_no_traceback(apply_result)
        assert apply_result.exit_code != 0
        assert "resume_apply_blocked" not in apply_result.stderr
        assert "resume_preparation_blocked" not in apply_result.stderr


def _publish_valid_child_run_production_revision(
    store: FileRunStore,
    run_id: str,
    *,
    load_run=None,
    load_production=None,
) -> None:
    read_run = load_run or FileRunStore.load_run
    read_production = load_production or FileRunStore.load_production
    run = read_run(store, run_id)
    production = read_production(store, run_id)
    new_production = dict(production)
    new_production["revision"] = int(production["revision"]) + 1
    new_run = bind_run_digests_for_production_update(dict(run), new_production)
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


def test_resume_check_child_delivery_uses_one_child_snapshot(tmp_path: Path) -> None:
    store, parent_id, child_id = _attached_parent_and_child(tmp_path)
    before = store.load_canonical_snapshot(child_id)
    before_rev = int(before.run["revision"])
    bumped = {"done": False}
    real_load_run = FileRunStore.load_run
    real_load_production = FileRunStore.load_production
    real_snapshot = FileRunStore.load_canonical_snapshot

    def bump_after_child_read(self, rid, *args, **kwargs):
        record = real_load_run(self, rid)
        if rid == child_id and not bumped["done"]:
            bumped["done"] = True
            _publish_valid_child_run_production_revision(
                self,
                rid,
                load_run=real_load_run,
                load_production=real_load_production,
            )
        return record

    def snapshot_then_bump(self, rid):
        snap = real_snapshot(self, rid)
        if rid == child_id and not bumped["done"]:
            bumped["done"] = True
            _publish_valid_child_run_production_revision(
                self,
                rid,
                load_run=real_load_run,
                load_production=real_load_production,
            )
        return snap

    argv = [*_resume_check_argv(parent_id, store.root), "--stream-json"]
    with (
        patch.object(FileRunStore, "load_run", bump_after_child_read),
        patch.object(FileRunStore, "load_canonical_snapshot", snapshot_then_bump),
    ):
        result = run_cli(argv)

    _assert_no_traceback(result)
    after = store.load_run(child_id)
    assert int(after["revision"]) == before_rev + 1
    assert result.exit_code == 0
    payload = _stdout_json(result)
    assert "error" not in payload
