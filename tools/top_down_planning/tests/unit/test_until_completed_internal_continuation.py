"""Regression: ``--until completed`` drives recoverable focused-review handoffs to completion."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from core_tools.provider import StubProvider
from top_down_planning.domain.models import Plan
from top_down_planning.domain.reviews import ReviewLoop, mark_advisory_handoff_incomplete
from top_down_planning.orchestrator import RunEngine
from top_down_planning.orchestrator.focused_review import FocusedReviewOrchestrator
from top_down_planning.orchestrator.phase_step_disposition import PhaseStepDisposition
from top_down_planning.orchestrator.phases import PLANNING, PRODUCTION
from top_down_planning.orchestrator.production import (
    ProductionPhaseOrchestrator,
    ProductionPhaseResult,
)
from top_down_planning.orchestrator.run_transitions import pause_run
from top_down_planning.domain.run_lifecycle import StopRecord
from top_down_planning.persistence import FileRunStore
from tests.conftest import run_cli
from tests.helpers import (
    apply_plan_and_complete_focused_owner_revision,
    create_run_kwargs,
    done_events,
    mandatory_plan_digest,
    minimal_resolved_config,
    plan_root_item,
    respond_review,
    save_review_payload,
    with_root_contract,
)
from tests.support.focused_review import (
    advisory_optional_focused_output_loop,
    create_planning_run,
    create_production_run_open_item_second,
    focused_owner_revision_pending_loop,
)
from tests.support.focused_until_completed import (
    assert_focused_output_workflow_complete,
    script_focused_output_through_completion,
    script_focused_plan_through_plan_target,
    seed_focused_output_owner_pending_after_evidence,
    seed_focused_plan_owner_pending,
)
from tests.support.stub_provider_factory import RotatingStubProviderFactory


def test_until_completed_reaches_accepted_through_focused_output_owner_handoff(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T009001-009001"
    factory = RotatingStubProviderFactory(store, run_id, strict_session_scripts=True)
    seed_provider = StubProvider()
    loop_id = seed_focused_output_owner_pending_after_evidence(
        store,
        seed_provider,
        run_id=run_id,
        record_owner_finding_actions=False,
    )
    loop_before = store.load_review(run_id, loop_id)
    assert not loop_before.get("finding_actions")
    script_focused_output_through_completion(factory, store, run_id, loop_id)

    continuation = RunEngine(
        store,
        create_provider=factory.create_provider,
    ).continue_run(run_id, until="completed")

    assert any(
        step.disposition == PhaseStepDisposition.INTERNAL_HANDOFF
        for step in continuation.steps
    )
    assert continuation.ok is True
    assert continuation.target_reached is True
    assert continuation.status == "completed"
    assert continuation.outcome == "accepted"
    assert len(factory.instances) >= 2
    assert_focused_output_workflow_complete(store, run_id, loop_id)


def test_until_completed_recovers_recoverably_incomplete_focused_output_to_completion(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T009002-009002"
    factory = RotatingStubProviderFactory(store, run_id)
    loop_id = "review-focused-output-01"
    seed_provider = StubProvider()
    create_production_run_open_item_second(store, seed_provider, run_id=run_id)
    loop = ReviewLoop.from_dict(
        advisory_optional_focused_output_loop(item_ids=["item-first"])
    )
    incomplete = mark_advisory_handoff_incomplete(
        loop,
        missing_finding_ids=["finding-opt"],
    )
    save_review_payload(store, run_id, incomplete.to_dict())

    def _defer_optional() -> None:
        loop_payload = store.load_review(run_id, loop_id)
        from tests.helpers import record_finding_actions

        record_finding_actions(
            store,
            run_id,
            {
                "loop_id": loop_id,
                "finding_set_id": str(loop_payload.get("finding_set_id") or ""),
                "finding_actions": [
                    {
                        "finding_id": "finding-opt",
                        "action": "defer",
                        "actor_role": "producer",
                        "rationale": "Accept risk.",
                    }
                ],
            },
            role="producer",
            phase=PRODUCTION,
            loop_id=loop_id,
        )()

    _defer_optional()
    factory.script_turn(done_events(text="production primary resume"))
    script_focused_output_through_completion(factory, store, run_id, loop_id)

    continuation = RunEngine(
        store,
        create_provider=factory.create_provider,
    ).continue_run(run_id, until="completed")

    assert continuation.ok is True
    assert continuation.target_reached is True
    assert continuation.status == "completed"
    assert store.load_review(run_id, loop_id)["status"] == "approved"


def test_until_plan_continues_focused_plan_owner_handoff(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T009010-009010"
    factory = RotatingStubProviderFactory(store, run_id, strict_session_scripts=True)
    loop_id = seed_focused_plan_owner_pending(store, run_id=run_id)
    assert not store.load_review(run_id, loop_id).get("finding_actions")
    script_focused_plan_through_plan_target(factory, store, run_id, loop_id)

    continuation = RunEngine(
        store,
        create_provider=factory.create_provider,
    ).continue_run(run_id, until="plan")

    assert continuation.ok is True
    assert continuation.target_reached is True
    assert store.load_run(run_id)["phase"] != PLANNING
    assert store.load_review(run_id, loop_id)["status"] == "approved"
    events = store.load_events(run_id)
    assert any(event.get("type") == "focused_review_recheck_requested" for event in events)
    assert any(event.get("type") == "focused_review_approved" for event in events)


def test_default_resume_single_step_stops_after_one_phase_invocation(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T009003-009003"
    seed_focused_output_owner_pending_after_evidence(
        store,
        provider,
        run_id=run_id,
        record_owner_finding_actions=False,
    )
    provider.script_turn(done_events(text="owner revision session start"))
    provider.script_turn(done_events(text="owner revision turn"))

    continuation = RunEngine(
        store,
        create_provider=lambda _c, _w: provider,
    ).continue_run(run_id, until="completed", single_step=True)

    assert len(continuation.steps) == 1
    assert continuation.ok is False
    assert continuation.reason == "focused review owner work is pending"
    assert store.load_run(run_id)["status"] == "running"


def test_until_completed_stops_on_limit_exhausted_pause(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T009006-009006"
    root = plan_root_item(title="Root", outcome="Root.")
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Goal.",
        items={"item-root": root},
    )
    store.create_run(
        run_id,
        plan=plan,
        phase=PLANNING,
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
    )
    pause_run(
        store,
        run_id,
        stop=StopRecord(
            code="limit_exhausted",
            category="operational",
            phase=PRODUCTION,
            message="limit",
            details={"limit": "limits.production.max_batches", "consumed": 1, "configured": 1},
        ),
    )

    provider = StubProvider()
    engine = RunEngine(store, create_provider=lambda _c, _w: provider)
    continuation = engine.continue_run(run_id, until="completed")

    assert continuation.ok is False
    assert continuation.status == "paused"
    assert continuation.target_reached is False


def test_until_completed_fails_when_internal_handoff_makes_no_progress(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T009005-009005"
    seed_focused_output_owner_pending_after_evidence(
        store,
        provider,
        run_id=run_id,
        record_owner_finding_actions=False,
    )

    def _stuck_soft_pending(self: ProductionPhaseOrchestrator) -> ProductionPhaseResult:
        run = self._store.load_run(self._run_id)
        return ProductionPhaseResult(
            ok=False,
            phase=str(run.get("phase") or PRODUCTION),
            status=str(run.get("status") or "running"),
            outcome=run.get("outcome"),
            session_id=None,
            batch_count=0,
            reason="focused review owner work is pending",
            disposition=PhaseStepDisposition.INTERNAL_HANDOFF,
        )

    engine = RunEngine(store, create_provider=lambda _c, _w: provider)
    with patch.object(ProductionPhaseOrchestrator, "run", _stuck_soft_pending):
        continuation = engine.continue_run(run_id, until="completed")

    assert continuation.ok is False
    assert "durable progress" in (continuation.reason or "").lower()
    assert len(continuation.steps) >= 2


def test_cli_resume_until_completed_exits_zero_with_target_reached(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T009004-009004"
    factory = RotatingStubProviderFactory(store, run_id, strict_session_scripts=True)
    seed_provider = StubProvider()
    loop_id = seed_focused_output_owner_pending_after_evidence(
        store, seed_provider, run_id=run_id
    )
    script_focused_output_through_completion(factory, store, run_id, loop_id)

    with patch(
        "top_down_planning.cli.user.create_provider",
        side_effect=lambda config, workspace, **_kwargs: factory.create_provider(
            config, workspace
        ),
    ):
        result = run_cli(
            [
                "resume",
                "--run",
                run_id,
                "--runs-dir",
                str(store.root),
                "--until",
                "completed",
                "--stream-json",
            ]
        )

    assert result.exit_code == 0
    payload = json.loads(result.stdout.strip())
    assert payload["ok"] is True
    assert payload["target_reached"] is True
    assert payload["status"] == "completed"


def test_cli_resume_single_step_without_until(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T009007-009007"
    seed_focused_output_owner_pending_after_evidence(
        store,
        provider,
        run_id=run_id,
        record_owner_finding_actions=False,
    )
    provider.script_turn(done_events(text="owner revision session start"))
    provider.script_turn(done_events(text="owner revision turn"))
    with patch("top_down_planning.cli.user.create_provider", return_value=provider):
        result = run_cli(["resume", "--run", run_id, "--runs-dir", str(store.root)])

    assert result.exit_code == 1
    combined = f"{result.stdout}\n{result.stderr}"
    assert "focused review owner work is pending" in combined
