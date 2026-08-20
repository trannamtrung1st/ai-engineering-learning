"""Slice 7 re-review regressions for residual 789 and new 804."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core_tools.persistence import PersistenceError
from top_down_planning.orchestrator.engine import RunContinuationResult
from top_down_planning.orchestrator.prepared_unit_executor import PreparedUnitExecutor
from top_down_planning.persistence import FileRunStore
from tests.conftest import run_cli
from tests.helpers import accept_child_run
from tests.unit.test_prepared_runs import _built_package
from tests.unit.test_resume_cli import _create_paused_production_run
from tests.unit.test_slice7_rereview_751_754 import _assert_no_traceback
from tests.unit.test_slice7_rereview_768_774 import _run_dirs
from tests.unit.test_slice7_rereview_798_801 import _json_objects, _next_argv
from tests.unit.test_sub_tdp_attach_cli import _parent_with_orchestration


def _assert_command_interrupted(result, run_id: str, *, stream_json: bool) -> None:
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
    else:
        assert f"Run: {run_id}" in result.stderr
        assert "Command interrupted" in result.stderr
        assert f"Run: {run_id}" not in result.stdout
        recovery = _next_argv(result.stderr)
        assert recovery[0] == "tdp"
        assert recovery[1] == "status"
        assert recovery[recovery.index("--run") + 1] == run_id


def _attach_argv(tmp_path: Path, parent_id: str, child_id: str, *extra: str) -> list[str]:
    return [
        "sub-tdp",
        "attach",
        "--parent",
        parent_id,
        "--child",
        child_id,
        "--runs-dir",
        str(tmp_path / "runs"),
        *extra,
    ]


@pytest.mark.parametrize("stream_json", [True, False])
def test_execute_load_production_interrupt_is_command_interrupted(
    tmp_path: Path, stream_json: bool
) -> None:
    store, planning_id, package = _built_package(tmp_path)
    real_load = FileRunStore.load_production

    def load_production_then_interrupt(self, run_id, *args, **kwargs):
        if run_id != planning_id:
            raise KeyboardInterrupt
        return real_load(self, run_id, *args, **kwargs)

    argv = [
        "execute",
        "--manifest",
        str(package.manifest_path),
        "--runs-dir",
        str(store.root),
    ]
    if stream_json:
        argv.append("--stream-json")
    with patch.object(FileRunStore, "load_production", load_production_then_interrupt):
        result = run_cli(argv)
    leftover = [
        path.name
        for path in _run_dirs(store.root)
        if path.name.startswith("run-") and path.name != planning_id
    ]
    assert leftover
    _assert_command_interrupted(result, leftover[0], stream_json=stream_json)


@pytest.mark.parametrize("stream_json", [True, False])
def test_resume_apply_interrupt_before_commit_is_command_interrupted(
    tmp_path: Path, stream_json: bool
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_paused_production_run(store)
    argv = ["resume", "--run", run_id, "--runs-dir", str(store.root)]
    if stream_json:
        argv.append("--stream-json")
    with patch(
        "top_down_planning.cli.user.apply_resume_plan_atomically",
        side_effect=KeyboardInterrupt,
    ):
        result = run_cli(argv)
    _assert_command_interrupted(result, run_id, stream_json=stream_json)
    run = store.load_run(run_id)
    assert run["status"] == "paused"
    assert run.get("stop", {}).get("code") != "user_cancelled"


@pytest.mark.parametrize("stream_json", [True, False])
def test_resume_apply_interrupt_after_commit_is_command_interrupted(
    tmp_path: Path, stream_json: bool
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_paused_production_run(store)
    from top_down_planning.cli.user import apply_resume_plan_atomically

    def apply_then_interrupt(*args, **kwargs):
        apply_resume_plan_atomically(*args, **kwargs)
        raise KeyboardInterrupt

    engine = MagicMock()
    engine.continue_run.return_value = RunContinuationResult(
        ok=False,
        run_id=run_id,
        phase="production",
        status="running",
        outcome=None,
        cancelled=False,
        target_reached=False,
    )
    argv = ["resume", "--run", run_id, "--runs-dir", str(store.root)]
    if stream_json:
        argv.append("--stream-json")
    with (
        patch(
            "top_down_planning.cli.user.apply_resume_plan_atomically",
            side_effect=apply_then_interrupt,
        ),
        patch("top_down_planning.cli.user._build_run_engine", return_value=engine),
    ):
        result = run_cli(argv)
    _assert_command_interrupted(result, run_id, stream_json=stream_json)
    assert store.load_run(run_id)["status"] == "running"


@pytest.mark.parametrize("stream_json", [True, False])
def test_attach_interrupt_after_commit_is_command_interrupted(
    tmp_path: Path, stream_json: bool
) -> None:
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
    real_commit = FileRunStore.commit

    def commit_then_interrupt(self, *args, **kwargs):
        result = real_commit(self, *args, **kwargs)
        raise KeyboardInterrupt
        return result

    argv = _attach_argv(tmp_path, parent_id, child_id)
    if stream_json:
        argv.append("--stream-json")
    with patch.object(FileRunStore, "commit", commit_then_interrupt):
        result = run_cli(argv)
    _assert_command_interrupted(result, parent_id, stream_json=stream_json)
    from top_down_planning.persistence.sub_tdp_state import load_sub_tdp_state

    state = load_sub_tdp_state(store.load_production(parent_id))
    assert state is not None
    assert any(unit.get("child_run_id") == child_id for unit in state.get("units") or [])


def test_attach_parent_load_failure_recovers_parent(tmp_path: Path) -> None:
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
    real_load = FileRunStore.load_run

    def fail_parent(self, run_id, *args, **kwargs):
        if run_id == parent_id:
            raise PersistenceError("parent canonical torn")
        return real_load(self, run_id, *args, **kwargs)

    with patch.object(FileRunStore, "load_run", fail_parent):
        result = run_cli(_attach_argv(tmp_path, parent_id, child_id, "--stream-json"))
    _assert_no_traceback(result)
    objects = _json_objects(result.stdout)
    assert len(objects) == 1
    payload = objects[0]
    assert payload["error"]["code"] == "corrupt_run"
    assert payload.get("run_id") == parent_id
    assert payload.get("parent_run_id") == parent_id
    assert payload.get("child_run_id") == child_id
    assert payload["recovery"]["command"] == "doctor"
    assert payload["recovery"]["run_id"] == parent_id


@pytest.mark.parametrize("failing", ["load_run", "load_production"])
def test_attach_child_access_failure_recovers_child(tmp_path: Path, failing: str) -> None:
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
    real = getattr(FileRunStore, failing)

    def fail_child(self, run_id, *args, **kwargs):
        if run_id == child_id:
            raise PersistenceError(f"child {failing} torn")
        return real(self, run_id, *args, **kwargs)

    with patch.object(FileRunStore, failing, fail_child):
        result = run_cli(_attach_argv(tmp_path, parent_id, child_id, "--stream-json"))
    _assert_no_traceback(result)
    objects = _json_objects(result.stdout)
    assert len(objects) == 1
    payload = objects[0]
    assert payload["error"]["code"] == "corrupt_run"
    assert payload.get("run_id") == child_id
    assert payload.get("parent_run_id") == parent_id
    assert payload.get("child_run_id") == child_id
    assert payload["recovery"]["command"] == "doctor"
    assert payload["recovery"]["run_id"] == child_id
