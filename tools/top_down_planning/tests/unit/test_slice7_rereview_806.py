"""Slice 7 re-review regressions for TDP-CLI-806 prepare signal semantics."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from top_down_planning.package.builder import ExecutionPackageBuilder
from top_down_planning.persistence import FileRunStore
from tests.conftest import run_cli
from tests.helpers import write_config
from tests.support.run_builders import _planning_run_at_validated
from tests.support.cli_fakes import _assert_no_traceback
from tests.unit.test_slice7_rereview_768_774 import _run_dirs
from tests.unit.test_slice7_rereview_784_790 import _planning_argv
from tests.unit.test_slice7_rereview_798_801 import _json_objects, _next_argv


def _assert_prepare_command_interrupted(result, run_id: str, runs_dir: Path, *, stream_json: bool) -> None:
    _assert_no_traceback(result)
    assert result.exit_code == 130
    if stream_json:
        objects = _json_objects(result.stdout)
        assert len(objects) == 1
        payload = objects[0]
        assert payload.get("command_interrupted") is True
        assert payload.get("cancelled") is not True
        assert payload.get("run_id") == run_id
        assert payload["recovery"]["command"] == "status"
        assert payload["recovery"]["run_id"] == run_id
        assert payload["recovery"]["runs_dir"] == str(runs_dir)
    else:
        assert f"Run: {run_id}" in result.stderr
        assert "Command interrupted" in result.stderr
        assert f"Run: {run_id}" not in result.stdout
        recovery = _next_argv(result.stderr)
        assert recovery[1] == "status"
        assert recovery[recovery.index("--run") + 1] == run_id
        assert recovery[recovery.index("--runs-dir") + 1] == str(runs_dir)


@pytest.mark.parametrize("stream_json", [True, False])
def test_prepare_planning_run_snapshot_interrupt_is_command_interrupted(
    tmp_path: Path, stream_json: bool
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T006001-006001"
    _planning_run_at_validated(store, tmp_path, run_id)
    extra = ["--stream-json"] if stream_json else []
    with patch.object(
        FileRunStore, "load_canonical_snapshot", side_effect=KeyboardInterrupt
    ):
        result = run_cli(_planning_argv(tmp_path, run_id, tmp_path / "pkg", extra))
    _assert_prepare_command_interrupted(
        result, run_id, store.root, stream_json=stream_json
    )
    assert store.load_run(run_id)["status"] != "paused" or (
        store.load_run(run_id).get("stop") or {}
    ).get("code") != "user_cancelled"


@pytest.mark.parametrize("stream_json", [True, False])
def test_prepare_existing_run_builder_interrupt_before_publish_is_command_interrupted(
    tmp_path: Path, stream_json: bool
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T006002-006002"
    _planning_run_at_validated(store, tmp_path, run_id)
    extra = ["--stream-json"] if stream_json else []
    with patch.object(
        ExecutionPackageBuilder,
        "build_from_planning_run",
        side_effect=KeyboardInterrupt,
    ):
        result = run_cli(_planning_argv(tmp_path, run_id, tmp_path / "pkg", extra))
    _assert_prepare_command_interrupted(
        result, run_id, store.root, stream_json=stream_json
    )
    assert not (tmp_path / "pkg").exists()


@pytest.mark.parametrize("stream_json", [True, False])
def test_fresh_prepare_pre_publication_interrupt_does_not_advertise_run(
    tmp_path: Path, stream_json: bool
) -> None:
    config_path = write_config(
        tmp_path / "cfg.yaml",
        "run:\n  output_goal: Ship it.\n"
        f"project:\n  workspace: {tmp_path}\nprovider:\n  name: stub\n",
    )
    real_rename = Path.rename

    def interrupt_before_publish(self, target):
        dest = Path(target)
        if self.name.startswith(".creating-") and dest.name.startswith("run-"):
            raise KeyboardInterrupt
        return real_rename(self, dest)

    argv = [
        "prepare",
        "--config",
        str(config_path),
        "--runs-dir",
        str(tmp_path / "runs"),
        "--output",
        str(tmp_path / "pkg"),
    ]
    if stream_json:
        argv.append("--stream-json")
    with patch.object(Path, "rename", interrupt_before_publish):
        result = run_cli(argv)
    _assert_no_traceback(result)
    leftover = [path for path in _run_dirs(tmp_path / "runs") if path.name.startswith("run-")]
    assert leftover == []
    if stream_json:
        objects = _json_objects(result.stdout)
        assert len(objects) == 1
        payload = objects[0]
        assert not payload.get("run_id")
        assert payload.get("command_interrupted") is not True
    else:
        assert "Run:" not in result.stderr
        assert "Next:" not in result.stderr
