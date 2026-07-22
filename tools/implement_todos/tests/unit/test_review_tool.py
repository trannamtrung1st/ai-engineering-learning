"""Tests for the session-scoped review submission CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from todos_tool.errors import ReviewError
from todos_tool.review_tool import (
    ReviewToolError,
    build_session_env,
    load_review_submission,
    reset_review_submission,
    review_submission_path,
    review_tool_argv,
    resolve_review_tool_command,
    submit_review_decision,
)


VALID_SUBMISSION = {
    "schema_version": 1,
    "item_id": "TASK-001",
    "logical_attempt": 1,
    "decision": "pass",
    "summary": "Looks good",
    "acceptance_criteria": [
        {"criterion": "Crit A", "passed": True, "evidence": "ok"},
    ],
    "validation": [],
    "instruction_compliance": {"passed": True, "violations": []},
    "issues": [],
    "proposed_commit_message": "agent: feat: ship it",
    "recommended_next_action": "mark_done",
}


@pytest.fixture
def submission_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    submission = tmp_path / "review-submission-1.json"
    env = build_session_env(
        submission_path=submission,
        item_id="TASK-001",
        logical_attempt=1,
        review_tool_command=f"{sys.executable} -m todos_tool.review_tool",
    )
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return submission


def test_resolve_review_tool_command_prefers_explicit() -> None:
    assert resolve_review_tool_command(explicit="custom-review-tool") == "custom-review-tool"


def test_build_session_env_includes_scope() -> None:
    path = Path("/tmp/review-submission-1.json")
    env = build_session_env(
        submission_path=path,
        item_id="TASK-001",
        logical_attempt=2,
        review_tool_command="todos-review-tool",
    )
    assert env["TODOS_TOOL_REVIEW_SUBMISSION_FILE"] == str(path.resolve())
    assert env["TODOS_TOOL_ITEM_ID"] == "TASK-001"
    assert env["TODOS_TOOL_LOGICAL_ATTEMPT"] == "2"
    assert env["TODOS_TOOL_REVIEW_TOOL_COMMAND"] == "todos-review-tool"


def test_review_tool_argv_splits_command() -> None:
    assert review_tool_argv("python -m todos_tool.review_tool", "status") == [
        "python",
        "-m",
        "todos_tool.review_tool",
        "status",
    ]


def test_submit_and_load_round_trip(submission_env: Path) -> None:
    decision = submit_review_decision(json.dumps(VALID_SUBMISSION))
    assert decision.decision == "pass"
    loaded = load_review_submission(submission_env)
    assert loaded.item_id == "TASK-001"
    assert loaded.summary == "Looks good"


def test_submit_rejects_duplicate(submission_env: Path) -> None:
    submit_review_decision(json.dumps(VALID_SUBMISSION))
    with pytest.raises(ReviewToolError, match="already exists"):
        submit_review_decision(json.dumps(VALID_SUBMISSION))


def test_submit_rejects_identity_mismatch(submission_env: Path) -> None:
    payload = dict(VALID_SUBMISSION)
    payload["logical_attempt"] = 2
    with pytest.raises(ReviewToolError, match="logical_attempt mismatch"):
        submit_review_decision(json.dumps(payload))


def test_load_missing_submission_raises(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(ReviewError, match="not found"):
        load_review_submission(missing)


def test_reset_clears_submission(submission_env: Path) -> None:
    submit_review_decision(json.dumps(VALID_SUBMISSION))
    reset_review_submission(submission_env)
    assert not submission_env.is_file()


def test_review_submission_path_uses_session_number(tmp_path: Path) -> None:
    assert review_submission_path(tmp_path, 3) == tmp_path / "review-submission-3.json"


def test_cli_submit_status_reset(submission_env: Path) -> None:
    env = os.environ.copy()
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "todos_tool.review_tool",
            "submit",
            "--json",
            json.dumps(VALID_SUBMISSION),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Submitted review decision: pass" in proc.stdout

    status = subprocess.run(
        [sys.executable, "-m", "todos_tool.review_tool", "status"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(status.stdout)
    assert payload["submitted"] is True
    assert payload["decision"] == "pass"

    reset = subprocess.run(
        [sys.executable, "-m", "todos_tool.review_tool", "reset"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "reset" in reset.stdout.lower()
    assert not submission_env.is_file()
