"""Persistence and attempt/session restart bookkeeping."""

from __future__ import annotations

from pathlib import Path

from todos_tool.models import Phase, Transition
from todos_tool.persistence import (
    load_state,
    new_run_state,
    record_transition,
    save_state,
)


def test_atomic_state_roundtrip(tmp_path: Path) -> None:
    runs = tmp_path / "runs" / "TASK-001"
    state = new_run_state("TASK-001", "abc123")
    state.logical_attempt = 1
    state.phase = Phase.WORK
    record_transition(runs, state, Transition.ATTEMPT_STARTED)
    loaded = load_state(runs)
    assert loaded is not None
    assert loaded.item_id == "TASK-001"
    assert loaded.logical_attempt == 1
    assert loaded.last_transition == Transition.ATTEMPT_STARTED
    assert loaded.history


def test_review_proposed_commit_message_roundtrip(tmp_path: Path) -> None:
    runs = tmp_path / "runs" / "TASK-001"
    state = new_run_state("TASK-001", "abc123")
    state.review.decision = "pass"
    state.review.summary = "ok"
    state.review.proposed_commit_message = "agent: feat: add greeting helper"
    record_transition(runs, state, Transition.REVIEW_PASSED)
    loaded = load_state(runs)
    assert loaded is not None
    assert loaded.review.proposed_commit_message == "agent: feat: add greeting helper"


def test_session_restart_does_not_bump_attempt(tmp_path: Path) -> None:
    runs = tmp_path / "runs" / "TASK-001"
    state = new_run_state("TASK-001", "abc")
    state.logical_attempt = 2
    state.session_restart_count = 0
    record_transition(runs, state, Transition.WORK_SESSION_STARTED)
    state.session_restart_count += 1
    record_transition(runs, state, Transition.WORK_SESSION_RESTARTED)
    loaded = load_state(runs)
    assert loaded is not None
    assert loaded.logical_attempt == 2
    assert loaded.session_restart_count == 1
