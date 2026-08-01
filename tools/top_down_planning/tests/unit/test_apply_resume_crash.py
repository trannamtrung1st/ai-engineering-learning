"""Crash idempotency tests for resume apply (§21 tests 35–36)."""

from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path

import pytest

from top_down_planning.orchestrator.apply_resume import ApplyResumeError, apply_resume_plan_atomically
from top_down_planning.orchestrator.prepare_resume import prepare_resume
from top_down_planning.orchestrator import RunEngine
from top_down_planning.persistence import FileRunStore
from core_tools.provider.stub import StubProvider
from tests.helpers import script_planning_candidate_ready
from tests.unit.test_apply_resume import _paused_planning_run


def test_crash_before_resume_applied_leaves_run_unchanged(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _paused_planning_run(store)
    stored = store.load_resolved_config(run_id)
    candidate = copy.deepcopy(stored)
    candidate["limits"] = copy.deepcopy(stored["limits"])
    candidate["limits"]["planning"] = copy.deepcopy(stored["limits"]["planning"])
    candidate["limits"]["planning"]["max_agent_turns"] = 99
    plan = prepare_resume(store, run_id, candidate)
    stale_plan = replace(plan, expected_run_revision=plan.expected_run_revision - 1)

    with pytest.raises(ApplyResumeError):
        apply_resume_plan_atomically(
            store,
            stale_plan,
            resolved_config=candidate,
            invocation=store.load_invocation(run_id),
        )

    assert store.load_run(run_id)["status"] == "paused"
    assert store.load_resolved_config(run_id) == stored
    assert not any(
        event.get("type") == "resume_applied" for event in store.load_events(run_id)
    )


def test_crash_after_resume_applied_allows_continue_run(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _paused_planning_run(store)
    stored = store.load_resolved_config(run_id)
    candidate = copy.deepcopy(stored)
    candidate["limits"] = copy.deepcopy(stored["limits"])
    candidate["limits"]["planning"] = copy.deepcopy(stored["limits"]["planning"])
    candidate["limits"]["planning"]["max_agent_turns"] = 99
    plan = prepare_resume(store, run_id, candidate)
    apply_resume_plan_atomically(
        store,
        plan,
        resolved_config=candidate,
        invocation=store.load_invocation(run_id),
    )

    run = store.load_run(run_id)
    assert run["status"] == "running"
    assert run["stop"] is None

    provider = StubProvider()
    script_planning_candidate_ready(provider)
    engine = RunEngine(
        store,
        create_provider=lambda _config, _workspace: provider,
    )
    result = engine.continue_run(run_id, single_step=True)
    assert result.ok is True
    assert result.status == "running"
    assert store.load_run(run_id)["status"] == "running"
