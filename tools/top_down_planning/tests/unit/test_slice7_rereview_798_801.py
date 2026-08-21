"""Slice 7 re-review regressions for residual 775/789 and new 798–801."""

from __future__ import annotations

import json
import shlex
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core_tools.persistence import PersistenceError
from top_down_planning.domain.run_ownership import RunOwnershipError
from top_down_planning.observability import ObservabilityContext
from top_down_planning.orchestrator.engine import RunContinuationResult
from top_down_planning.package.builder import ExecutionPackageBuilder
from top_down_planning.persistence import FileRunStore
from tests.conftest import run_cli
from tests.helpers import write_config
from tests.support.run_builders import _planning_run_at_validated
from tests.support.run_builders import _built_package
from tests.support.run_builders import _create_paused_production_run
from tests.support.cli_fakes import _assert_no_traceback
from tests.support.cli_fakes import _stdout_json
from tests.unit.test_slice7_rereview_768_774 import _run_dirs
from tests.unit.test_slice7_rereview_784_790 import _planning_argv
from tests.unit.test_slice7_rereview_791_796 import _rename_then_interrupt_when


def _json_objects(text: str) -> list[dict]:
    decoder = json.JSONDecoder()
    objects: list[dict] = []
    idx = 0
    body = text.strip()
    while idx < len(body):
        while idx < len(body) and body[idx].isspace():
            idx += 1
        if idx >= len(body):
            break
        obj, end = decoder.raw_decode(body, idx)
        if isinstance(obj, dict):
            objects.append(obj)
        idx = end
    return objects


def _next_argv(text: str) -> list[str]:
    for line in text.splitlines():
        if line.startswith("Next:"):
            return shlex.split(line[len("Next:") :].strip())
    raise AssertionError(f"no Next: line in {text!r}")


@pytest.mark.parametrize("stream_json", [True, False])
@pytest.mark.parametrize(
    "exc,code",
    [
        (PersistenceError("resume persist failed"), "corrupt_run"),
        (RunOwnershipError("owned", code="run_owned_by_live_process"), "run_owned_by_live_process"),
        (PermissionError("resume io denied"), "operational_error"),
    ],
)
def test_resume_engine_failures_are_normalized(tmp_path: Path, stream_json: bool, exc, code) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_paused_production_run(store)
    engine = MagicMock()
    engine.continue_run.side_effect = exc
    argv = ["resume", "--run", run_id, "--runs-dir", str(store.root)]
    if stream_json:
        argv.append("--stream-json")
    with (
        patch("top_down_planning.cli.user.apply_resume_plan_atomically"),
        patch("top_down_planning.cli.user._build_run_engine", return_value=engine),
    ):
        result = run_cli(argv)
    _assert_no_traceback(result)
    assert result.exit_code == 1
    text = result.stdout + result.stderr
    if stream_json:
        objects = _json_objects(result.stdout)
        assert len(objects) == 1
        payload = objects[0]
        assert payload["error"]["code"] == code
        assert payload.get("run_id") == run_id
        assert payload["recovery"]["runs_dir"] == str(store.root)
    else:
        assert run_id in text
        assert str(store.root) in text


@pytest.mark.parametrize("command", ["run", "prepare", "resume", "execute"])
def test_observability_close_failure_does_not_emit_second_payload(tmp_path: Path, command: str) -> None:
    engine = MagicMock()
    engine.continue_run.side_effect = PersistenceError("engine persist failed")
    close = MagicMock(side_effect=PermissionError("jsonl close denied"))
    if command == "execute":
        store, _, package = _built_package(tmp_path)
        argv = [
            "execute",
            "--manifest",
            str(package.manifest_path),
            "--runs-dir",
            str(store.root),
            "--stream-json",
        ]
        patches = [patch("top_down_planning.cli.execute._build_run_engine", return_value=engine)]
        expected_id = None
    elif command == "resume":
        store = FileRunStore(tmp_path / "runs")
        run_id = _create_paused_production_run(store)
        argv = ["resume", "--run", run_id, "--runs-dir", str(store.root), "--stream-json"]
        patches = [
            patch("top_down_planning.cli.user.apply_resume_plan_atomically"),
            patch("top_down_planning.cli.user._build_run_engine", return_value=engine),
        ]
        expected_id = run_id
    else:
        config_path = write_config(
            tmp_path / "cfg.yaml",
            "run:\n  output_goal: Ship it.\n"
            f"project:\n  workspace: {tmp_path}\nprovider:\n  name: stub\n",
        )
        argv = [
            command,
            "--config",
            str(config_path),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--stream-json",
        ]
        if command == "prepare":
            argv.extend(["--output", str(tmp_path / "pkg")])
        module = "user" if command == "run" else command
        patches = [patch(f"top_down_planning.cli.{module}._build_run_engine", return_value=engine)]
        if command == "prepare":
            from tests.support.cli_fakes import _patch_prepare_plan_validated

            patches.append(_patch_prepare_plan_validated())
        expected_id = None
    with ExitStack() as stack:
        for item in patches:
            stack.enter_context(item)
        stack.enter_context(
            patch("top_down_planning.observability.ObservabilityContext.close", close)
        )
        result = run_cli(argv)
    _assert_no_traceback(result)
    objects = _json_objects(result.stdout)
    assert len(objects) == 1
    payload = objects[0]
    assert payload["ok"] is False
    assert payload["error"]["code"] == "corrupt_run"
    leftover = _run_dirs(tmp_path / "runs" if command != "execute" else store.root)
    run_id = expected_id or payload.get("run_id")
    assert run_id
    assert any(path.name == run_id for path in leftover)
    assert payload.get("run_id") == run_id


@pytest.mark.parametrize("stream_json", [True, False])
@pytest.mark.parametrize(
    "failing_name",
    ["finalize_user_cancel", "notify_run_outcome", "ObservabilityContext.emit"],
)
def test_interrupt_handler_normalizes_follow_on_failures(
    tmp_path: Path, stream_json: bool, failing_name: str
) -> None:
    config_path = write_config(
        tmp_path / "cfg.yaml",
        "run:\n  output_goal: Ship it.\n"
        f"project:\n  workspace: {tmp_path}\nprovider:\n  name: stub\n",
    )
    engine = MagicMock()
    engine.continue_run.side_effect = KeyboardInterrupt
    argv = ["run", "--config", str(config_path), "--runs-dir", str(tmp_path / "runs")]
    if stream_json:
        argv.append("--stream-json")
    fail = PersistenceError("interrupt follow-on failed")
    extra_patches = []
    if failing_name == "ObservabilityContext.emit":
        real_emit = ObservabilityContext.emit

        def emit_cancel_fails(self, event, *args, **kwargs):
            category = str(getattr(event, "category", "") or "")
            if "cancel" in category:
                raise fail
            return real_emit(self, event, *args, **kwargs)

        extra_patches.append(
            patch.object(ObservabilityContext, "emit", emit_cancel_fails)
        )
    elif failing_name == "notify_run_outcome":
        extra_patches.append(
            patch("top_down_planning.cli.user.notify_run_outcome", side_effect=fail)
        )
    else:
        extra_patches.append(
            patch("top_down_planning.cli.user.finalize_user_cancel", side_effect=fail)
        )
    with ExitStack() as stack:
        stack.enter_context(
            patch("top_down_planning.cli.user._build_run_engine", return_value=engine)
        )
        stack.enter_context(
            patch("top_down_planning.cli.user.holds_run_ownership", return_value=True)
        )
        for item in extra_patches:
            stack.enter_context(item)
        result = run_cli(argv)
    leftover = _run_dirs(tmp_path / "runs")
    assert leftover
    run_id = leftover[0].name
    _assert_no_traceback(result)
    assert result.exit_code == 130
    text = result.stdout + result.stderr
    assert run_id in text
    if stream_json:
        objects = _json_objects(result.stdout)
        assert len(objects) == 1
        payload = objects[0]
        assert payload.get("run_id") == run_id
        if failing_name == "finalize_user_cancel":
            assert payload.get("command_interrupted") is True
            assert payload.get("cancelled") is not True
        else:
            assert payload.get("cancelled") is True
    else:
        assert "Traceback" not in text


def test_human_command_interrupt_identifies_published_run(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "cfg.yaml",
        "run:\n  output_goal: Ship it.\n"
        f"project:\n  workspace: {tmp_path}\nprovider:\n  name: stub\n",
    )

    def is_publish(src: Path, dest: Path) -> bool:
        return src.name.startswith(".creating-") and dest.name.startswith("run-")

    argv = ["run", "--config", str(config_path), "--runs-dir", str(tmp_path / "runs")]
    with patch.object(Path, "rename", _rename_then_interrupt_when(is_publish)):
        result = run_cli(argv)
    leftover = _run_dirs(tmp_path / "runs")
    _assert_no_traceback(result)
    assert leftover
    assert result.exit_code == 130
    text = result.stderr + result.stdout
    assert f"Run: {leftover[0].name}" in text
    assert str(tmp_path / "runs") in text


def test_create_run_interrupt_survives_failed_post_publish_reread(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "cfg.yaml",
        "run:\n  output_goal: Ship it.\n"
        f"project:\n  workspace: {tmp_path}\nprovider:\n  name: stub\n",
    )
    real_read = FileRunStore._read_run

    def fail_after_publish(self, rid):
        if (self.root / rid).is_dir():
            raise PersistenceError("post-publish reread failed")
        return real_read(self, rid)

    def is_publish(src: Path, dest: Path) -> bool:
        return src.name.startswith(".creating-") and dest.name.startswith("run-")

    argv = [
        "run",
        "--config",
        str(config_path),
        "--runs-dir",
        str(tmp_path / "runs"),
        "--stream-json",
    ]
    with (
        patch.object(Path, "rename", _rename_then_interrupt_when(is_publish)),
        patch.object(FileRunStore, "_read_run", fail_after_publish),
    ):
        structured = run_cli(argv)
    leftover = _run_dirs(tmp_path / "runs")
    assert leftover
    structured_id = leftover[0].name
    _assert_no_traceback(structured)
    assert structured.exit_code == 130
    payload = _stdout_json(structured)
    assert payload.get("run_id") == structured_id

    with (
        patch.object(Path, "rename", _rename_then_interrupt_when(is_publish)),
        patch.object(FileRunStore, "_read_run", fail_after_publish),
    ):
        human = run_cli(argv[:-1])
    human_id = [path.name for path in _run_dirs(tmp_path / "runs") if path.name != structured_id][-1]
    _assert_no_traceback(human)
    assert human.exit_code == 130
    assert f"Run: {human_id}" in human.stderr + human.stdout


def test_prepare_snapshot_failure_includes_store_locator(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T005001-005001"
    _planning_run_at_validated(store, tmp_path, run_id)
    with patch.object(
        FileRunStore, "load_canonical_snapshot", side_effect=PersistenceError("snapshot torn")
    ):
        result = run_cli(
            [
                "prepare",
                "--planning-run",
                run_id,
                "--runs-dir",
                str(store.root),
                "--output",
                str(tmp_path / "pkg"),
            ]
        )
    _assert_no_traceback(result)
    argv = _next_argv(result.stderr + result.stdout)
    assert argv[argv.index("--runs-dir") + 1] == str(store.root)


def test_package_exists_recovery_includes_replace(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T005002-005002"
    _planning_run_at_validated(store, tmp_path, run_id)
    output = tmp_path / "pkg"
    ExecutionPackageBuilder().build_from_planning_run(store, run_id, output_dir=output)
    result = run_cli(_planning_argv(tmp_path, run_id, output))
    _assert_no_traceback(result)
    argv = _next_argv(result.stderr + result.stdout)
    assert "--replace" in argv


def test_status_access_failure_includes_store_locator(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = _create_paused_production_run(store)
    with patch.object(FileRunStore, "load_canonical_snapshot", side_effect=PersistenceError("torn")):
        result = run_cli(["status", "--run", run_id, "--runs-dir", str(store.root)])
    _assert_no_traceback(result)
    argv = _next_argv(result.stderr + result.stdout)
    assert argv[argv.index("--run") + 1] == run_id
    assert argv[argv.index("--runs-dir") + 1] == str(store.root)


@pytest.mark.parametrize("nasty", ["TDP Runs", 'quote"here', "semi;colon", "dollar$(x)"])
def test_human_recovery_quotes_shell_metacharacters_in_paths(tmp_path: Path, nasty: str) -> None:
    runs = tmp_path / nasty
    store = FileRunStore(runs)
    run_id = "run-20260101T005003-005003"
    _planning_run_at_validated(store, tmp_path, run_id)
    output = tmp_path / "out dir"
    with patch(
        "top_down_planning.cli.prepare.ExecutionPackageBuilder.build_from_planning_run",
        side_effect=ValueError("materialize failed"),
    ):
        result = run_cli(
            [
                "prepare",
                "--planning-run",
                run_id,
                "--runs-dir",
                str(runs),
                "--output",
                str(output),
                "--replace",
            ]
        )
    argv = _next_argv(result.stderr + result.stdout)
    assert argv[0] == "tdp"
    assert argv[argv.index("--runs-dir") + 1] == str(runs)
    assert argv[argv.index("--output") + 1] == str(output.resolve())
