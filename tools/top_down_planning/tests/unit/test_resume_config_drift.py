"""Tests for explicit resume config drift policy (--allow-config-drift)."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from core_tools.config import apply_cli_overrides

from top_down_planning.config import resolve_config
from top_down_planning.config.defaults import ALLOWED_OVERRIDE_PATHS
from top_down_planning.config.resume_policy import (
    apply_resume_config_drift_policy,
    has_mandatory_whole_plan_approval,
)
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator.phases import PLANNING, PRODUCTION
from top_down_planning.orchestrator.prepare_resume import (
    PrepareResumeBlockedError,
    prepare_resume,
)
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.config_commit import (
    ResumeConfigCommitError,
    validate_and_prepare_resume_config_update,
)
from top_down_planning.persistence.digests import compute_config_contract_digest
from tests.helpers import (
    create_run_kwargs,
    minimal_resolved_config,
    whole_plan_approval_record,
    write_config,
)


def _candidate_with_overrides(
    stored: dict,
    overrides: list[str],
) -> dict:
    return apply_cli_overrides(
        copy.deepcopy(stored),
        overrides,
        allowed_paths=ALLOWED_OVERRIDE_PATHS,
    )


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


def _create_planning_run(store: FileRunStore, *, run_id: str = "run-20260101T003001-003001") -> str:
    config = minimal_resolved_config()
    store.create_run(
        run_id,
        plan=_sample_plan(),
        phase=PLANNING,
        **create_run_kwargs(store.root, resolved_config=config),
    )
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["status"] = "paused"
    run["stop"] = {
        "code": "user_cancelled",
        "category": "operational",
        "phase": PLANNING,
        "message": "cancelled by user",
    }
    run["revision"] = expected_revision + 1
    store.save_run(run_id, run, expected_revision)
    return run_id


def _create_production_run_with_approval(store: FileRunStore) -> str:
    run_id = "run-20260101T003101-003101"
    config = minimal_resolved_config()
    store.create_run(
        run_id,
        plan=_sample_plan(),
        phase=PRODUCTION,
        **create_run_kwargs(store.root, resolved_config=config),
    )
    store.save_review(run_id, whole_plan_approval_record(store, run_id))
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["status"] = "paused"
    run["stop"] = {
        "code": "user_cancelled",
        "category": "operational",
        "phase": PRODUCTION,
        "message": "cancelled by user",
    }
    run["revision"] = expected_revision + 1
    store.save_run(run_id, run, expected_revision)
    return run_id


def test_drift_policy_strict_default_rejects_contract_change() -> None:
    stored = minimal_resolved_config()
    candidate = _candidate_with_overrides(stored, ["planning.max_depth=2"])
    result = apply_resume_config_drift_policy(
        stored,
        candidate,
        allow_config_drift=False,
        has_whole_plan_approval=False,
    )
    assert not result.ok
    assert any("contract change" in error for error in result.errors)


def test_drift_policy_pre_approval_applies_contract_change() -> None:
    stored = minimal_resolved_config()
    candidate = _candidate_with_overrides(stored, ["planning.max_depth=2"])
    result = apply_resume_config_drift_policy(
        stored,
        candidate,
        allow_config_drift=True,
        has_whole_plan_approval=False,
    )
    assert result.ok
    assert result.effective_config["planning"]["max_depth"] == 2
    assert "planning.max_depth" in result.applied_changes
    assert result.warnings


def test_drift_policy_pre_approval_applies_model_change() -> None:
    stored = minimal_resolved_config()
    candidate = _candidate_with_overrides(stored, ["agent_context.roles.producer.model=gpt-4"])
    result = apply_resume_config_drift_policy(
        stored,
        candidate,
        allow_config_drift=True,
        has_whole_plan_approval=False,
    )
    assert result.ok
    assert result.effective_config["agent_context"]["roles"]["producer"]["model"] == "gpt-4"
    assert "agent_context.roles.producer.model" in result.applied_changes


def test_drift_policy_post_approval_ignores_contract_and_model_changes() -> None:
    stored = minimal_resolved_config()
    candidate = _candidate_with_overrides(
        stored,
        [
            "planning.max_depth=2",
            "agent_context.roles.producer.model=gpt-4",
            "run.output_goal=Tweaked goal.",
        ],
    )
    result = apply_resume_config_drift_policy(
        stored,
        candidate,
        allow_config_drift=True,
        has_whole_plan_approval=True,
    )
    assert result.ok
    assert result.effective_config["planning"]["max_depth"] == stored["planning"]["max_depth"]
    stored_model = (stored.get("agent_context") or {}).get("roles", {}).get("producer", {}).get("model")
    effective_model = (result.effective_config.get("agent_context") or {}).get(
        "roles", {}
    ).get("producer", {}).get("model")
    assert effective_model == stored_model
    assert result.effective_config["run"]["output_goal"] == stored["run"]["output_goal"]
    assert "planning.max_depth" in result.ignored_changes
    assert "agent_context.roles.producer.model" in result.ignored_changes
    assert "run.output_goal" in result.ignored_changes
    assert any("will not take effect" in warning for warning in result.warnings)


def test_drift_policy_post_approval_still_applies_limit_change() -> None:
    stored = minimal_resolved_config()
    candidate = _candidate_with_overrides(
        stored,
        ["limits.production.max_batches=99", "planning.max_depth=2"],
    )
    result = apply_resume_config_drift_policy(
        stored,
        candidate,
        allow_config_drift=True,
        has_whole_plan_approval=True,
    )
    assert result.ok
    assert result.effective_config["limits"]["production"]["max_batches"] == 99
    assert "limits.production.max_batches" in result.applied_changes
    assert "planning.max_depth" in result.ignored_changes


def test_drift_policy_always_blocks_provider_change() -> None:
    stored = minimal_resolved_config()
    candidate = _candidate_with_overrides(stored, ["provider.name=other"])
    result = apply_resume_config_drift_policy(
        stored,
        candidate,
        allow_config_drift=True,
        has_whole_plan_approval=False,
    )
    assert not result.ok
    assert any("provider" in error.lower() or "session-strategy" in error for error in result.errors)
    assert len(result.errors) == 1
    assert result.effective_config["provider"]["name"] == stored["provider"]["name"]


def test_drift_policy_allows_limit_decrease_when_no_consumed_usage() -> None:
    stored = minimal_resolved_config()
    candidate = _candidate_with_overrides(stored, ["limits.planning.max_agent_turns=10"])
    result = apply_resume_config_drift_policy(
        stored,
        candidate,
        allow_config_drift=True,
        has_whole_plan_approval=False,
    )
    assert result.ok
    assert result.effective_config["limits"]["planning"]["max_agent_turns"] == 10


def test_drift_policy_limit_decrease_at_exhausted_single_error() -> None:
    stored = minimal_resolved_config()
    candidate = _candidate_with_overrides(stored, ["limits.planning.max_agent_turns=30"])
    result = apply_resume_config_drift_policy(
        stored,
        candidate,
        allow_config_drift=True,
        has_whole_plan_approval=False,
        consumed_limits={"limits.planning.max_agent_turns": 40},
    )
    assert not result.ok
    assert len(result.errors) == 1
    assert "strictly greater than consumed" in result.errors[0]
    assert result.effective_config["limits"]["planning"]["max_agent_turns"] == 40


def test_drift_policy_limit_decrease_below_consumed_reverts_effective() -> None:
    stored = minimal_resolved_config()
    candidate = _candidate_with_overrides(stored, ["limits.planning.max_agent_turns=10"])
    result = apply_resume_config_drift_policy(
        stored,
        candidate,
        allow_config_drift=True,
        has_whole_plan_approval=False,
        consumed_limits={"limits.planning.max_agent_turns": 15},
    )
    assert not result.ok
    assert len(result.errors) == 1
    assert "strictly greater than consumed" in result.errors[0]
    assert result.effective_config["limits"]["planning"]["max_agent_turns"] == (
        stored["limits"]["planning"]["max_agent_turns"]
    )


def test_drift_policy_pre_approval_does_not_warn_on_presentation_only() -> None:
    stored = minimal_resolved_config()
    candidate = _candidate_with_overrides(stored, ["observability.log_level=verbose"])
    result = apply_resume_config_drift_policy(
        stored,
        candidate,
        allow_config_drift=True,
        has_whole_plan_approval=False,
    )
    assert result.ok
    assert "observability.log_level" in result.applied_changes
    assert not any("contract and model changes will apply" in warning for warning in result.warnings)


def test_drift_policy_pre_approval_warns_on_contract_change() -> None:
    stored = minimal_resolved_config()
    candidate = _candidate_with_overrides(stored, ["planning.max_depth=2"])
    result = apply_resume_config_drift_policy(
        stored,
        candidate,
        allow_config_drift=True,
        has_whole_plan_approval=False,
    )
    assert result.ok
    assert any("contract and model changes will apply" in warning for warning in result.warnings)


def test_drift_policy_limit_exhausted_without_limit_change_single_error() -> None:
    stored = minimal_resolved_config()
    result = apply_resume_config_drift_policy(
        stored,
        stored,
        allow_config_drift=True,
        has_whole_plan_approval=False,
        consumed_limits={"limits.planning.max_agent_turns": 40},
    )
    assert not result.ok
    assert len(result.errors) == 1
    assert "limit_exhausted" in result.errors[0]


def test_has_mandatory_whole_plan_approval_detects_approval_record(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_production_run_with_approval(store)
    reviews = store.list_reviews(run_id)
    plan = store.load_plan(run_id)
    assert has_mandatory_whole_plan_approval(reviews, int(plan.get("revision") or 0))


def test_prepare_resume_allows_pre_approval_drift_with_flag(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_planning_run(store)
    stored = store.load_resolved_config(run_id)
    candidate = copy.deepcopy(stored)
    candidate["run"] = dict(candidate.get("run") or {})
    candidate["run"]["output_goal"] = "Tweaked goal."

    plan = prepare_resume(
        store,
        run_id,
        candidate,
        allow_config_drift=True,
    )
    assert plan.effective_config["run"]["output_goal"] == "Tweaked goal."
    assert plan.warnings


def test_prepare_resume_still_blocks_without_flag(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_planning_run(store)
    stored = store.load_resolved_config(run_id)
    candidate = copy.deepcopy(stored)
    candidate["run"] = dict(candidate.get("run") or {})
    candidate["run"]["output_goal"] = "Tweaked goal."

    with pytest.raises(PrepareResumeBlockedError, match="output-goal digest"):
        prepare_resume(store, run_id, candidate, allow_config_drift=False)


def test_prepare_resume_post_approval_ignores_contract_with_flag(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_production_run_with_approval(store)
    stored = store.load_resolved_config(run_id)
    candidate = copy.deepcopy(stored)
    candidate["run"] = dict(candidate.get("run") or {})
    candidate["run"]["output_goal"] = "Tweaked goal."

    plan = prepare_resume(
        store,
        run_id,
        candidate,
        allow_config_drift=True,
    )
    assert plan.effective_config["run"]["output_goal"] == stored["run"]["output_goal"]
    assert "run.output_goal" in plan.ignored_config_changes
    assert plan.validation.approval_binding_valid


def test_validate_resume_config_update_pre_approval_drift_accepts_contract_change() -> None:
    stored = minimal_resolved_config()
    candidate = _candidate_with_overrides(stored, ["planning.max_depth=2"])
    drift = apply_resume_config_drift_policy(
        stored,
        candidate,
        allow_config_drift=True,
        has_whole_plan_approval=False,
    )
    update = validate_and_prepare_resume_config_update(
        stored_config=stored,
        candidate_config=drift.effective_config,
        stored_invocation={"command": "run"},
        candidate_invocation={"command": "resume"},
        contract_digest_may_change=True,
    )
    assert update.config_contract_digest == compute_config_contract_digest(drift.effective_config)
    assert update.config_contract_digest != compute_config_contract_digest(stored)


def test_validate_resume_config_update_post_approval_keeps_contract_unchanged() -> None:
    stored = minimal_resolved_config()
    candidate = _candidate_with_overrides(stored, ["planning.max_depth=2"])
    drift = apply_resume_config_drift_policy(
        stored,
        candidate,
        allow_config_drift=True,
        has_whole_plan_approval=True,
    )
    update = validate_and_prepare_resume_config_update(
        stored_config=stored,
        candidate_config=drift.effective_config,
        stored_invocation={"command": "run"},
        candidate_invocation={"command": "resume"},
        contract_digest_may_change=False,
    )
    assert update.config_contract_digest == compute_config_contract_digest(stored)


def test_validate_resume_config_update_rejects_contract_without_flag() -> None:
    stored = minimal_resolved_config()
    candidate = _candidate_with_overrides(stored, ["planning.max_depth=2"])
    with pytest.raises(ResumeConfigCommitError, match="contract"):
        validate_and_prepare_resume_config_update(
            stored_config=stored,
            candidate_config=candidate,
            stored_invocation={"command": "run"},
            candidate_invocation={},
        )
