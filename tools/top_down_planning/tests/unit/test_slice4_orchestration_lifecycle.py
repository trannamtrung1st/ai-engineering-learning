"""Slice 4 orchestration lifecycle regressions (temp/tdp-slice4-orchestration-review.md)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.resume_plan import ResumePlan, ResumePlanValidation, ResumeStateTransition
from top_down_planning.domain.run_lifecycle import StopRecord, continuation_ok_from_run
from top_down_planning.orchestrator.apply_resume import ApplyResumeError, apply_resume_plan_atomically
from top_down_planning.orchestrator.engine import RunEngine
from top_down_planning.orchestrator.failure import mark_run_failed
from top_down_planning.orchestrator.planning import PlanningPhaseOrchestrator
from top_down_planning.orchestrator.phases import PLANNING, PRODUCTION, WHOLE_PLAN_REVIEW
from top_down_planning.orchestrator.run_transitions import (
    complete_run_with_outcome,
    fail_run,
    pause_run,
)
from top_down_planning.persistence import FileRunStore
from core_tools.provider import StubProvider
from tests.helpers import create_run_kwargs, minimal_resolved_config


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


def _create_running_run(store: FileRunStore, run_id: str = "run-20260101T010001-010001") -> str:
    config = minimal_resolved_config()
    store.create_run(
        run_id,
        plan=_sample_plan(),
        phase=PLANNING,
        **create_run_kwargs(store.root, resolved_config=config),
    )
    return run_id


def _pause_stop(phase: str = PLANNING) -> StopRecord:
    return StopRecord(
        code="user_cancelled",
        category="operational",
        phase=phase,
        message="cancelled",
    )


def test_pause_run_refuses_completed_run_without_mutation(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    complete_run_with_outcome(store, run_id, "accepted")
    run_after_complete = store.load_run(run_id)
    revision_after_complete = int(run_after_complete["revision"])
    events_before = len(store.load_events(run_id))

    result = pause_run(store, run_id, stop=_pause_stop())

    assert result["status"] == "completed"
    assert result["outcome"] == "accepted"
    assert int(result["revision"]) == revision_after_complete
    assert len(store.load_events(run_id)) == events_before


def test_pause_run_refuses_failed_run_without_mutation(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    mark_run_failed(store, run_id, message="invariant")
    run = store.load_run(run_id)
    rev = int(run["revision"])
    events_before = len(store.load_events(run_id))

    result = pause_run(store, run_id, stop=_pause_stop())

    assert result["status"] == "failed"
    assert int(result["revision"]) == rev
    assert len(store.load_events(run_id)) == events_before


def test_complete_run_refuses_outcome_rewrite_on_completed_run(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    complete_run_with_outcome(store, run_id, "blocked")
    run = store.load_run(run_id)
    rev = int(run["revision"])
    events_before = len(store.load_events(run_id))

    result = complete_run_with_outcome(store, run_id, "accepted")

    assert result["status"] == "completed"
    assert result["outcome"] == "blocked"
    assert int(result["revision"]) == rev
    assert len(store.load_events(run_id)) == events_before


def test_mark_run_failed_preserves_operational_paused_run(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    pause_run(
        store,
        run_id,
        stop=StopRecord(
            code="limit_exhausted",
            category="operational",
            phase=PLANNING,
            message="limit",
            details={
                "limit": "limits.planning.max_agent_turns",
                "consumed": 1,
                "configured": 1,
            },
        ),
    )
    run = store.load_run(run_id)
    rev = int(run["revision"])

    mark_run_failed(store, run_id, message="secondary event failure")

    after = store.load_run(run_id)
    assert after["status"] == "paused"
    assert after["stop"]["code"] == "limit_exhausted"
    assert int(after["revision"]) == rev


def test_continuation_ok_from_run_blocked_completed_is_false() -> None:
    assert continuation_ok_from_run({"status": "completed", "outcome": "accepted"}) is True
    assert continuation_ok_from_run({"status": "completed", "outcome": "blocked"}) is False
    assert continuation_ok_from_run({"status": "paused", "outcome": None}) is False


def test_continue_run_on_blocked_completed_reports_ok_false_twice(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["status"] = "completed"
    run["outcome"] = "blocked"
    run["phase"] = WHOLE_PLAN_REVIEW
    store.save_run(run_id, run, expected_revision)

    provider = StubProvider()
    engine = RunEngine(store, create_provider=lambda _c, _w: provider)

    first = engine.continue_run(run_id)
    second = engine.continue_run(run_id)

    assert first.ok is False
    assert second.ok is False
    assert first.outcome == "blocked"
    assert second.outcome == "blocked"


def test_continue_run_paused_before_until_target_does_not_report_ok_true(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["status"] = "paused"
    run["phase"] = PRODUCTION
    run["stop"] = {
        "code": "limit_exhausted",
        "category": "operational",
        "phase": PRODUCTION,
        "message": "limit",
        "details": {},
    }
    store.save_run(run_id, run, expected_revision)

    provider = StubProvider()
    engine = RunEngine(store, create_provider=lambda _c, _w: provider)
    result = engine.continue_run(run_id, until="validated")

    assert result.ok is False
    assert result.status == "paused"


def test_continue_run_paused_user_cancelled_sets_cancelled_true(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    pause_run(store, run_id, stop=_pause_stop())

    provider = StubProvider()
    engine = RunEngine(store, create_provider=lambda _c, _w: provider)
    result = engine.continue_run(run_id)

    assert result.ok is False
    assert result.status == "paused"
    assert result.cancelled is True


def test_continue_run_until_target_reached_while_running(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["phase"] = WHOLE_PLAN_REVIEW
    store.save_run(run_id, run, expected_revision)

    provider = StubProvider()
    engine = RunEngine(store, create_provider=lambda _c, _w: provider)
    result = engine.continue_run(run_id, until="plan")

    assert result.ok is True
    assert result.target_reached is True
    assert result.status == "running"


def test_fail_run_refuses_paused_run_without_mutation(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    pause_run(
        store,
        run_id,
        stop=StopRecord(
            code="limit_exhausted",
            category="operational",
            phase=PLANNING,
            message="limit",
            details={"limit": "limits.planning.max_agent_turns", "consumed": 1, "configured": 1},
        ),
    )
    paused = store.load_run(run_id)
    revision_after_pause = int(paused["revision"])
    events_before = len(store.load_events(run_id))

    result = fail_run(
        store,
        run_id,
        stop=StopRecord(
            code="orchestrator_invariant_failure",
            category="invariant",
            phase=PLANNING,
            message="should not apply",
        ),
    )

    assert result["status"] == "paused"
    assert result["stop"]["code"] == "limit_exhausted"
    assert int(result["revision"]) == revision_after_pause
    assert len(store.load_events(run_id)) == events_before


def test_apply_resume_rejects_crafted_failed_to_running_transition(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["status"] = "failed"
    run["stop"] = {
        "code": "orchestrator_invariant_failure",
        "category": "invariant",
        "phase": PLANNING,
        "message": "failed",
    }
    store.save_run(run_id, run, expected_revision)
    config = store.load_resolved_config(run_id)

    plan = ResumePlan(
        run_id=run_id,
        expected_run_revision=int(run["revision"]),
        state_transition=ResumeStateTransition(
            from_status="running",
            to_status="running",
            prior_stop_code=None,
        ),
        config_changes={},
        session_policy={},
        validation=ResumePlanValidation(
            contract_digest_valid=True,
            plan_binding_valid=True,
            approval_binding_valid=True,
            evidence_binding_valid=True,
        ),
        effective_config=config,
    )

    with pytest.raises(ApplyResumeError, match="terminal status 'failed'"):
        apply_resume_plan_atomically(store, plan, resolved_config=config)


def test_pause_run_refuses_paused_run_without_overwriting_stop(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    pause_run(
        store,
        run_id,
        stop=StopRecord(
            code="limit_exhausted",
            category="operational",
            phase=PLANNING,
            message="limit",
            details={
                "limit": "limits.planning.max_agent_turns",
                "consumed": 1,
                "configured": 1,
            },
        ),
    )
    paused = store.load_run(run_id)
    revision_after_pause = int(paused["revision"])
    events_before = len(store.load_events(run_id))

    result = pause_run(store, run_id, stop=_pause_stop())

    assert result["status"] == "paused"
    assert result["stop"]["code"] == "limit_exhausted"
    assert int(result["revision"]) == revision_after_pause
    assert len(store.load_events(run_id)) == events_before


def test_complete_run_refuses_paused_run_without_mutation(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    pause_run(
        store,
        run_id,
        stop=StopRecord(
            code="limit_exhausted",
            category="operational",
            phase=PLANNING,
            message="limit",
            details={
                "limit": "limits.planning.max_agent_turns",
                "consumed": 1,
                "configured": 1,
            },
        ),
    )
    paused = store.load_run(run_id)
    revision_after_pause = int(paused["revision"])
    events_before = len(store.load_events(run_id))

    result = complete_run_with_outcome(store, run_id, "accepted")

    assert result["status"] == "paused"
    assert result.get("outcome") is None
    assert int(result["revision"]) == revision_after_pause
    assert len(store.load_events(run_id)) == events_before


def test_engine_unsupported_phase_does_not_create_provider(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["phase"] = "output_validated"
    store.save_run(run_id, run, expected_revision)

    def _forbidden_factory(_config: object, _workspace: object) -> StubProvider:
        raise AssertionError("create_provider must not run for unsupported phase")

    engine = RunEngine(store, create_provider=_forbidden_factory)
    result = engine.continue_run(run_id, single_step=True)

    assert result.ok is False
    assert "unsupported phase" in (result.reason or "")


def test_prepared_parent_pending_amendment_pauses_with_registered_stop(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010002-010002"
    config = minimal_resolved_config()
    store.create_run(
        run_id,
        plan=_sample_plan(),
        phase=PLANNING,
        run_extras={"run_kind": "parent_execution"},
        **create_run_kwargs(store.root, resolved_config=config),
    )
    production = store.load_production(run_id)
    expected = int(production["revision"])
    production = dict(production)
    production["revision"] = expected + 1
    amendment_id = "amend-prepared-01"
    production["pending_amendment_id"] = amendment_id
    production["amendment_requests"] = [
        {
            "id": amendment_id,
            "status": "pending",
            "evidence": "Prepared package needs plan change.",
            "affected_refs": ["item-root"],
        }
    ]
    store.save_production(run_id, production, expected)

    engine = RunEngine(store, create_provider=lambda _c, _w: StubProvider())
    result = engine.continue_run(run_id, single_step=True)

    assert result.ok is False
    run = store.load_run(run_id)
    assert run["status"] == "paused"
    assert run["stop"]["code"] == "prepared_plan_amendment_required"


def test_apply_resume_paused_requires_prior_stop_code(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    pause_run(
        store,
        run_id,
        stop=StopRecord(
            code="limit_exhausted",
            category="operational",
            phase=PLANNING,
            message="limit",
            details={"limit": "limits.planning.max_agent_turns", "consumed": 1, "configured": 1},
        ),
    )
    run = store.load_run(run_id)
    config = store.load_resolved_config(run_id)
    plan = ResumePlan(
        run_id=run_id,
        expected_run_revision=int(run["revision"]),
        state_transition=ResumeStateTransition(
            from_status="paused",
            to_status="running",
            prior_stop_code=None,
        ),
        config_changes={},
        session_policy={},
        validation=ResumePlanValidation(
            contract_digest_valid=True,
            plan_binding_valid=True,
            approval_binding_valid=True,
            evidence_binding_valid=True,
            context_binding_valid=True,
        ),
        effective_config=config,
    )
    with pytest.raises(ApplyResumeError, match="prior_stop_code"):
        apply_resume_plan_atomically(store, plan, resolved_config=config)


def test_apply_resume_already_completed_blocked_is_not_ok(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["status"] = "completed"
    run["outcome"] = "blocked"
    run["stop"] = None
    store.save_run(run_id, run, expected_revision)
    plan = ResumePlan(
        run_id=run_id,
        expected_run_revision=int(run["revision"]),
        state_transition=None,
        config_changes={},
        session_policy={},
        validation=ResumePlanValidation(
            contract_digest_valid=True,
            plan_binding_valid=True,
            approval_binding_valid=True,
            evidence_binding_valid=True,
            context_binding_valid=True,
        ),
        already_completed=True,
        message="run already completed",
    )
    result = apply_resume_plan_atomically(store, plan, resolved_config=store.load_resolved_config(run_id))
    assert result["ok"] is False
    assert result["already_completed"] is True


def test_invalid_phase_with_pending_amendment_does_not_create_provider(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010003-010003"
    config = minimal_resolved_config()
    store.create_run(
        run_id,
        plan=_sample_plan(),
        phase="invalid_phase",
        **create_run_kwargs(store.root, resolved_config=config),
    )
    production = store.load_production(run_id)
    expected = int(production["revision"])
    production = dict(production)
    production["revision"] = expected + 1
    amendment_id = "amend-01"
    production["pending_amendment_id"] = amendment_id
    production["amendment_requests"] = [
        {
            "id": amendment_id,
            "status": "pending",
            "evidence": "needs change",
            "affected_refs": ["item-root"],
        }
    ]
    store.save_production(run_id, production, expected)

    def _forbidden_factory(_config: object, _workspace: object) -> StubProvider:
        raise AssertionError("create_provider must not run for invalid phase")

    engine = RunEngine(store, create_provider=_forbidden_factory)
    result = engine.continue_run(run_id, single_step=True)

    assert result.ok is False
    assert "unsupported phase" in (result.reason or "")


def test_completed_continue_run_ok_skips_preflight(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    complete_run_with_outcome(store, run_id, "accepted")

    with patch(
        "top_down_planning.orchestrator.engine.kill_orphan_agents",
        side_effect=RuntimeError("orphan scan failed"),
    ):
        result = RunEngine(
            store,
            create_provider=lambda _config, _workspace: StubProvider(),
        ).continue_run(run_id)

    assert result.ok is True
    assert continuation_ok_from_run(store.load_run(run_id))


def test_interrupt_after_run_completed_does_not_report_cancelled(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)

    def complete_then_interrupt(self: PlanningPhaseOrchestrator) -> None:
        complete_run_with_outcome(store, run_id, "accepted")
        raise KeyboardInterrupt

    engine = RunEngine(
        store,
        create_provider=lambda _config, _workspace: StubProvider(),
    )
    with patch.object(PlanningPhaseOrchestrator, "run", complete_then_interrupt):
        result = engine.continue_run(run_id, single_step=True)

    assert result.cancelled is False
    assert result.ok is True
    run = store.load_run(run_id)
    assert run["status"] == "completed"
    assert run["outcome"] == "accepted"


def test_apply_resume_already_completed_rejects_running_run(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    run = store.load_run(run_id)
    config = store.load_resolved_config(run_id)
    plan = ResumePlan(
        run_id=run_id,
        expected_run_revision=int(run["revision"]),
        state_transition=None,
        config_changes={},
        session_policy={},
        validation=ResumePlanValidation(
            contract_digest_valid=True,
            plan_binding_valid=True,
            approval_binding_valid=True,
            evidence_binding_valid=True,
            context_binding_valid=True,
        ),
        already_completed=True,
        message="run already completed",
    )
    with pytest.raises(ApplyResumeError, match="does not match actual status"):
        apply_resume_plan_atomically(store, plan, resolved_config=config)
