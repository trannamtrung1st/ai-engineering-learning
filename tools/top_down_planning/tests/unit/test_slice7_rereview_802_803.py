"""Slice 7 re-review regressions for residual 775/789/799/800 and new 802–803."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core_tools.persistence import PersistenceError
from top_down_planning.observability import ObservabilityContext
from top_down_planning.orchestrator.engine import RunContinuationResult
from top_down_planning.orchestrator.phases import PLAN_VALIDATED, PRODUCTION
from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory
from top_down_planning.orchestrator.sub_tdp_child_driver import PreparedChildResult
from top_down_planning.persistence import FileRunStore
from tests.conftest import run_cli
from tests.helpers import create_run_kwargs, write_config
from tests.unit.test_prepared_runs import _built_package
from tests.unit.test_resume_cli import _create_paused_production_run
from tests.unit.test_slice7_rereview_751_754 import _assert_no_traceback
from tests.unit.test_slice7_rereview_755_758 import _stdout_json
from tests.unit.test_slice7_rereview_768_774 import _run_dirs
from tests.unit.test_slice7_rereview_791_796 import _rename_then_interrupt_when
from tests.unit.test_slice7_rereview_798_801 import _json_objects, _next_argv


def _is_run_publish(src: Path, dest: Path) -> bool:
    return src.name.startswith(".creating-") and dest.name.startswith("run-")


def _cancelled_continuation(run_id: str) -> RunContinuationResult:
    return RunContinuationResult(
        ok=False,
        run_id=run_id,
        phase=PRODUCTION,
        status="paused",
        outcome=None,
        cancelled=True,
        target_reached=False,
        reason="cancelled by user",
    )


def _execute_parent_argv(package, store: FileRunStore, *extra: str) -> list[str]:
    return [
        "execute",
        "--manifest",
        str(package.manifest_path),
        "--runs-dir",
        str(store.root),
        *extra,
    ]


@pytest.mark.parametrize("mode", ["parent", "unit"])
def test_execute_publish_interrupt_keeps_one_identity_and_reuses_run(
    tmp_path: Path, mode: str
) -> None:
    store, _, package = _built_package(tmp_path)
    argv = _execute_parent_argv(package, store, "--stream-json")
    if mode == "unit":
        argv.extend(["--unit", "item-foundation"])

    with patch.object(Path, "rename", _rename_then_interrupt_when(_is_run_publish)):
        first = run_cli(argv)
    leftover = [path for path in _run_dirs(store.root) if path.name.startswith("run-")]
    _assert_no_traceback(first)
    assert first.exit_code == 130
    objects = _json_objects(first.stdout)
    assert len(objects) == 1
    published_id = objects[0].get("run_id")
    assert published_id
    assert any(path.name == published_id for path in leftover)
    assert objects[0].get("command_interrupted") is True

    if mode == "parent":
        engine = MagicMock()
        engine.continue_run.return_value = RunContinuationResult(
            ok=False,
            run_id=published_id,
            phase=PLAN_VALIDATED,
            status="running",
            outcome=None,
            cancelled=False,
            target_reached=False,
        )
        with patch("top_down_planning.cli.execute._build_run_engine", return_value=engine):
            retry = run_cli(argv)
    else:
        child_run = store.load_run(published_id)
        driven = PreparedChildResult(
            run=child_run,
            ok=False,
            cancelled=False,
            status=str(child_run.get("status") or "running"),
            outcome=child_run.get("outcome"),
            phase=str(child_run.get("phase") or PLAN_VALIDATED),
        )
        with patch(
            "top_down_planning.cli.execute.PreparedUnitExecutor.drive_child_run",
            return_value=driven,
        ):
            retry = run_cli(argv)
    _assert_no_traceback(retry)
    after = [path.name for path in _run_dirs(store.root) if path.name.startswith("run-")]
    assert published_id in after
    assert after.count(published_id) == 1
    assert len(after) == len({path.name for path in leftover})


@pytest.mark.parametrize("stream_json", [True, False])
def test_human_primary_error_survives_observability_close_failure(
    tmp_path: Path, stream_json: bool
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_paused_production_run(store)
    engine = MagicMock()
    engine.continue_run.side_effect = PersistenceError("engine persist failed")
    argv = ["resume", "--run", run_id, "--runs-dir", str(store.root)]
    if stream_json:
        argv.append("--stream-json")
    with (
        patch("top_down_planning.cli.user.apply_resume_plan_atomically"),
        patch("top_down_planning.cli.user._build_run_engine", return_value=engine),
        patch(
            "top_down_planning.observability.ObservabilityContext.close",
            side_effect=PermissionError("jsonl close denied"),
        ),
    ):
        result = run_cli(argv)
    _assert_no_traceback(result)
    assert result.exit_code == 1
    if stream_json:
        objects = _json_objects(result.stdout)
        assert len(objects) == 1
        assert objects[0]["error"]["code"] == "corrupt_run"
        assert objects[0].get("run_id") == run_id
    else:
        text = result.stderr
        assert "engine persist failed" in text
        assert run_id in text
        assert "Next:" in text


def test_structured_close_interrupt_does_not_emit_second_payload(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_paused_production_run(store)
    engine = MagicMock()
    engine.continue_run.side_effect = PersistenceError("engine persist failed")
    with (
        patch("top_down_planning.cli.user.apply_resume_plan_atomically"),
        patch("top_down_planning.cli.user._build_run_engine", return_value=engine),
        patch(
            "top_down_planning.observability.ObservabilityContext.close",
            side_effect=KeyboardInterrupt,
        ),
    ):
        result = run_cli(
            ["resume", "--run", run_id, "--runs-dir", str(store.root), "--stream-json"]
        )
    _assert_no_traceback(result)
    objects = _json_objects(result.stdout)
    assert len(objects) == 1
    assert objects[0]["error"]["code"] == "corrupt_run"
    assert objects[0].get("run_id") == run_id
    assert result.exit_code == 1


@pytest.mark.parametrize("stream_json", [True, False])
def test_interrupt_reload_failure_stays_command_interrupted(
    tmp_path: Path, stream_json: bool
) -> None:
    config_path = write_config(
        tmp_path / "cfg.yaml",
        "run:\n  output_goal: Ship it.\n"
        f"project:\n  workspace: {tmp_path}\nprovider:\n  name: stub\n",
    )
    engine = MagicMock()
    interrupted = False

    def continue_then_interrupt(*_args, **_kwargs):
        nonlocal interrupted
        interrupted = True
        raise KeyboardInterrupt

    engine.continue_run.side_effect = continue_then_interrupt
    real_load = FileRunStore.load_run

    def load_after_interrupt(self, run_id, *args, **kwargs):
        if interrupted:
            raise PersistenceError("interrupt reload failed")
        return real_load(self, run_id, *args, **kwargs)

    argv = ["run", "--config", str(config_path), "--runs-dir", str(tmp_path / "runs")]
    if stream_json:
        argv.append("--stream-json")
    with (
        patch("top_down_planning.cli.user._build_run_engine", return_value=engine),
        patch.object(FileRunStore, "load_run", load_after_interrupt),
    ):
        result = run_cli(argv)
    leftover = _run_dirs(tmp_path / "runs")
    assert leftover
    run_id = leftover[0].name
    _assert_no_traceback(result)
    assert result.exit_code == 130
    text = result.stderr + result.stdout
    assert run_id in text
    if stream_json:
        objects = _json_objects(result.stdout)
        assert len(objects) == 1
        assert objects[0].get("command_interrupted") is True
        assert objects[0].get("cancelled") is not True
        assert objects[0].get("run_id") == run_id
        assert objects[0]["recovery"]["command"] == "status"
    else:
        assert result.stdout.strip() == ""
        assert f"Run: {run_id}" in result.stderr


@pytest.mark.parametrize("command", ["prepare", "execute"])
def test_startup_interrupt_after_create_includes_run_identity(
    tmp_path: Path, command: str
) -> None:
    if command == "execute":
        store, _, package = _built_package(tmp_path)
        argv = _execute_parent_argv(package, store, "--stream-json")
        runs_root = store.root
    else:
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
        runs_root = tmp_path / "runs"

    def emit_startup_interrupt(self, event, *args, **kwargs):
        category = str(getattr(event, "category", "") or "")
        if category.endswith(":start"):
            raise KeyboardInterrupt
        return ObservabilityContext.emit(self, event, *args, **kwargs)

    with patch.object(ObservabilityContext, "emit", emit_startup_interrupt):
        result = run_cli(argv)
    leftover = _run_dirs(runs_root)
    assert leftover
    _assert_no_traceback(result)
    assert result.exit_code == 130
    objects = _json_objects(result.stdout)
    assert len(objects) == 1
    run_id = objects[0].get("run_id")
    assert run_id
    assert any(path.name == run_id for path in leftover)


def test_status_missing_production_includes_identity_and_doctor(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_paused_production_run(store)
    (store.run_dir(run_id) / "production.json").unlink()
    result = run_cli(
        ["status", "--run", run_id, "--runs-dir", str(store.root), "--stream-json"]
    )
    _assert_no_traceback(result)
    assert result.exit_code == 1
    payload = _stdout_json(result)
    assert payload["error"]["code"] == "corrupt_run"
    assert payload.get("run_id") == run_id
    assert payload["recovery"]["command"] == "doctor"
    assert payload["recovery"]["runs_dir"] == str(store.root)


def test_doctor_corrupt_run_keeps_locator(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_paused_production_run(store)
    (store.run_dir(run_id) / "run.json").write_text("{not-json", encoding="utf-8")
    result = run_cli(
        ["doctor", "--run", run_id, "--runs-dir", str(store.root), "--stream-json"]
    )
    _assert_no_traceback(result)
    payload = _stdout_json(result)
    assert payload["error"]["code"] == "corrupt_run"
    assert payload.get("run_id") == run_id
    assert payload["recovery"]["runs_dir"] == str(store.root)


def test_attach_access_failure_keeps_parent_child_locator(tmp_path: Path) -> None:
    store, _, package = _built_package(tmp_path)
    config = create_run_kwargs(tmp_path)["resolved_config"]
    parent_id = PreparedRunFactory().create_parent_run(
        store,
        package,
        resolved_config=config,
        invocation={"command": "execute", "observability": {}},
    )
    child_id = PreparedRunFactory().create_child_run(
        store,
        package,
        package.units["item-foundation"],
        resolved_config=config,
        invocation={"command": "execute", "observability": {}},
    )
    with patch(
        "top_down_planning.cli.sub_tdp.resolve_run_dir",
        side_effect=PersistenceError("attach store torn"),
    ):
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
    _assert_no_traceback(result)
    payload = _stdout_json(result)
    assert payload["error"]["code"] == "corrupt_run"
    assert payload.get("run_id") in {parent_id, child_id}
    assert payload.get("parent_run_id") == parent_id
    assert payload.get("child_run_id") == child_id
    assert payload["recovery"]["runs_dir"] == str(store.root)


@pytest.mark.parametrize("stream_json", [True, False])
@pytest.mark.parametrize("log_level", ["quiet", "normal"])
@pytest.mark.parametrize("kind", ["cancelled", "command_interrupted", "ctrl_c"])
def test_signal_results_use_stderr_in_human_mode(
    tmp_path: Path, stream_json: bool, log_level: str, kind: str
) -> None:
    engine = MagicMock()
    extra_patches = []
    if kind == "cancelled":
        store = FileRunStore(tmp_path / "runs")
        run_id = _create_paused_production_run(store)
        engine.continue_run.return_value = _cancelled_continuation(run_id)
        argv = [
            "resume",
            "--run",
            run_id,
            "--runs-dir",
            str(store.root),
            "--log-level",
            log_level,
        ]
        extra_patches.append(patch("top_down_planning.cli.user.apply_resume_plan_atomically"))
        engine_target = "top_down_planning.cli.user._build_run_engine"
    else:
        config_path = write_config(
            tmp_path / "cfg.yaml",
            "run:\n  output_goal: Ship it.\n"
            f"project:\n  workspace: {tmp_path}\nprovider:\n  name: stub\n",
        )
        engine.continue_run.side_effect = KeyboardInterrupt
        extra_patches.append(
            patch(
                "top_down_planning.cli.user.holds_run_ownership",
                return_value=kind == "ctrl_c",
            )
        )
        argv = [
            "run",
            "--config",
            str(config_path),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--log-level",
            log_level,
        ]
        engine_target = "top_down_planning.cli.user._build_run_engine"
        run_id = None
    if stream_json:
        argv.append("--stream-json")
    with ExitStack() as stack:
        stack.enter_context(patch(engine_target, return_value=engine))
        for item in extra_patches:
            stack.enter_context(item)
        result = run_cli(argv)
    if run_id is None:
        leftover = _run_dirs(tmp_path / "runs")
        assert leftover
        run_id = leftover[0].name
    _assert_no_traceback(result)
    assert result.exit_code == 130
    if stream_json:
        objects = _json_objects(result.stdout)
        assert len(objects) == 1
        payload = objects[0]
        assert payload.get("run_id") == run_id
        if kind == "command_interrupted":
            assert payload.get("command_interrupted") is True
            assert payload.get("cancelled") is not True
        else:
            assert payload.get("cancelled") is True
    else:
        assert f"Run: {run_id}" in result.stderr
        assert "Next:" in result.stderr
        assert f"Run: {run_id}" not in result.stdout
        recovery = _next_argv(result.stderr)
        assert recovery[recovery.index("--run") + 1] == run_id
