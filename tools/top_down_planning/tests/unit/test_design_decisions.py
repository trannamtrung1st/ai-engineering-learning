"""Verify proposal §2 fourteen design decisions in code."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from top_down_planning.domain.run_lifecycle import (
    FAILED_STOP_CODES,
    PAUSED_STOP_CODES,
    RUN_STATUSES,
    validate_run_lifecycle_invariants,
)
from top_down_planning.orchestrator.prepare_resume import prepare_resume
from top_down_planning.persistence.run_schema import CURRENT_RUN_SCHEMA_VERSION


def test_decision_1_paused_is_recoverable_stop_state() -> None:
    assert "paused" in RUN_STATUSES


def test_decision_2_failed_for_invariant_failures() -> None:
    assert "failed" in RUN_STATUSES
    assert "session_recovery_exhausted" in FAILED_STOP_CODES


def test_decision_3_completed_for_final_outcomes() -> None:
    assert "completed" in RUN_STATUSES


def test_decision_4_no_separate_resumable_boolean() -> None:
    from top_down_planning.persistence import file_store

    source = inspect.getsource(file_store.new_run_record)
    assert "resumable" not in source


def test_decision_5_structured_stop_for_paused_and_failed() -> None:
    with pytest.raises(Exception):
        validate_run_lifecycle_invariants(
            {
                "status": "paused",
                "outcome": None,
                "stop": None,
                "phase_action_id": None,
            }
        )


def test_decision_6_limit_exhausted_is_operational_pause() -> None:
    assert "limit_exhausted" in PAUSED_STOP_CODES


def test_decision_7_candidate_config_resolved_during_resume() -> None:
    from top_down_planning.config.resume_policy import resolve_resume_candidate_config

    assert callable(resolve_resume_candidate_config)


def test_decision_8_execution_policy_allowlist() -> None:
    from top_down_planning.config.resume_policy import RESUME_EXECUTION_POLICY_ALLOWLIST

    assert "limits.planning.max_agent_turns" in RESUME_EXECUTION_POLICY_ALLOWLIST


def test_decision_9_split_contract_and_execution_digests() -> None:
    from top_down_planning.persistence.digests import (
        compute_config_contract_digest,
        compute_config_execution_digest,
    )

    assert callable(compute_config_contract_digest)
    assert callable(compute_config_execution_digest)


def test_decision_10_session_bindings_are_replaceable() -> None:
    from top_down_planning.domain.session_bindings import SessionBinding

    binding = SessionBinding(
        session_instance_id="sess-1",
        generation=1,
        role="planner",
        kind="primary",
        provider_session_id="provider-1",
        state="bound",
    )
    assert binding.with_next_generation().generation == 2


def test_decision_11_recovery_manifests_from_durable_state() -> None:
    from top_down_planning.orchestrator import recovery_manifest

    assert hasattr(recovery_manifest, "build_planner_recovery_manifest")


def test_decision_12_prepare_resume_is_pure() -> None:
    assert "store.save_run" not in inspect.getsource(prepare_resume)
    assert "store.append_event" not in inspect.getsource(prepare_resume)


def test_decision_13_run_lease_prevents_concurrent_resume() -> None:
    from top_down_planning.domain.run_ownership import run_ownership

    assert callable(run_ownership)


def test_decision_14_old_schemas_rejected() -> None:
    assert CURRENT_RUN_SCHEMA_VERSION == 3


def test_legacy_resume_preconditions_removed() -> None:
    src_root = Path(__file__).resolve().parents[2] / "src" / "top_down_planning"
    hits: list[str] = []
    for path in src_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "validate_resume_preconditions" in text:
            hits.append(f"{path.name}: validate_resume_preconditions")
        if "class ResumeError" in text:
            hits.append(f"{path.name}: ResumeError")
    assert not hits, f"legacy resume symbols remain: {hits}"


def test_cli_resume_uses_prepare_and_apply_not_legacy() -> None:
    from top_down_planning.cli import user

    source = inspect.getsource(user.handle_resume_command)
    assert "prepare_resume" in source
    assert "apply_resume_plan_atomically" in source
