"""Slice 10 process-boundary proofs: restart, cancel, competing writers."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.capabilities import CAPABILITY_TOKEN_FILE_ENV_VAR
from tests.integration.e2e_helpers import write_e2e_config
from tests.helpers import (
    grant_capability,
    only_run_id,
    write_agent_request_file,
    write_capability_token_file,
    write_config,
)
from tests.support.run_builders import _create_planning_run
from tests.support.slice10 import (
    SLICE10_FAKE_AGENT,
    SLICE10_PROCESS_PROVIDER_SITECUSTOMIZE,
    SLICE10_SITECUSTOMIZE,
    assert_audit_events_agree_with_snapshots,
    run_tdp_process,
    scan_orphan_agent_pids_in_fresh_interpreter,
    slice10_child_pythonpath,
    start_tdp_process,
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
    env["PYTHONPATH"] = slice10_child_pythonpath(sitecustomize=SLICE10_SITECUSTOMIZE)
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
    env["PYTHONPATH"] = slice10_child_pythonpath(sitecustomize=SLICE10_SITECUSTOMIZE)
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


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _wait_for_file(path: Path, *, timeout: float = 15) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file() and path.stat().st_size:
            return path.read_text(encoding="utf-8").strip()
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {path}")


def _live_pids_tagged_with_run(run_id: str) -> list[int]:
    from top_down_planning.cli.common import RUN_ID_ENV_VAR
    from top_down_planning.orchestrator.agent_process_cleanup import default_read_pid_environ

    listed = subprocess.run(
        ["ps", "-ax", "-o", "pid="],
        capture_output=True,
        text=True,
        check=False,
    )
    tagged: list[int] = []
    for line in listed.stdout.splitlines():
        try:
            pid = int(line.strip())
        except ValueError:
            continue
        if default_read_pid_environ(pid).get(RUN_ID_ENV_VAR) == run_id:
            tagged.append(pid)
    return tagged


def _parse_process_json(stdout: str) -> dict:
    import json

    text = stdout.strip()
    payload = json.loads(text)
    assert isinstance(payload, dict)
    return payload


@pytest.mark.integration
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process-boundary contract")
def test_competing_plan_apply_same_revision_exactly_one_commits(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    store = FileRunStore(runs_dir)
    run_id = _create_planning_run(store, "run-20260101T101501-101501")
    base_revision = int(store.load_plan(run_id)["revision"])
    token_path = write_capability_token_file(
        store,
        run_id,
        grant_capability(store, run_id, role="planner", phase=PLANNING),
    )
    go_path = tmp_path / "cas.go"
    workers = []
    for slot, title in (("a", "From-A"), ("b", "From-B")):
        request = write_agent_request_file(
            store,
            run_id,
            f"apply-{slot}.json",
            {
                "base_revision": base_revision,
                "operations": [
                    {
                        "op": "update_item",
                        "item_id": "item-root",
                        "patch": {"title": title},
                    }
                ],
            },
        )
        workers.append(
            start_tdp_process(
                [
                    "agent",
                    "plan",
                    "apply",
                    "--run",
                    run_id,
                    "--runs-dir",
                    str(runs_dir),
                    "--request",
                    str(request),
                ],
                cwd=tmp_path,
                runs_dir=runs_dir,
                sitecustomize=True,
                extra_env={
                    CAPABILITY_TOKEN_FILE_ENV_VAR: str(token_path),
                    "TDP_SLICE10_CAS_READY": str(tmp_path / f"cas-ready-{slot}"),
                    "TDP_SLICE10_CAS_GO": str(go_path),
                },
            )
        )
    try:
        _wait_for_file(tmp_path / "cas-ready-a")
        _wait_for_file(tmp_path / "cas-ready-b")
        go_path.write_text("go\n", encoding="utf-8")
        results = []
        for worker in workers:
            stdout, stderr = worker.communicate(timeout=20)
            results.append((worker.returncode, stdout, stderr))
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
                worker.wait(timeout=5)

    payloads = []
    for returncode, stdout, stderr in results:
        payload = _parse_process_json(stdout)
        payloads.append((returncode, payload, stderr))
    winners = [payload for returncode, payload, _ in payloads if returncode == 0]
    losers = [payload for returncode, payload, _ in payloads if returncode != 0]
    assert len(winners) == 1, payloads
    assert len(losers) == 1, payloads
    assert winners[0]["ok"] is True
    assert losers[0]["ok"] is False
    assert losers[0]["error"]["code"] == "revision_conflict", losers[0]
    plan = store.load_plan(run_id)
    assert int(plan["revision"]) == base_revision + 1
    items = plan["items"]
    if isinstance(items, dict):
        title = items["item-root"]["title"]
    else:
        title = next(item["title"] for item in items if item["id"] == "item-root")
    assert title in {"From-A", "From-B"}
    applied = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == "plan_applied"
    ]
    assert len(applied) == 1
    assert int(applied[0]["revision"]) == base_revision + 1


@pytest.mark.integration
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process-backed provider contract")
def test_cancel_process_backed_provider_leaves_no_orphan_process(tmp_path: Path) -> None:
    agent = tmp_path / "agent"
    agent.write_text(SLICE10_FAKE_AGENT.read_text(encoding="utf-8"), encoding="utf-8")
    agent.chmod(0o755)
    ready_path = tmp_path / "agent.pid"
    pgid_path = tmp_path / "agent.pgid"
    config_path = write_config(
        tmp_path / "run.yaml",
        f"""
run:
  output_goal: Deliver the sample output for process-backed cancel.
provider:
  name: cursor
  binary: {agent}
  skip_probe: true
""",
    )
    runs_dir = tmp_path / "runs"
    child = start_tdp_process(
        [
            "run",
            "--config",
            str(config_path),
            "--runs-dir",
            str(runs_dir),
            "--stream-json",
            "--no-notify",
            "--no-color",
        ],
        cwd=tmp_path,
        runs_dir=runs_dir,
        sitecustomize=SLICE10_PROCESS_PROVIDER_SITECUSTOMIZE,
        extra_env={
            "TDP_SLICE10_PROCESS_PROVIDER": "1",
            "TDP_SLICE10_AGENT_READY": str(ready_path),
            "TDP_SLICE10_AGENT_PGID": str(pgid_path),
        },
    )
    try:
        try:
            agent_pid = int(_wait_for_file(ready_path))
        except AssertionError:
            stdout, stderr = child.communicate(timeout=5)
            raise AssertionError(
                f"fake agent never started\nstdout={stdout}\nstderr={stderr}"
            ) from None
        agent_pgid = int(_wait_for_file(pgid_path))
        assert _pid_alive(agent_pid)
        deadline = time.monotonic() + 10
        run_id = None
        store = FileRunStore(runs_dir)
        while time.monotonic() < deadline:
            try:
                run_id = only_run_id(store)
                break
            except AssertionError:
                time.sleep(0.05)
        assert run_id is not None
        tagged_while_live = _live_pids_tagged_with_run(run_id)
        assert agent_pid in tagged_while_live
        child.send_signal(signal.SIGINT)
        child.wait(timeout=15)
        assert child.returncode == 130
        gone_deadline = time.monotonic() + 2
        while time.monotonic() < gone_deadline and (
            _pid_alive(child.pid) or _pid_alive(agent_pid)
        ):
            time.sleep(0.05)
        assert not _pid_alive(child.pid)
        assert not _pid_alive(agent_pid)
        members = subprocess.run(
            ["ps", "-ax", "-o", "pid=,pgid="],
            capture_output=True,
            text=True,
            check=False,
        )
        leftover_group = []
        for line in members.stdout.splitlines():
            parts = line.split()
            if len(parts) != 2:
                continue
            pid_text, pgid_text = parts
            try:
                pid = int(pid_text)
                pgid = int(pgid_text)
            except ValueError:
                continue
            if pgid == agent_pgid and pid != agent_pgid:
                leftover_group.append(pid)
            elif pgid == agent_pgid and _pid_alive(pid):
                leftover_group.append(pid)
        assert leftover_group == []
        assert _live_pids_tagged_with_run(run_id) == []
        assert scan_orphan_agent_pids_in_fresh_interpreter(run_id) == []
        run = store.load_run(run_id)
        assert run["status"] == "paused"
        assert run["stop"]["code"] == "user_cancelled"
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
