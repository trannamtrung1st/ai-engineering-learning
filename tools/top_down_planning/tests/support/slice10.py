"""Slice 10 whole-system scenario matrix and shared assertions."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from top_down_planning.domain.session_lineage import LINEAGE_EVENT_TYPES
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.digests import compute_output_digest, compute_plan_digest

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
SLICE10_SITECUSTOMIZE = _PACKAGE_ROOT / "fixtures" / "slice10_subprocess"
SLICE10_PROCESS_PROVIDER_SITECUSTOMIZE = _PACKAGE_ROOT / "fixtures" / "slice10_process_provider"
SLICE10_FAKE_AGENT = _PACKAGE_ROOT / "fixtures" / "slice10_fake_agent.py"
TDP_SRC = _PROJECT_ROOT / "src"
CORE_TOOLS_SRC = _PROJECT_ROOT.parent / "core_tools" / "src"
TESTS_ROOT = _PACKAGE_ROOT
PACKAGE_ROOT = _PROJECT_ROOT

# Review-plan Slice 10 rows → executable test that proves the assembled-system contract.
# Shared rows are intentional. must_contain is a semantic token the test body must use.
SLICE10_SCENARIO_EVIDENCE: dict[int, tuple[str, str, str]] = {
    1: (
        "tests/integration/test_end_to_end.py",
        "test_happy_path_lifecycle_reaches_accepted",
        "PLAN_VALIDATED",
    ),
    2: (
        "tests/integration/test_end_to_end.py",
        "test_happy_path_lifecycle_reaches_accepted",
        "accepted",
    ),
    3: (
        "tests/integration/test_resume_cross_phase_e2e.py",
        "test_resume_planning_turn_limit_exhausted_increased_and_resumed",
        "resume",
    ),
    4: (
        "tests/integration/test_slice10_process_restart.py",
        "test_process_restart_between_phase_steps_reaches_accepted",
        "run_tdp_process",
    ),
    5: (
        "tests/integration/test_slice10_adversarial.py",
        "test_resume_applies_presentation_config_and_continues",
        "observability.log_level",
    ),
    6: (
        "tests/integration/test_slice10_adversarial.py",
        "test_resume_rejects_prohibited_contract_drift",
        "planning.max_depth",
    ),
    7: (
        "tests/integration/test_slice10_adversarial.py",
        "test_corrupt_persisted_state_fails_closed_through_cli",
        "corrupt_run",
    ),
    8: (
        "tests/integration/test_slice10_adversarial.py",
        "test_stale_plan_revision_is_rejected_through_agent_cli",
        "revision_conflict",
    ),
    9: (
        "tests/integration/test_slice10_adversarial.py",
        "test_lost_provider_session_is_replaced_with_complete_lineage",
        "REASON_PROVIDER_SESSION_NOT_FOUND",
    ),
    10: (
        "tests/integration/test_slice10_adversarial.py",
        "test_stalled_provider_exhausts_recovery_without_orphans",
        "REASON_PROVIDER_TURN_STALLED",
    ),
    11: (
        "tests/integration/test_slice10_process_restart.py",
        "test_cancel_process_backed_provider_leaves_no_orphan_process",
        "SIGINT",
    ),
    12: (
        "tests/integration/test_end_to_end.py",
        "test_planning_turn_limit_yields_paused_not_accepted",
        "paused",
    ),
    13: (
        "tests/integration/test_slice10_process_restart.py",
        "test_process_restart_between_phase_steps_reaches_accepted",
        "stream-json",
    ),
    14: (
        "tests/integration/test_packaging_smoke.py",
        "test_installed_wheel_smoke",
        "packaging_wheelhouse",
    ),
    15: (
        "tests/integration/test_slice10_process_restart.py",
        "test_competing_plan_apply_same_revision_exactly_one_commits",
        "revision_conflict",
    ),
    16: (
        "tests/integration/test_slice10_process_restart.py",
        "test_cancel_process_backed_provider_leaves_no_orphan_process",
        "scan_orphan_agent_pids",
    ),
    17: (
        "tests/integration/test_slice10_adversarial.py",
        "test_audit_events_and_snapshots_agree_after_full_run",
        "assert_audit_events_agree_with_snapshots",
    ),
    18: (
        "tests/integration/test_slice10_adversarial.py",
        "test_lost_provider_session_is_replaced_with_complete_lineage",
        "assert_recovery_lineage_complete",
    ),
    19: (
        "tests/integration/test_slice10_adversarial.py",
        "test_provider_secrets_are_redacted_from_console_and_transcript",
        "slice10-e2e-secret",
    ),
    20: (
        "tests/integration/test_slice10_adversarial.py",
        "test_repeated_public_commands_are_idempotent_on_terminal_run",
        "len(after_events) == len(before_events)",
    ),
}

_LIFECYCLE_EVENT_BY_STATUS = {
    "paused": "run_paused",
    "failed": "run_failed",
    "completed": "outcome_resolved",
}


def assert_audit_events_agree_with_snapshots(store: FileRunStore, run_id: str) -> None:
    """Require events.jsonl and canonical snapshots to describe the same run."""

    snapshot = store.load_canonical_snapshot(run_id)
    events = store.load_events(run_id)
    run = snapshot.run
    assert events, "canonical run must have an audit log"
    assert events[0].get("type") == "run_created"
    assert events[0].get("run_id") == run_id
    assert run["digests"]["plan"] == compute_plan_digest(snapshot.plan)
    if snapshot.production is not None and run.get("phase") not in {None, "planning", "whole_plan_review"}:
        output_digest = (run.get("digests") or {}).get("output")
        if output_digest:
            assert output_digest == compute_output_digest(snapshot.production)
    status = str(run.get("status") or "")
    expected_event = _LIFECYCLE_EVENT_BY_STATUS.get(status)
    if expected_event is not None:
        assert any(event.get("type") == expected_event for event in events), (
            f"status {status!r} requires a {expected_event} event"
        )


def assert_recovery_lineage_complete(
    store: FileRunStore,
    run_id: str,
    *,
    reason: str,
) -> None:
    """Require a started→replaced (or failed) lineage chain for one recovery."""

    events = [
        event
        for event in store.load_events(run_id)
        if str(event.get("type") or "") in LINEAGE_EVENT_TYPES
    ]
    types = [str(event.get("type") or "") for event in events]
    assert "session_replacement_started" in types
    assert "session_resume_failed" in types
    assert "session_replaced" in types or "session_replacement_failed" in types
    started = [event for event in events if event.get("type") == "session_replacement_started"]
    assert started
    assert started[-1].get("reason") == reason


def slice10_child_pythonpath(*, sitecustomize: Path | None = None) -> str:
    parts = [str(PACKAGE_ROOT), str(TDP_SRC), str(CORE_TOOLS_SRC)]
    if sitecustomize is not None:
        parts.insert(0, str(sitecustomize))
    existing = os.environ.get("PYTHONPATH", "")
    if existing:
        parts.append(existing)
    return os.pathsep.join(parts)


@dataclass(frozen=True)
class Slice10ProcessResult:
    returncode: int
    stdout: str
    stderr: str

    def json(self) -> dict[str, Any]:
        text = self.stdout.strip()
        if not text:
            raise json.JSONDecodeError("empty stdout", text, 0)
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise json.JSONDecodeError("stdout JSON must be an object", text, 0)
        return payload


def _slice10_env(
    *,
    runs_dir: Path,
    script: str | None,
    extra_env: dict[str, str] | None,
    sitecustomize: Path | None | bool,
) -> dict[str, str]:
    if sitecustomize is True:
        customize = SLICE10_SITECUSTOMIZE
    elif sitecustomize is False:
        customize = None
    elif sitecustomize is None:
        customize = SLICE10_SITECUSTOMIZE if script is not None else None
    else:
        customize = sitecustomize
    env = os.environ.copy()
    env["PYTHONPATH"] = slice10_child_pythonpath(sitecustomize=customize)
    env["TDP_SLICE10_RUNS_DIR"] = str(runs_dir)
    if script is not None:
        env["TDP_SLICE10_SCRIPT"] = script
    if extra_env:
        env.update(extra_env)
    return env


def run_tdp_process(
    argv: list[str],
    *,
    cwd: Path,
    runs_dir: Path,
    script: str | None = None,
    extra_env: dict[str, str] | None = None,
    sitecustomize: Path | None | bool = None,
    timeout: float = 30,
) -> Slice10ProcessResult:
    """Invoke the installed-module CLI in a fresh interpreter."""

    completed = subprocess.run(
        [sys.executable, "-m", "top_down_planning", *argv],
        cwd=str(cwd),
        env=_slice10_env(
            runs_dir=runs_dir,
            script=script,
            extra_env=extra_env,
            sitecustomize=sitecustomize,
        ),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return Slice10ProcessResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def start_tdp_process(
    argv: list[str],
    *,
    cwd: Path,
    runs_dir: Path,
    script: str | None = None,
    extra_env: dict[str, str] | None = None,
    sitecustomize: Path | None | bool = None,
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-m", "top_down_planning", *argv],
        cwd=str(cwd),
        env=_slice10_env(
            runs_dir=runs_dir,
            script=script,
            extra_env=extra_env,
            sitecustomize=sitecustomize,
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def scan_orphan_agent_pids_in_fresh_interpreter(run_id: str) -> list[int]:
    """Call the real orphan scanner in a process that is not pytest-patched."""

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from top_down_planning.orchestrator.agent_process_cleanup "
                "import scan_orphan_agent_pids; "
                f"print(list(scan_orphan_agent_pids({run_id!r})))"
            ),
        ],
        env={**os.environ, "PYTHONPATH": slice10_child_pythonpath()},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    payload = json.loads(completed.stdout.strip() or "[]")
    assert isinstance(payload, list)
    return [int(pid) for pid in payload]
