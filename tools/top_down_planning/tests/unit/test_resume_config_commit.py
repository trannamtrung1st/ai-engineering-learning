"""Tests for atomic resume config persistence (proposal §8.4)."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.invocation import merge_invocation_metadata
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.commit import CommitSpec
from top_down_planning.persistence.config_commit import (
    ResumeConfigCommitError,
    apply_resume_config_atomic,
    build_resume_config_commit_spec,
    validate_and_prepare_resume_config_update,
)
from top_down_planning.persistence.digests import (
    compute_config_contract_digest,
    compute_config_execution_digest,
)
from tests.helpers import create_run_kwargs, minimal_invocation, minimal_resolved_config


def _sample_plan() -> Plan:
    return Plan(
        id="plan-run-test",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Root",
                kind="aggregate",
            )
        },
    )


def _create_store_run(store: FileRunStore, *, config: dict | None = None) -> str:
    run_id = "run-20260101T001101-001101"
    config = config or minimal_resolved_config()
    store.create_run(
        run_id,
        plan=_sample_plan(),
        **create_run_kwargs(store.root, resolved_config=config),
    )
    return run_id


def _with_limit_override(config: dict, path: str, value: int) -> dict:
    updated = copy.deepcopy(config)
    parts = path.split(".")
    current = updated
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value
    return updated


def test_validate_and_prepare_resume_config_update_accepts_limit_change() -> None:
    stored = minimal_resolved_config()
    candidate = _with_limit_override(stored, "limits.planning.max_agent_turns", 80)
    stored_invocation = minimal_invocation(Path("/tmp/workspace"))
    update = validate_and_prepare_resume_config_update(
        stored_config=stored,
        candidate_config=candidate,
        stored_invocation=stored_invocation,
        candidate_invocation={"command": "resume"},
    )
    assert update.config_changes["limits.planning.max_agent_turns"] == {
        "from": 40,
        "to": 80,
    }
    assert update.config_contract_digest == compute_config_contract_digest(stored)
    assert update.config_execution_digest != compute_config_execution_digest(stored)


def test_validate_and_prepare_resume_config_update_accepts_limit_decrease() -> None:
    stored = minimal_resolved_config()
    candidate = _with_limit_override(stored, "limits.planning.max_agent_turns", 20)
    stored_invocation = minimal_invocation(Path("/tmp/workspace"))
    update = validate_and_prepare_resume_config_update(
        stored_config=stored,
        candidate_config=candidate,
        stored_invocation=stored_invocation,
        candidate_invocation={"command": "resume"},
    )
    assert update.config_changes["limits.planning.max_agent_turns"] == {
        "from": 40,
        "to": 20,
    }


def test_validate_and_prepare_resume_config_update_rejects_contract_change() -> None:
    stored = minimal_resolved_config()
    candidate = _with_limit_override(stored, "planning.max_depth", 2)
    with pytest.raises(ResumeConfigCommitError, match="contract change"):
        validate_and_prepare_resume_config_update(
            stored_config=stored,
            candidate_config=candidate,
            stored_invocation=minimal_invocation(Path("/tmp/workspace")),
            candidate_invocation={},
        )


def test_merge_invocation_metadata_preserves_unspecified_fields() -> None:
    stored = {
        "command": "run",
        "observability": {"log_level": "normal", "agent_transcript": False},
        "runs_dir": {"path": "/tmp/runs", "source": "config"},
    }
    merged = merge_invocation_metadata(
        stored,
        {"command": "resume", "observability": {"log_level": "verbose"}},
    )
    assert merged["command"] == "resume"
    assert merged["observability"]["log_level"] == "verbose"
    assert merged["observability"]["agent_transcript"] is False
    assert merged["runs_dir"]["path"] == "/tmp/runs"


def test_apply_resume_config_atomic_updates_config_invocation_and_run_digest(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_store_run(store)
    stored_config = store.load_resolved_config(run_id)
    candidate_config = _with_limit_override(stored_config, "limits.production.max_batches", 99)
    invocation = store.load_invocation(run_id)
    invocation = merge_invocation_metadata(invocation, {"command": "resume"})

    result = apply_resume_config_atomic(
        store,
        run_id,
        resolved_config=candidate_config,
        invocation=invocation,
        run_expected_revision=0,
    )

    assert result["run_revision"] == 1
    assert store.load_resolved_config(run_id) == candidate_config
    assert store.load_invocation(run_id) == invocation
    run = store.load_run(run_id)
    assert run["revision"] == 1
    assert run["digests"]["config_contract"] == compute_config_contract_digest(candidate_config)
    assert run["digests"]["config_execution"] == compute_config_execution_digest(candidate_config)
    assert run["digests"]["config_contract"] == compute_config_contract_digest(stored_config)


def test_apply_resume_config_atomic_revision_conflict(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_store_run(store)
    candidate_config = _with_limit_override(store.load_resolved_config(run_id), "limits.production.max_batches", 99)
    invocation = store.load_invocation(run_id)

    with pytest.raises(ResumeConfigCommitError, match="revision is stale"):
        apply_resume_config_atomic(
            store,
            run_id,
            resolved_config=candidate_config,
            invocation=invocation,
            run_expected_revision=1,
        )


def test_build_resume_config_commit_spec_requires_contract_unchanged() -> None:
    stored = minimal_resolved_config()
    candidate = _with_limit_override(stored, "planning.max_depth", 2)
    run = {
        "revision": 0,
        "digests": {
            "config_contract": compute_config_contract_digest(stored),
            "config_execution": compute_config_execution_digest(stored),
        },
    }
    with pytest.raises(ResumeConfigCommitError, match="config_contract"):
        build_resume_config_commit_spec(
            run=run,
            resolved_config=candidate,
            invocation={},
            run_expected_revision=0,
        )


def test_config_commit_is_atomic_with_run_revision_cas(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_store_run(store)
    run = store.load_run(run_id)
    candidate_config = _with_limit_override(store.load_resolved_config(run_id), "limits.provider.max_retries_per_call", 5)
    invocation = store.load_invocation(run_id)
    spec = build_resume_config_commit_spec(
        run=run,
        resolved_config=candidate_config,
        invocation=invocation,
        run_expected_revision=0,
    )
    assert spec.resolved_config == candidate_config
    assert spec.invocation == invocation
    store.commit(run_id, spec)
    assert store.load_resolved_config(run_id) == candidate_config
    assert store.load_run(run_id)["revision"] == 1


def test_prepare_update_syncs_observability_into_invocation(tmp_path: Path) -> None:
    stored = minimal_resolved_config()
    candidate = copy.deepcopy(stored)
    candidate["observability"] = dict(stored["observability"])
    candidate["observability"]["log_level"] = "verbose"
    stored_invocation = minimal_invocation(tmp_path)
    update = validate_and_prepare_resume_config_update(
        stored_config=stored,
        candidate_config=candidate,
        stored_invocation=stored_invocation,
        candidate_invocation={"command": "resume"},
    )
    assert update.invocation["observability"]["log_level"] == "verbose"
    assert update.comparison.execution_digest_changed is False
