"""Top-level CLI cancellation across a real OS process boundary."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from top_down_planning.orchestrator.phases import WHOLE_OUTPUT_REVIEW
from top_down_planning.persistence import FileRunStore
from tests.helpers import apply_production, only_run_id, write_config
from tests.support.whole_output_sigint_resume import seed_whole_output_revision_in_progress_run

_SITCUSTOMIZE_DIR = (
    Path(__file__).resolve().parents[1] / "fixtures" / "cli_os_interrupt"
)
_WOR_SITCUSTOMIZE_DIR = _SITCUSTOMIZE_DIR
_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def _subprocess_env(
    *,
    sitecustomize_dir: Path,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    env = os.environ.copy()
    parts = [str(sitecustomize_dir), str(_PACKAGE_ROOT)]
    existing = env.get("PYTHONPATH", "")
    if existing:
        parts.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    if extra:
        env.update(extra)
    return env


def _run_tdp_resume_sigint(
    *,
    runs_dir: Path,
    run_id: str,
    ready_path: Path,
    sitecustomize_dir: Path,
    wor_script: str,
    extra_env: dict[str, str] | None = None,
) -> subprocess.Popen[str]:
    tdp = shutil.which("tdp")
    assert tdp, "expected the tdp console script on PATH"
    env = _subprocess_env(
        sitecustomize_dir=sitecustomize_dir,
        extra={
            "TDP_STUB_TURN_READY_PATH": str(ready_path),
            "TDP_STUB_TURN_BLOCK_SECONDS": "30",
            "TDP_WOR_RUNS_DIR": str(runs_dir),
            "TDP_WOR_SCRIPT": wor_script,
            **(extra_env or {}),
        },
    )
    return subprocess.Popen(
        [
            tdp,
            "resume",
            "--run",
            run_id,
            "--runs-dir",
            str(runs_dir),
            "--no-notify",
            "--no-color",
        ],
        cwd=str(runs_dir.parent),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )


def _wait_ready_and_sigint(child: subprocess.Popen[str], ready_path: Path) -> None:
    deadline = time.monotonic() + 15
    while not ready_path.is_file():
        if child.poll() is not None:
            stdout, stderr = child.communicate()
            raise AssertionError(
                "tdp exited before entering the blocked provider turn: "
                f"code={child.returncode} stdout={stdout!r} stderr={stderr!r}"
            )
        if time.monotonic() >= deadline:
            child.send_signal(signal.SIGKILL)
            stdout, stderr = child.communicate()
            raise AssertionError(
                "timed out waiting for blocked provider turn: "
                f"stdout={stdout!r} stderr={stderr!r}"
            )
        time.sleep(0.05)
    child.send_signal(signal.SIGINT)
    child.wait(timeout=15)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX SIGINT CLI contract")
def test_tdp_run_sigint_exits_130_and_pauses_run_as_user_cancelled(
    tmp_path: Path,
) -> None:
    config_path = write_config(
        tmp_path / "run.yaml",
        """
run:
  output_goal: Deliver the sample output.
provider:
  name: stub
""",
    )
    runs_dir = tmp_path / "runs"
    ready_path = tmp_path / "stub-turn-ready"
    env = _subprocess_env(sitecustomize_dir=_SITCUSTOMIZE_DIR)
    env["TDP_STUB_TURN_READY_PATH"] = str(ready_path)
    env["TDP_STUB_TURN_BLOCK_SECONDS"] = "30"

    tdp = shutil.which("tdp")
    assert tdp, "expected the tdp console script on PATH"
    child = subprocess.Popen(
        [
            tdp,
            "run",
            "--config",
            str(config_path),
            "--runs-dir",
            str(runs_dir),
            "--no-notify",
            "--no-color",
            "--stream-json",
        ],
        cwd=str(tmp_path),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        _wait_ready_and_sigint(child, ready_path)
    except Exception:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        raise

    assert child.returncode == 130, (
        f"expected SIGINT exit 130, got {child.returncode}; "
        f"stdout={child.stdout.read() if child.stdout else ''} "
        f"stderr={child.stderr.read() if child.stderr else ''}"
    )

    store = FileRunStore(runs_dir)
    run_id = only_run_id(store)
    run = store.load_run(run_id)
    assert run["status"] == "paused"
    assert run["stop"]["code"] == "user_cancelled"
    events = store.load_events(run_id)
    assert any(event.get("type") == "run_paused" for event in events)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX SIGINT CLI contract")
def test_tdp_resume_sigint_whole_output_revision_in_progress_then_resumes(
    tmp_path: Path,
) -> None:
    """SIGINT during pending owner revision must not corrupt mandatory review resume."""

    runs_dir = tmp_path / "runs"
    artifacts_dir = runs_dir / "artifacts"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "leaf.txt").write_text("leaf artifact", encoding="utf-8")

    store = FileRunStore(runs_dir)
    run_id = "run-20260824T090000-a1b2c3"
    loop_id = seed_whole_output_revision_in_progress_run(
        store,
        run_id,
        revision_cycles=1,
    )
    revision_cycles_before = int(store.load_review(run_id, loop_id)["revision_cycles"])

    ready_path = tmp_path / "owner-revision-ready"
    child = _run_tdp_resume_sigint(
        runs_dir=runs_dir,
        run_id=run_id,
        ready_path=ready_path,
        sitecustomize_dir=_WOR_SITCUSTOMIZE_DIR,
        wor_script="block_owner_revision",
    )
    try:
        _wait_ready_and_sigint(child, ready_path)
    except Exception:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        raise

    assert child.returncode == 130
    run = store.load_run(run_id)
    assert run["status"] == "paused"
    assert run["stop"]["code"] == "user_cancelled"
    review_after_sigint = store.load_review(run_id, loop_id)
    assert review_after_sigint["lifecycle_status"] == "revision_in_progress"
    assert int(review_after_sigint["revision_cycles"]) == revision_cycles_before
    assert (review_after_sigint.get("verification_result") or {}).get("decision") == (
        "needs_revision"
    )

    owner_count_path = tmp_path / "owner-turn-count"
    completed = subprocess.run(
        [
            shutil.which("tdp"),
            "resume",
            "--run",
            run_id,
            "--runs-dir",
            str(runs_dir),
            "--no-notify",
            "--no-color",
        ],
        cwd=str(runs_dir.parent),
        env=_subprocess_env(
            sitecustomize_dir=_WOR_SITCUSTOMIZE_DIR,
            extra={
                "TDP_WOR_RUNS_DIR": str(runs_dir),
                "TDP_WOR_SCRIPT": "owner_then_verify",
                "TDP_WOR_OWNER_TURN_COUNT_PATH": str(owner_count_path),
            },
        ),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    combined = f"{completed.stdout}\n{completed.stderr}"
    assert "orchestrator_invariant_failure" not in combined
    assert "revision_in_progress" not in combined or "findings_open" not in combined

    run = store.load_run(run_id)
    assert run["status"] != "failed"
    assert (run.get("stop") or {}).get("code") != "orchestrator_invariant_failure"
    review = store.load_review(run_id, loop_id)
    assert int(review["revision_cycles"]) == revision_cycles_before
    assert owner_count_path.read_text(encoding="utf-8").strip() == "1"
    assert review.get("verification_result")
    assert review.get("scope_review_result")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX SIGINT CLI contract")
def test_tdp_resume_whole_output_artifact_advanced_skips_owner_rerun(
    tmp_path: Path,
) -> None:
    """When output revision advanced before verification_pending, resume must recheck only."""

    runs_dir = tmp_path / "runs"
    artifacts_dir = runs_dir / "artifacts"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "leaf.txt").write_text("leaf artifact", encoding="utf-8")

    store = FileRunStore(runs_dir)
    run_id = "run-20260824T090100-b2c3d4"
    loop_id = seed_whole_output_revision_in_progress_run(
        store,
        run_id,
        output_revision=1,
        target_revision=1,
        revision_cycles=1,
    )
    apply_production(
        store,
        run_id,
        {
            "production_revision": 2,
            "evidence_revision": True,
            "plan_items": ["item-leaf"],
            "dispositions": {
                "item-leaf": {
                    "disposition": "completed",
                    "evidence": "Owner already revised.",
                }
            },
            "outputs": [
                {
                    "id": "output-leaf",
                    "type": "artifact",
                    "ref": "artifacts/leaf.txt",
                }
            ],
            "contributions": [
                {
                    "item_id": "item-leaf",
                    "output_refs": ["output-leaf"],
                    "summary": "Revised before interrupt.",
                }
            ],
            "summary": "Artifact advanced before verification_pending.",
        },
        handler="apply",
        phase=WHOLE_OUTPUT_REVIEW,
    )()
    apply_production(
        store,
        run_id,
        {
            "goal_assessment": "Output goal is fully met after owner revision.",
        },
        handler="submit_completion",
        phase=WHOLE_OUTPUT_REVIEW,
    )()
    assert int(store.load_production(run_id)["output_revision"]) == 2

    owner_count_path = tmp_path / "owner-turn-count-advanced"
    completed = subprocess.run(
        [
            shutil.which("tdp"),
            "resume",
            "--run",
            run_id,
            "--runs-dir",
            str(runs_dir),
            "--no-notify",
            "--no-color",
        ],
        cwd=str(runs_dir.parent),
        env=_subprocess_env(
            sitecustomize_dir=_WOR_SITCUSTOMIZE_DIR,
            extra={
                "TDP_WOR_RUNS_DIR": str(runs_dir),
                "TDP_WOR_SCRIPT": "artifact_advanced_verify_only",
                "TDP_WOR_OWNER_TURN_COUNT_PATH": str(owner_count_path),
            },
        ),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    combined = f"{completed.stdout}\n{completed.stderr}"
    assert "orchestrator_invariant_failure" not in combined
    assert completed.returncode in {0, 1}

    assert not owner_count_path.is_file()
    review = store.load_review(run_id, loop_id)
    assert review["lifecycle_status"] == "verification_pending"
    assert review.get("verification_result") is None
    assert int(review["target_revision"]) == 2
    run = store.load_run(run_id)
    assert (run.get("stop") or {}).get("code") != "orchestrator_invariant_failure"
