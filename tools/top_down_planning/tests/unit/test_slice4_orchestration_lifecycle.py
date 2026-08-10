"""Slice 4 orchestration lifecycle regressions (temp/tdp-slice4-orchestration-review.md)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.resume_plan import ResumePlan, ResumePlanValidation, ResumeStateTransition
from top_down_planning.domain.run_lifecycle import StopRecord, continuation_ok_from_run
from top_down_planning.domain.run_ownership import (
    clear_orphan_resume_lock,
    ownership_cleanup_failures,
    resolve_run_dir,
    resume_lock_dir,
    resume_lock_metadata_path,
)
from top_down_planning.orchestrator.apply_resume import ApplyResumeError, apply_resume_plan_atomically
from top_down_planning.orchestrator.engine import RunEngine
from top_down_planning.orchestrator.failure import mark_run_failed
from top_down_planning.orchestrator.planning import PlanningPhaseOrchestrator
from top_down_planning.orchestrator.phases import PLAN_AMENDMENT, PLANNING, PRODUCTION, WHOLE_PLAN_REVIEW
from top_down_planning.orchestrator.run_transitions import (
    complete_run_with_outcome,
    fail_run,
    pause_run,
    pending_capability_revoke_phase,
)
from top_down_planning.persistence import FileRunStore
from core_tools.provider import StubProvider
from tests.helpers import (
    create_run_kwargs,
    minimal_resolved_config,
    whole_plan_approval_record,
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


def test_owned_scope_interrupt_after_completed_matches_canonical_state(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    engine = RunEngine(
        store,
        create_provider=lambda _config, _workspace: StubProvider(),
    )

    def complete_then_interrupt(
        self: RunEngine,
        run_id: str,
        **kwargs: object,
    ) -> object:
        complete_run_with_outcome(store, run_id, "accepted")
        raise KeyboardInterrupt

    with patch.object(RunEngine, "_continue_run_unlocked", complete_then_interrupt):
        result = engine.continue_run(run_id)

    assert result.cancelled is False
    assert result.ok is True
    assert result.status == "completed"
    assert result.outcome == "accepted"
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


def test_terminal_continue_run_ok_without_ownership_acquisition(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    complete_run_with_outcome(store, run_id, "accepted")
    run_dir = Path(store.run_dir(run_id))
    run_dir.mkdir(parents=True, exist_ok=True)
    resume_lock_dir(run_dir).mkdir()
    resume_lock_metadata_path(run_dir).write_text(
        __import__("json").dumps(
            {
                "run_id": run_id,
                "pid": 999999,
                "owner_token": "foreign-token",
                "acquired_at": "2026-01-01T00:00:00Z",
                "process_identity": "999999:0",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = RunEngine(
        store,
        create_provider=lambda _config, _workspace: StubProvider(),
    ).continue_run(run_id)

    assert result.ok is True
    assert store.load_run(run_id)["outcome"] == "accepted"


def test_running_target_reached_runs_preflight_before_return(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010010-010010"
    config = minimal_resolved_config()
    store.create_run(
        run_id,
        plan=_sample_plan(),
        phase=PRODUCTION,
        **create_run_kwargs(store.root, resolved_config=config),
    )
    store.save_review(run_id, whole_plan_approval_record(store, run_id))

    with patch(
        "top_down_planning.orchestrator.engine.execute_session_policy_if_registered",
    ) as policy_mock:
        with patch(
            "top_down_planning.orchestrator.engine.kill_orphan_agents",
        ) as orphan_mock:
            result = RunEngine(
                store,
                create_provider=lambda _config, _workspace: StubProvider(),
            ).continue_run(run_id, until="plan", session_policy={})

    policy_mock.assert_called_once()
    orphan_mock.assert_called_once()
    assert result.ok is True
    assert result.target_reached is True


def test_empty_lock_dir_without_artifacts_reports_no_cleanup(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    resume_lock_dir(run_dir).mkdir()
    assert clear_orphan_resume_lock(run_dir) is False


def test_pause_run_revokes_capabilities_only_after_durable_commit(tmp_path: Path) -> None:
    from tests.helpers import grant_capability

    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    token_id = token.split(".", 1)[0]

    pause_run(store, run_id, stop=_pause_stop(), revoke_phase=PLANNING)
    assert store.load_capability(run_id, token_id)["revoked"] is True
    assert pending_capability_revoke_phase(store.load_run(run_id)) is None


def test_pause_run_preserves_capabilities_when_lifecycle_commit_fails(tmp_path: Path) -> None:
    from tests.helpers import grant_capability

    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    token_id = token.split(".", 1)[0]

    with patch.object(store, "commit", side_effect=OSError("lifecycle cas failed")):
        with pytest.raises(OSError, match="lifecycle cas failed"):
            pause_run(store, run_id, stop=_pause_stop(), revoke_phase=PLANNING)

    assert store.load_run(run_id)["status"] == "running"
    assert store.load_capability(run_id, token_id)["revoked"] is False


def test_continue_run_preserves_planning_completion_when_observability_emit_fails(
    tmp_path: Path,
) -> None:
    from core_tools.observability import NullSink
    from tests.helpers import done_events
    from top_down_planning.observability import ObservabilityContext, wrap_store_with_observability

    raw_store = FileRunStore(tmp_path)
    run_id = _create_running_run(raw_store)
    observability = ObservabilityContext(sink=NullSink(), run_id=run_id)

    def fail_planning_candidate_emit(event: object) -> None:
        category = getattr(event, "category", None)
        message = getattr(event, "message", "")
        if category == "state" and message == "planning candidate ready":
            raise RuntimeError("emit failed")

    observability.emit = fail_planning_candidate_emit  # type: ignore[method-assign]
    store = wrap_store_with_observability(raw_store, observability)
    provider = StubProvider()
    provider.script_turn(done_events(text="planner session start"))
    provider.script_turn(done_events(signal="candidate_plan_ready", text="done"))

    result = RunEngine(
        store,
        create_provider=lambda _c, _w: provider,
        observability=observability,
    ).continue_run(run_id, until="plan")

    run = raw_store.load_run(run_id)
    assert run["status"] == "running"
    assert run["phase"] == WHOLE_PLAN_REVIEW
    assert result.ok is True
    assert result.target_reached is True
    assert any(
        event.get("type") == "planning_candidate_ready"
        for event in raw_store.load_events(run_id)
    )


def test_continue_run_preserves_planning_when_post_commit_revoke_fails(
    tmp_path: Path,
) -> None:
    from tests.helpers import done_events, grant_capability
    from top_down_planning.orchestrator.run_transitions import (
        pending_capability_revoke_phase,
        reconcile_pending_capability_revocation,
    )

    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    token_id = token.split(".", 1)[0]
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    updated = dict(run)
    updated["revision"] = expected_revision + 1
    updated["phase"] = WHOLE_PLAN_REVIEW
    updated["pending_capability_revoke_phase"] = PLANNING
    store.save_run(run_id, updated, expected_revision)
    store.append_event(
        run_id,
        {"type": "planning_candidate_ready", "run_id": run_id, "plan_revision": 0},
    )

    with patch(
        "top_down_planning.orchestrator.run_transitions.revoke_capabilities_for_phase",
        side_effect=OSError("revoke failed"),
    ):
        with patch("top_down_planning.orchestrator.engine.mark_run_failed") as mark_failed:
            result = RunEngine(
                store,
                create_provider=lambda _c, _w: StubProvider(),
            ).continue_run(run_id, until="plan")

    mark_failed.assert_not_called()
    run = store.load_run(run_id)
    assert run["status"] == "running"
    assert run["phase"] == WHOLE_PLAN_REVIEW
    assert pending_capability_revoke_phase(run) == PLANNING
    assert store.load_capability(run_id, token_id)["revoked"] is False
    assert result.ok is True
    assert result.target_reached is True

    reconcile_pending_capability_revocation(store, run_id)
    assert pending_capability_revoke_phase(store.load_run(run_id)) is None
    assert store.load_capability(run_id, token_id)["revoked"] is True


def _planning_continue_run_store(tmp_path: Path) -> tuple[FileRunStore, str]:
    from tests.helpers import create_run_kwargs, plan_root_item

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T030001-030001"
    root = plan_root_item(title="Deliver", outcome="Deliver.")
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver.",
        items={"item-root": root},
    )
    config = minimal_resolved_config()
    config["limits"]["planning"] = {"max_items_added": 20, "max_agent_turns": 40}
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=config),
    )
    return store, run_id


def test_continue_run_blocks_whole_plan_review_when_revoke_unresolved_same_call(
    tmp_path: Path,
) -> None:
    from tests.helpers import done_events, grant_capability

    store, run_id = _planning_continue_run_store(tmp_path)
    grant_capability(store, run_id, role="planner", phase=PLANNING)
    provider = StubProvider()
    provider.script_turn(done_events(text="planner session start"))
    provider.script_turn(done_events(signal="candidate_plan_ready", text="done"))

    provider_calls = 0

    def counting_factory(_config: dict, _workspace: object) -> StubProvider:
        nonlocal provider_calls
        provider_calls += 1
        return provider

    with patch(
        "top_down_planning.orchestrator.run_transitions.revoke_capabilities_for_phase",
        side_effect=OSError("revoke failed"),
    ):
        result = RunEngine(
            store,
            create_provider=counting_factory,
        ).continue_run(run_id, until="validated")

    run = store.load_run(run_id)
    assert result.ok is False
    assert result.status == "running"
    assert result.phase == WHOLE_PLAN_REVIEW
    assert result.reason == (
        "continuation blocked until pending capability revocation converges"
    )
    assert pending_capability_revoke_phase(run) == PLANNING
    assert provider_calls == 1


def test_continue_run_blocks_when_pending_revoke_unresolved_before_provider(
    tmp_path: Path,
) -> None:
    from tests.helpers import grant_capability

    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    token_id = token.split(".", 1)[0]
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    updated = dict(run)
    updated["revision"] = expected_revision + 1
    updated["phase"] = WHOLE_PLAN_REVIEW
    updated["pending_capability_revoke_phase"] = PLANNING
    store.save_run(run_id, updated, expected_revision)

    provider_calls = 0

    def forbidden_factory(_config: dict, _workspace: object) -> StubProvider:
        nonlocal provider_calls
        provider_calls += 1
        return StubProvider()

    with patch(
        "top_down_planning.orchestrator.run_transitions.revoke_capabilities_for_phase",
        side_effect=OSError("revoke failed"),
    ):
        result = RunEngine(
            store,
            create_provider=forbidden_factory,
        ).continue_run(run_id, until="validated")

    assert provider_calls == 0
    assert result.ok is False
    assert store.load_run(run_id)["phase"] == WHOLE_PLAN_REVIEW
    assert pending_capability_revoke_phase(store.load_run(run_id)) == PLANNING
    assert store.load_capability(run_id, token_id)["revoked"] is False


def test_continue_run_blocks_amendment_when_revoke_all_unresolved(
    tmp_path: Path,
) -> None:
    from tests.helpers import grant_capability
    from top_down_planning.orchestrator.run_transitions import pending_capability_revoke_all

    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)
    token_id = token.split(".", 1)[0]
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    updated = dict(run)
    updated["revision"] = expected_revision + 1
    updated["phase"] = PLAN_AMENDMENT
    updated["status"] = "running"
    updated["pending_capability_revoke_all"] = True
    store.save_run(run_id, updated, expected_revision)

    provider_calls = 0

    def forbidden_factory(_config: dict, _workspace: object) -> StubProvider:
        nonlocal provider_calls
        provider_calls += 1
        return StubProvider()

    with patch.object(store, "revoke_capability", side_effect=OSError("revoke failed")):
        result = RunEngine(
            store,
            create_provider=forbidden_factory,
        ).continue_run(run_id, until="validated")

    assert provider_calls == 0
    assert result.ok is False
    run = store.load_run(run_id)
    assert run["phase"] == PLAN_AMENDMENT
    assert run["status"] == "running"
    assert pending_capability_revoke_all(run) is True
    assert store.load_capability(run_id, token_id)["revoked"] is False


def test_continue_run_proceeds_after_capability_revocation_converges(
    tmp_path: Path,
) -> None:
    from tests.helpers import grant_capability

    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    token_id = token.split(".", 1)[0]
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    updated = dict(run)
    updated["revision"] = expected_revision + 1
    updated["phase"] = WHOLE_PLAN_REVIEW
    updated["pending_capability_revoke_phase"] = PLANNING
    store.save_run(run_id, updated, expected_revision)

    provider_calls = 0

    def counting_factory(_config: dict, _workspace: object) -> StubProvider:
        nonlocal provider_calls
        provider_calls += 1
        return StubProvider()

    RunEngine(
        store,
        create_provider=counting_factory,
    ).continue_run(run_id, until="validated")

    assert provider_calls >= 1
    assert pending_capability_revoke_phase(store.load_run(run_id)) is None
    assert store.load_capability(run_id, token_id)["revoked"] is True


def test_report_ownership_cleanup_diagnostics_emits_observability_event(tmp_path: Path) -> None:
    from top_down_planning.domain.run_ownership import (
        _OWNERSHIP_CLEANUP_FAILURES,
        ownership_cleanup_failures,
    )
    from top_down_planning.observability import ObservabilityContext, report_ownership_cleanup_diagnostics
    from core_tools.observability import NullSink

    _OWNERSHIP_CLEANUP_FAILURES.clear()
    _OWNERSHIP_CLEANUP_FAILURES.append(
        {
            "type": "ownership_cleanup_failed",
            "run_id": "run-1",
            "path": str(tmp_path / "owner.json"),
            "error_class": "OSError",
            "message": "unlink failed",
            "safe_to_retry": True,
        }
    )
    emitted: list[Any] = []
    observability = ObservabilityContext(sink=NullSink(), run_id="run-1")
    observability.emit = lambda event: emitted.append(event)  # type: ignore[method-assign]

    drained = report_ownership_cleanup_diagnostics(observability, run_id="run-1")
    assert len(drained) == 1
    assert drained[0]["error_class"] == "OSError"
    assert len(emitted) == 1
    assert emitted[0].category == "ownership:cleanup_failed"
    assert emitted[0].fields["run_id"] == "run-1"
    assert ownership_cleanup_failures() == []


def test_pause_run_reconciles_capabilities_after_post_commit_revoke_failure(
    tmp_path: Path,
) -> None:
    from tests.helpers import grant_capability
    from top_down_planning.orchestrator.capability import revoke_capabilities_for_phase

    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    token_id = token.split(".", 1)[0]
    events_before = len(store.load_events(run_id))

    attempts = 0

    def revoke_side_effect(store_arg: FileRunStore, run_id_arg: str, phase: str) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("revoke failed")
        revoke_capabilities_for_phase(store_arg, run_id_arg, phase)

    with patch(
        "top_down_planning.orchestrator.run_transitions.revoke_capabilities_for_phase",
        side_effect=revoke_side_effect,
    ) as revoke_mock:
        pause_run(store, run_id, stop=_pause_stop(), revoke_phase=PLANNING)
        paused = store.load_run(run_id)
        assert paused["status"] == "paused"
        assert paused["pending_capability_revoke_phase"] == PLANNING
        assert store.load_capability(run_id, token_id)["revoked"] is False

        pause_run(store, run_id, stop=_pause_stop(), revoke_phase=PLANNING)
        assert revoke_mock.call_count == 2

    assert store.load_run(run_id)["status"] == "paused"
    assert store.load_capability(run_id, token_id)["revoked"] is True
    assert len(store.load_events(run_id)) == events_before + 1


def test_report_ownership_cleanup_diagnostics_emit_failure_does_not_raise(
    tmp_path: Path,
) -> None:
    from top_down_planning.domain.run_ownership import _OWNERSHIP_CLEANUP_FAILURES
    from top_down_planning.observability import ObservabilityContext, report_ownership_cleanup_diagnostics
    from core_tools.observability import NullSink

    _OWNERSHIP_CLEANUP_FAILURES.clear()
    _OWNERSHIP_CLEANUP_FAILURES.append(
        {
            "type": "ownership_cleanup_failed",
            "run_id": "run-1",
            "path": str(tmp_path / "owner.json"),
            "error_class": "OSError",
            "message": "unlink failed",
            "safe_to_retry": True,
        }
    )
    observability = ObservabilityContext(sink=NullSink(), run_id="run-1")

    def fail_emit(_event: Any) -> None:
        raise OSError("sink failed")

    observability.emit = fail_emit  # type: ignore[method-assign]

    report_ownership_cleanup_diagnostics(observability, run_id="run-1")


def test_drain_ownership_cleanup_failures_is_run_scoped() -> None:
    from top_down_planning.domain.run_ownership import (
        _OWNERSHIP_CLEANUP_FAILURES,
        drain_ownership_cleanup_failures,
        ownership_cleanup_failures,
    )

    _OWNERSHIP_CLEANUP_FAILURES.clear()
    _OWNERSHIP_CLEANUP_FAILURES.extend(
        [
            {"type": "ownership_cleanup_failed", "run_id": "run-a", "error_class": "OSError"},
            {"type": "ownership_cleanup_failed", "run_id": "run-b", "error_class": "OSError"},
        ]
    )
    drained_a = drain_ownership_cleanup_failures(run_id="run-a")
    assert len(drained_a) == 1
    assert drained_a[0]["run_id"] == "run-a"
    remaining = ownership_cleanup_failures()
    assert len(remaining) == 1
    assert remaining[0]["run_id"] == "run-b"
    _OWNERSHIP_CLEANUP_FAILURES.clear()


def _fail_stop(phase: str = PLANNING) -> StopRecord:
    return StopRecord(
        code="orchestrator_invariant_failure",
        category="invariant",
        phase=phase,
        message="failed",
    )


def test_continue_run_reconciles_pause_revoke_after_engine_restart(tmp_path: Path) -> None:
    from tests.helpers import grant_capability
    from top_down_planning.orchestrator.capability import revoke_capabilities_for_phase

    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    token_id = token.split(".", 1)[0]

    attempts = 0

    def revoke_side_effect(store_arg: FileRunStore, run_id_arg: str, phase: str) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("revoke failed")
        revoke_capabilities_for_phase(store_arg, run_id_arg, phase)

    with patch(
        "top_down_planning.orchestrator.run_transitions.revoke_capabilities_for_phase",
        side_effect=revoke_side_effect,
    ):
        pause_run(store, run_id, stop=_pause_stop(), revoke_phase=PLANNING)

    revision_before = int(store.load_run(run_id)["revision"])
    events_before = len(store.load_events(run_id))
    paused = store.load_run(run_id)
    assert paused["status"] == "paused"
    assert paused["pending_capability_revoke_phase"] == PLANNING
    assert store.load_capability(run_id, token_id)["revoked"] is False

    result = RunEngine(
        store,
        create_provider=lambda _config, _workspace: StubProvider(),
    ).continue_run(run_id, until="plan")

    assert result.ok is False
    assert int(store.load_run(run_id)["revision"]) == revision_before + 1
    assert store.load_capability(run_id, token_id)["revoked"] is True
    assert pending_capability_revoke_phase(store.load_run(run_id)) is None
    assert len(store.load_events(run_id)) == events_before

    repeat = RunEngine(
        store,
        create_provider=lambda _config, _workspace: StubProvider(),
    ).continue_run(run_id, until="plan")
    assert repeat.ok is False
    assert store.load_capability(run_id, token_id)["revoked"] is True


def test_continue_run_reconciles_fail_revoke_after_engine_restart(tmp_path: Path) -> None:
    from tests.helpers import grant_capability
    from top_down_planning.orchestrator.capability import revoke_capabilities_for_phase

    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    token_id = token.split(".", 1)[0]

    attempts = 0

    def revoke_side_effect(store_arg: FileRunStore, run_id_arg: str, phase: str) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("revoke failed")
        revoke_capabilities_for_phase(store_arg, run_id_arg, phase)

    with patch(
        "top_down_planning.orchestrator.run_transitions.revoke_capabilities_for_phase",
        side_effect=revoke_side_effect,
    ):
        fail_run(store, run_id, stop=_fail_stop(), revoke_phase=PLANNING)

    revision_before = int(store.load_run(run_id)["revision"])
    events_before = len(store.load_events(run_id))
    failed = store.load_run(run_id)
    assert failed["status"] == "failed"
    assert failed["pending_capability_revoke_phase"] == PLANNING
    assert store.load_capability(run_id, token_id)["revoked"] is False

    result = RunEngine(
        store,
        create_provider=lambda _config, _workspace: StubProvider(),
    ).continue_run(run_id, until="plan")

    assert result.ok is False
    assert int(store.load_run(run_id)["revision"]) == revision_before + 1
    assert store.load_capability(run_id, token_id)["revoked"] is True
    assert pending_capability_revoke_phase(store.load_run(run_id)) is None
    assert len(store.load_events(run_id)) == events_before


def test_continue_run_reconciles_complete_revoke_after_engine_restart(tmp_path: Path) -> None:
    from tests.helpers import grant_capability
    from top_down_planning.orchestrator.capability import revoke_capabilities_for_phase

    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    token_id = token.split(".", 1)[0]

    attempts = 0

    def revoke_side_effect(store_arg: FileRunStore, run_id_arg: str, phase: str) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("revoke failed")
        revoke_capabilities_for_phase(store_arg, run_id_arg, phase)

    with patch(
        "top_down_planning.orchestrator.run_transitions.revoke_capabilities_for_phase",
        side_effect=revoke_side_effect,
    ):
        complete_run_with_outcome(
            store,
            run_id,
            "accepted",
            revoke_phase=PLANNING,
        )

    revision_before = int(store.load_run(run_id)["revision"])
    events_before = len(store.load_events(run_id))
    completed = store.load_run(run_id)
    assert completed["status"] == "completed"
    assert completed["outcome"] == "accepted"
    assert completed["pending_capability_revoke_phase"] == PLANNING
    assert store.load_capability(run_id, token_id)["revoked"] is False

    result = RunEngine(
        store,
        create_provider=lambda _config, _workspace: StubProvider(),
    ).continue_run(run_id, until="plan")

    assert result.ok is True
    assert int(store.load_run(run_id)["revision"]) == revision_before + 1
    assert store.load_capability(run_id, token_id)["revoked"] is True
    assert pending_capability_revoke_phase(store.load_run(run_id)) is None
    assert len(store.load_events(run_id)) == events_before


def test_terminal_continue_run_retries_requeued_cleanup_diagnostic(tmp_path: Path) -> None:
    from top_down_planning.domain.run_ownership import (
        _OWNERSHIP_CLEANUP_FAILURES,
        ownership_cleanup_failures,
    )
    from top_down_planning.observability import ObservabilityContext, report_ownership_cleanup_diagnostics
    from core_tools.observability import NullSink

    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    pause_run(store, run_id, stop=_pause_stop())

    _OWNERSHIP_CLEANUP_FAILURES.clear()
    _OWNERSHIP_CLEANUP_FAILURES.append(
        {
            "type": "ownership_cleanup_failed",
            "run_id": run_id,
            "path": str(tmp_path / "owner.json"),
            "error_class": "OSError",
            "message": "unlink failed",
            "safe_to_retry": True,
        }
    )
    observability = ObservabilityContext(sink=NullSink(), run_id=run_id)

    def fail_emit(_event: Any) -> None:
        raise OSError("sink failed")

    observability.emit = fail_emit  # type: ignore[method-assign]
    with patch(
        "top_down_planning.observability._emit_cleanup_fallback_stderr",
        side_effect=OSError("stderr failed"),
    ):
        report_ownership_cleanup_diagnostics(observability, run_id=run_id)
    assert len(ownership_cleanup_failures()) == 1

    emitted: list[Any] = []
    observability.emit = lambda event: emitted.append(event)  # type: ignore[method-assign]
    RunEngine(
        store,
        create_provider=lambda _config, _workspace: StubProvider(),
        observability=observability,
    ).continue_run(run_id, until="plan")

    assert len(emitted) == 2
    cleanup_events = [event for event in emitted if event.category == "ownership:cleanup_failed"]
    assert len(cleanup_events) == 1
    assert ownership_cleanup_failures() == []


def test_ownership_cleanup_failure_queue_is_bounded_per_run() -> None:
    from top_down_planning.domain.run_ownership import (
        _MAX_CLEANUP_FAILURES_PER_RUN,
        _OWNERSHIP_CLEANUP_FAILURES,
        ownership_cleanup_dropped_counts,
        ownership_cleanup_failures,
        requeue_ownership_cleanup_failures,
    )

    _OWNERSHIP_CLEANUP_FAILURES.clear()
    overflow = 5
    for index in range(_MAX_CLEANUP_FAILURES_PER_RUN + overflow):
        requeue_ownership_cleanup_failures(
            [
                {
                    "type": "ownership_cleanup_failed",
                    "run_id": "run-1",
                    "error_class": "OSError",
                    "message": f"failure-{index}",
                    "safe_to_retry": True,
                }
            ]
        )

    assert len(ownership_cleanup_failures()) == _MAX_CLEANUP_FAILURES_PER_RUN
    assert ownership_cleanup_dropped_counts().get("run-1") == overflow
    _OWNERSHIP_CLEANUP_FAILURES.clear()


def test_continue_run_does_not_reconcile_capabilities_before_ownership(tmp_path: Path) -> None:
    import threading
    import time

    from tests.helpers import grant_capability
    from top_down_planning.domain.run_ownership import RunOwnershipError, run_ownership

    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    token_id = token.split(".", 1)[0]
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    updated = dict(run)
    updated["revision"] = expected_revision + 1
    updated["pending_capability_revoke_phase"] = PLANNING
    store.save_run(run_id, updated, expected_revision)
    run_dir = resolve_run_dir(store, run_id)
    assert run_dir is not None

    revoke_calls: list[bool] = []
    barrier = threading.Barrier(2)
    ownership_errors: list[RunOwnershipError] = []

    def track_revoke(*_args: Any, **_kwargs: Any) -> None:
        revoke_calls.append(True)

    def holder() -> None:
        with run_ownership(run_id, run_dir=run_dir):
            barrier.wait()
            time.sleep(0.3)

    def contender() -> None:
        try:
            barrier.wait()
            with patch(
                "top_down_planning.orchestrator.run_transitions.revoke_capabilities_for_phase",
                side_effect=track_revoke,
            ):
                RunEngine(
                    store,
                    create_provider=lambda _config, _workspace: StubProvider(),
                ).continue_run(run_id, until="plan")
        except RunOwnershipError as exc:
            ownership_errors.append(exc)

    holder_thread = threading.Thread(target=holder)
    contender_thread = threading.Thread(target=contender)
    holder_thread.start()
    contender_thread.start()
    holder_thread.join(timeout=5)
    contender_thread.join(timeout=5)
    assert not holder_thread.is_alive()
    assert not contender_thread.is_alive()

    assert revoke_calls == []
    assert store.load_capability(run_id, token_id)["revoked"] is False
    assert len(ownership_errors) == 1
    assert ownership_errors[0].code == "run_owned_by_live_process"


def test_resume_apply_removes_pending_capability_revoke_marker(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    pause_run(store, run_id, stop=_pause_stop(), revoke_phase=PLANNING)
    paused = store.load_run(run_id)
    assert pending_capability_revoke_phase(paused) is None

    config = store.load_resolved_config(run_id)
    plan = ResumePlan(
        run_id=run_id,
        expected_run_revision=int(paused["revision"]),
        state_transition=ResumeStateTransition(
            from_status="paused",
            to_status="running",
            prior_stop_code="user_cancelled",
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
    apply_resume_plan_atomically(store, plan, resolved_config=config)
    resumed = store.load_run(run_id)
    assert resumed["status"] == "running"
    assert pending_capability_revoke_phase(resumed) is None


def test_resume_apply_reconciles_pending_revoke_after_pause_revoke_failure(
    tmp_path: Path,
) -> None:
    from tests.helpers import grant_capability
    from top_down_planning.domain.run_ownership import run_ownership
    from top_down_planning.orchestrator.capability import revoke_capabilities_for_phase
    from top_down_planning.orchestrator.run_transitions import (
        reconcile_pending_capability_revocation,
    )

    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    token_id = token.split(".", 1)[0]
    run_dir = resolve_run_dir(store, run_id)
    assert run_dir is not None

    attempts = 0

    def revoke_side_effect(store_arg: FileRunStore, run_id_arg: str, phase: str) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("revoke failed")
        revoke_capabilities_for_phase(store_arg, run_id_arg, phase)

    with patch(
        "top_down_planning.orchestrator.run_transitions.revoke_capabilities_for_phase",
        side_effect=revoke_side_effect,
    ):
        pause_run(store, run_id, stop=_pause_stop(), revoke_phase=PLANNING)

    paused = store.load_run(run_id)
    revision_after_pause = int(paused["revision"])
    assert paused["pending_capability_revoke_phase"] == PLANNING
    assert store.load_capability(run_id, token_id)["revoked"] is False

    with run_ownership(run_id, run_dir=run_dir):
        reconcile_pending_capability_revocation(store, run_id)
    revision_after_reconcile = int(store.load_run(run_id)["revision"])
    assert pending_capability_revoke_phase(store.load_run(run_id)) is None
    assert store.load_capability(run_id, token_id)["revoked"] is True

    config = store.load_resolved_config(run_id)
    plan = ResumePlan(
        run_id=run_id,
        expected_run_revision=revision_after_reconcile,
        state_transition=ResumeStateTransition(
            from_status="paused",
            to_status="running",
            prior_stop_code="user_cancelled",
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
    apply_resume_plan_atomically(store, plan, resolved_config=config)

    resumed = store.load_run(run_id)
    assert resumed["status"] == "running"
    assert pending_capability_revoke_phase(resumed) is None
    assert store.load_capability(run_id, token_id)["revoked"] is True
    assert int(resumed["revision"]) == revision_after_reconcile + 1


def test_resume_apply_blocks_when_pending_revoke_cannot_converge(tmp_path: Path) -> None:
    from tests.helpers import grant_capability

    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    token_id = token.split(".", 1)[0]

    with patch(
        "top_down_planning.orchestrator.run_transitions.revoke_capabilities_for_phase",
        side_effect=OSError("revoke failed"),
    ):
        pause_run(store, run_id, stop=_pause_stop(), revoke_phase=PLANNING)

        revision_after_pause = int(store.load_run(run_id)["revision"])
        config = store.load_resolved_config(run_id)
        plan = ResumePlan(
            run_id=run_id,
            expected_run_revision=revision_after_pause,
            state_transition=ResumeStateTransition(
                from_status="paused",
                to_status="running",
                prior_stop_code="user_cancelled",
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
        with pytest.raises(
            ApplyResumeError,
            match="resume blocked until pending capability revocation converges",
        ):
            apply_resume_plan_atomically(store, plan, resolved_config=config)


def test_resume_apply_rejects_stale_plan_after_capability_reconciliation(
    tmp_path: Path,
) -> None:
    from tests.helpers import grant_capability
    from top_down_planning.orchestrator.capability import revoke_capabilities_for_phase

    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    token_id = token.split(".", 1)[0]

    attempts = 0

    def revoke_side_effect(store_arg: FileRunStore, run_id_arg: str, phase: str) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("revoke failed")
        revoke_capabilities_for_phase(store_arg, run_id_arg, phase)

    with patch(
        "top_down_planning.orchestrator.run_transitions.revoke_capabilities_for_phase",
        side_effect=revoke_side_effect,
    ):
        pause_run(store, run_id, stop=_pause_stop(), revoke_phase=PLANNING)

        revision_after_pause = int(store.load_run(run_id)["revision"])
        config = store.load_resolved_config(run_id)
        plan = ResumePlan(
            run_id=run_id,
            expected_run_revision=revision_after_pause,
            state_transition=ResumeStateTransition(
                from_status="paused",
                to_status="running",
                prior_stop_code="user_cancelled",
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
        with pytest.raises(ApplyResumeError, match="stale after capability reconciliation"):
            apply_resume_plan_atomically(store, plan, resolved_config=config)

    reconciled = store.load_run(run_id)
    assert reconciled["status"] == "paused"
    assert pending_capability_revoke_phase(reconciled) is None
    assert store.load_capability(run_id, token_id)["revoked"] is True


def test_global_cleanup_dropped_count_is_reported_on_continue_run(tmp_path: Path) -> None:
    from top_down_planning.domain.run_ownership import (
        _MAX_CLEANUP_FAILURES_GLOBAL,
        _MAX_CLEANUP_FAILURES_PER_RUN,
        _OWNERSHIP_CLEANUP_FAILURES,
        ownership_cleanup_dropped_counts,
        requeue_ownership_cleanup_failures,
    )
    from top_down_planning.observability import ObservabilityContext
    from core_tools.observability import NullSink

    store = FileRunStore(tmp_path)
    run_id = _create_running_run(store)
    pause_run(store, run_id, stop=_pause_stop())

    _OWNERSHIP_CLEANUP_FAILURES.clear()
    for run_index in range(8):
        for failure_index in range(_MAX_CLEANUP_FAILURES_PER_RUN):
            requeue_ownership_cleanup_failures(
                [
                    {
                        "type": "ownership_cleanup_failed",
                        "run_id": f"other-run-{run_index}",
                        "error_class": "OSError",
                        "message": f"{run_index}-{failure_index}",
                        "safe_to_retry": True,
                    }
                ]
            )
    requeue_ownership_cleanup_failures(
        [
            {
                "type": "ownership_cleanup_failed",
                "run_id": run_id,
                "error_class": "OSError",
                "message": "overflow",
                "safe_to_retry": True,
            }
        ]
    )
    assert ownership_cleanup_dropped_counts().get("__global__", 0) >= 1

    emitted: list[Any] = []
    observability = ObservabilityContext(sink=NullSink(), run_id=run_id)
    observability.emit = lambda event: emitted.append(event)  # type: ignore[method-assign]
    RunEngine(
        store,
        create_provider=lambda _config, _workspace: StubProvider(),
        observability=observability,
    ).continue_run(run_id, until="plan")

    dropped_events = [event for event in emitted if event.category == "ownership:cleanup_dropped"]
    assert dropped_events
    assert ownership_cleanup_dropped_counts().get("__global__", 0) == 0


def test_dropped_cleanup_count_stderr_fallback_and_retry() -> None:
    from top_down_planning.domain.run_ownership import (
        _OWNERSHIP_CLEANUP_DROPPED,
        _OWNERSHIP_CLEANUP_FAILURES,
        ownership_cleanup_dropped_counts,
        requeue_ownership_cleanup_dropped_count,
    )
    from top_down_planning.observability import ObservabilityContext, report_ownership_cleanup_diagnostics
    from core_tools.observability import NullSink

    _OWNERSHIP_CLEANUP_FAILURES.clear()
    _OWNERSHIP_CLEANUP_DROPPED.clear()
    requeue_ownership_cleanup_dropped_count("run-1", 3)
    observability = ObservabilityContext(sink=NullSink(), run_id="run-1")

    def fail_emit(_event: Any) -> None:
        raise OSError("sink failed")

    observability.emit = fail_emit  # type: ignore[method-assign]
    with patch(
        "top_down_planning.observability._emit_cleanup_fallback_stderr",
        side_effect=OSError("stderr failed"),
    ):
        report_ownership_cleanup_diagnostics(observability, run_id="run-1")
    assert ownership_cleanup_dropped_counts().get("run-1") == 3

    emitted: list[Any] = []
    observability.emit = lambda event: emitted.append(event)  # type: ignore[method-assign]
    report_ownership_cleanup_diagnostics(observability, run_id="run-1")
    assert len(emitted) == 1
    assert emitted[0].category == "ownership:cleanup_dropped"
    assert emitted[0].fields["dropped_count"] == 3
    assert ownership_cleanup_dropped_counts().get("run-1", 0) == 0


def test_dropped_cleanup_count_key_cardinality_is_bounded() -> None:
    from top_down_planning.domain.run_ownership import (
        _MAX_CLEANUP_DROPPED_RUN_KEYS,
        _OWNERSHIP_CLEANUP_DROPPED,
        ownership_cleanup_dropped_counts,
        requeue_ownership_cleanup_dropped_count,
    )

    _OWNERSHIP_CLEANUP_DROPPED.clear()
    overflow = 10
    for index in range(_MAX_CLEANUP_DROPPED_RUN_KEYS + overflow):
        requeue_ownership_cleanup_dropped_count(f"run-{index}", 1)

    counts = ownership_cleanup_dropped_counts()
    per_run_keys = [key for key in counts if key != "__global__"]
    assert len(per_run_keys) <= _MAX_CLEANUP_DROPPED_RUN_KEYS
    assert counts.get("__global__", 0) >= overflow
    _OWNERSHIP_CLEANUP_DROPPED.clear()
