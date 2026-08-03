"""Lifecycle invariant tests for run records (proposal §4–§5, item 1.1.1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.run_lifecycle import (
    RunLifecycleError,
    StopRecord,
    validate_run_lifecycle_invariants,
)
from top_down_planning.persistence import (
    CURRENT_RUN_SCHEMA_VERSION,
    FileRunStore,
    PersistenceError,
    UnsupportedRunSchemaVersionError,
    validate_run_schema_version,
)
from top_down_planning.persistence.commit import CommitSpec
from tests.helpers import minimal_invocation

_EMPTY_SNAPSHOT_BINDING = {
    "resource_digests": {},
    "skill_digests": {},
    "guidance_digests": [],
}


def _sample_plan() -> Plan:
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        kind="aggregate",
    )
    return Plan(
        id="plan-001",
        revision=0,
        output_goal="Deliver the output.",
        items={"item-root": root},
    )


def _create_run(store: FileRunStore, run_id: str = "run-20260101T000001-000001") -> dict:
    return store.create_run(
        run_id,
        plan=_sample_plan(),
        resolved_config={"limits": {}},
        input_digest="input-a",
        output_goal_digest="goal-b",
        context_spec_digest="0" * 64,
        context_snapshot_digest="1" * 64,
        context_snapshot_binding={**_EMPTY_SNAPSHOT_BINDING},
        workspace=str(store.root),
        invocation=minimal_invocation(store.root),
    )


def _operational_stop(**overrides: object) -> dict:
    base = StopRecord(
        code="limit_exhausted",
        category="operational",
        phase="planning",
        message="planning turn limit exhausted",
        details={"limit": "limits.planning.max_agent_turns", "consumed": 5, "configured": 5},
    ).to_dict()
    base.update(overrides)
    return base


def _invariant_stop(**overrides: object) -> dict:
    base = StopRecord(
        code="state_integrity_failure",
        category="invariant",
        phase="production",
        message="canonical production state violates required invariants",
    ).to_dict()
    base.update(overrides)
    return base


def test_new_run_has_lifecycle_fields(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run = _create_run(store)
    assert run["status"] == "running"
    assert run["outcome"] is None
    assert run["stop"] is None
    assert run["phase_action_id"] is None
    assert run["schema_version"] == CURRENT_RUN_SCHEMA_VERSION


def test_running_rejects_active_stop() -> None:
    with pytest.raises(RunLifecycleError, match="stop null"):
        validate_run_lifecycle_invariants(
            {
                "status": "running",
                "outcome": None,
                "stop": _operational_stop(),
                "phase_action_id": None,
            }
        )


def test_paused_requires_operational_stop() -> None:
    with pytest.raises(RunLifecycleError, match="structured stop"):
        validate_run_lifecycle_invariants(
            {
                "status": "paused",
                "outcome": None,
                "stop": None,
                "phase_action_id": None,
            }
        )

    validate_run_lifecycle_invariants(
        {
            "status": "paused",
            "outcome": None,
            "stop": _operational_stop(),
            "phase_action_id": "action-1",
        }
    )


def test_paused_rejects_invariant_stop_category() -> None:
    with pytest.raises(RunLifecycleError, match="operational"):
        validate_run_lifecycle_invariants(
            {
                "status": "paused",
                "outcome": None,
                "stop": _invariant_stop(),
                "phase_action_id": None,
            }
        )


def test_completed_requires_outcome_and_no_stop() -> None:
    with pytest.raises(RunLifecycleError, match="non-null outcome"):
        validate_run_lifecycle_invariants(
            {
                "status": "completed",
                "outcome": None,
                "stop": None,
                "phase_action_id": None,
            }
        )

    with pytest.raises(RunLifecycleError, match="stop null"):
        validate_run_lifecycle_invariants(
            {
                "status": "completed",
                "outcome": "accepted",
                "stop": _operational_stop(),
                "phase_action_id": None,
            }
        )

    validate_run_lifecycle_invariants(
        {
            "status": "completed",
            "outcome": "accepted",
            "stop": None,
            "phase_action_id": None,
        }
    )


def test_failed_requires_invariant_stop() -> None:
    with pytest.raises(RunLifecycleError, match="structured stop"):
        validate_run_lifecycle_invariants(
            {
                "status": "failed",
                "outcome": None,
                "stop": None,
                "phase_action_id": None,
            }
        )

    with pytest.raises(RunLifecycleError, match="invariant"):
        validate_run_lifecycle_invariants(
            {
                "status": "failed",
                "outcome": None,
                "stop": _operational_stop(),
                "phase_action_id": None,
            }
        )

    validate_run_lifecycle_invariants(
        {
            "status": "failed",
            "outcome": None,
            "stop": _invariant_stop(),
            "phase_action_id": None,
        }
    )


def test_load_rejects_missing_stop_field(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run(store)
    run_path = tmp_path / "run-20260101T000001-000001" / "run.json"
    payload = json.loads(run_path.read_text(encoding="utf-8"))
    del payload["stop"]
    run_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PersistenceError, match="run.stop is required"):
        store.load_run("run-20260101T000001-000001")


def test_commit_persists_phase_action_id(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run = _create_run(store)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["phase_action_id"] = "action-42"
    store.commit(
        run["id"],
        CommitSpec(
            run=run,
            run_expected_revision=expected_revision,
            events=[{"type": "phase_action_assigned", "phase_action_id": "action-42"}],
        ),
    )
    loaded = store.load_run(run["id"])
    assert loaded["phase_action_id"] == "action-42"


def test_schema_version_gate_accepts_current_version() -> None:
    assert validate_run_schema_version({"schema_version": CURRENT_RUN_SCHEMA_VERSION}) == (
        CURRENT_RUN_SCHEMA_VERSION
    )


def test_schema_version_gate_rejects_previous_version() -> None:
    with pytest.raises(UnsupportedRunSchemaVersionError):
        validate_run_schema_version({"schema_version": 2})
