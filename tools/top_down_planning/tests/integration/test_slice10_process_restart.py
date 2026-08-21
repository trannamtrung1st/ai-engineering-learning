"""Slice 10 process-boundary proofs: restart, cancel, competing writers."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from top_down_planning.persistence import FileRunStore
from tests.integration.e2e_helpers import write_e2e_config
from tests.support.slice10 import (
    assert_audit_events_agree_with_snapshots,
    run_tdp_process,
    slice10_child_pythonpath,
)


@pytest.mark.integration
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process-boundary contract")
def test_process_restart_between_phase_steps_reaches_accepted(tmp_path: Path) -> None:
    config_path = write_e2e_config(tmp_path / "run.yaml")
    runs_dir = tmp_path / "runs"

    planned = run_tdp_process(
        [
            "run",
            "--config",
            str(config_path),
            "--runs-dir",
            str(runs_dir),
            "--until",
            "plan",
            "--stream-json",
            "--no-notify",
            "--no-color",
        ],
        cwd=tmp_path,
        runs_dir=runs_dir,
        script="plan",
    )
    assert planned.returncode == 0, planned.stderr
    planned_payload = planned.json()
    run_id = planned_payload["run_id"]
    assert planned_payload["ok"] is True
    assert planned_payload["phase"] != "planning"

    validated = run_tdp_process(
        [
            "resume",
            "--run",
            run_id,
            "--runs-dir",
            str(runs_dir),
            "--until",
            "validated",
            "--stream-json",
            "--no-notify",
            "--no-color",
        ],
        cwd=tmp_path,
        runs_dir=runs_dir,
        script="approve_plan",
    )
    assert validated.returncode == 0, validated.stderr
    validated_payload = validated.json()
    assert validated_payload["ok"] is True
    assert validated_payload["phase"] in {"plan_validated", "production"}

    completed = run_tdp_process(
        [
            "resume",
            "--run",
            run_id,
            "--runs-dir",
            str(runs_dir),
            "--until",
            "completed",
            "--stream-json",
            "--no-notify",
            "--no-color",
        ],
        cwd=tmp_path,
        runs_dir=runs_dir,
        script="finish_production",
    )
    assert completed.returncode == 0, completed.stderr
    completed_payload = completed.json()
    assert completed_payload["ok"] is True
    assert completed_payload["outcome"] == "accepted"

    status = run_tdp_process(
        ["status", "--run", run_id, "--runs-dir", str(runs_dir), "--stream-json", "--no-color"],
        cwd=tmp_path,
        runs_dir=runs_dir,
    )
    inspect = run_tdp_process(
        ["inspect", "--run", run_id, "--runs-dir", str(runs_dir), "--stream-json", "--no-color"],
        cwd=tmp_path,
        runs_dir=runs_dir,
    )
    assert status.returncode == 0, status.stderr
    assert inspect.returncode == 0, inspect.stderr
    assert status.json()["run"]["status"] == "completed"
    assert status.json()["run"]["outcome"] == "accepted"
    store = FileRunStore(runs_dir)
    assert_audit_events_agree_with_snapshots(store, run_id)


@pytest.mark.integration
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX SIGINT CLI contract")
def test_cancel_during_provider_execution_leaves_no_orphan_process(tmp_path: Path) -> None:
    config_path = write_e2e_config(tmp_path / "run.yaml")
    runs_dir = tmp_path / "runs"
    ready_path = tmp_path / "stub-turn-ready"
    env = os.environ.copy()
    env["PYTHONPATH"] = slice10_child_pythonpath(include_sitecustomize=True)
    env["TDP_SLICE10_SCRIPT"] = "block"
    env["TDP_SLICE10_RUNS_DIR"] = str(runs_dir)
    env["TDP_STUB_TURN_READY_PATH"] = str(ready_path)
    env["TDP_STUB_TURN_BLOCK_SECONDS"] = "10"

    child = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "top_down_planning",
            "run",
            "--config",
            str(config_path),
            "--runs-dir",
            str(runs_dir),
            "--stream-json",
            "--no-notify",
            "--no-color",
        ],
        cwd=str(tmp_path),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready_path.is_file():
            if child.poll() is not None:
                stdout, stderr = child.communicate()
                raise AssertionError(
                    "tdp run exited before the blocked stub turn: "
                    f"code={child.returncode} stdout={stdout!r} stderr={stderr!r}"
                )
            if time.monotonic() >= deadline:
                child.send_signal(signal.SIGKILL)
                stdout, stderr = child.communicate()
                raise AssertionError(
                    f"timed out waiting for stub turn: stdout={stdout!r} stderr={stderr!r}"
                )
            time.sleep(0.05)
        child.send_signal(signal.SIGINT)
        child.wait(timeout=15)
    except Exception:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        raise

    assert child.returncode == 130
    store = FileRunStore(runs_dir)
    from tests.helpers import only_run_id

    run = store.load_run(only_run_id(store))
    assert run["status"] == "paused"
    assert run["stop"]["code"] == "user_cancelled"
    assert child.poll() is not None
    with pytest.raises(OSError):
        os.kill(child.pid, 0)


@pytest.mark.integration
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX run-ownership contract")
def test_competing_resume_against_same_revision_is_rejected(tmp_path: Path) -> None:
    config_path = write_e2e_config(tmp_path / "run.yaml")
    runs_dir = tmp_path / "runs"
    planned = run_tdp_process(
        [
            "run",
            "--config",
            str(config_path),
            "--runs-dir",
            str(runs_dir),
            "--until",
            "plan",
            "--stream-json",
            "--no-notify",
            "--no-color",
        ],
        cwd=tmp_path,
        runs_dir=runs_dir,
        script="plan",
    )
    assert planned.returncode == 0, planned.stderr
    run_id = planned.json()["run_id"]
    store = FileRunStore(runs_dir)
    ready_path = tmp_path / "owner-ready"
    env = os.environ.copy()
    env["PYTHONPATH"] = slice10_child_pythonpath(include_sitecustomize=True)
    env["TDP_SLICE10_SCRIPT"] = "block"
    env["TDP_SLICE10_RUNS_DIR"] = str(runs_dir)
    env["TDP_STUB_TURN_READY_PATH"] = str(ready_path)
    env["TDP_STUB_TURN_BLOCK_SECONDS"] = "10"

    owner = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "top_down_planning",
            "resume",
            "--run",
            run_id,
            "--runs-dir",
            str(runs_dir),
            "--stream-json",
            "--no-notify",
            "--no-color",
        ],
        cwd=str(tmp_path),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready_path.is_file():
            if owner.poll() is not None:
                stdout, stderr = owner.communicate()
                raise AssertionError(
                    "owner resume exited before acquiring the blocked turn: "
                    f"code={owner.returncode} stdout={stdout!r} stderr={stderr!r}"
                )
            if time.monotonic() >= deadline:
                owner.send_signal(signal.SIGKILL)
                raise AssertionError("timed out waiting for owner resume")
            time.sleep(0.05)

        challenger = run_tdp_process(
            [
                "resume",
                "--run",
                run_id,
                "--runs-dir",
                str(runs_dir),
                "--stream-json",
                "--no-notify",
                "--no-color",
            ],
            cwd=tmp_path,
            runs_dir=runs_dir,
            script="approve_plan",
        )
        assert challenger.returncode != 0, challenger.stdout
        payload = challenger.json()
        assert payload["ok"] is False
        assert payload["error"]["code"] == "run_owned_by_live_process"
        run = store.load_run(run_id)
        assert run["phase"] != "plan_validated"
        assert run["status"] in {"running", "paused"}
    finally:
        if owner.poll() is None:
            owner.send_signal(signal.SIGINT)
            try:
                owner.wait(timeout=15)
            except subprocess.TimeoutExpired:
                owner.kill()
                owner.wait(timeout=5)
