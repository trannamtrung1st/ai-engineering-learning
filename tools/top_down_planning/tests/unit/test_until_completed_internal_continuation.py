"""Regression: ``--until completed`` must drive recoverable focused-review handoffs."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from core_tools.provider import StubProvider
from top_down_planning.agent_tool import ProductionAgentService
from top_down_planning.domain.reviews import ReviewLoop, mark_advisory_handoff_incomplete
from top_down_planning.orchestrator import RunEngine
from top_down_planning.orchestrator.phase_step_disposition import PhaseStepDisposition
from top_down_planning.orchestrator.phases import PRODUCTION
from top_down_planning.orchestrator.production import (
    ProductionPhaseOrchestrator,
    ProductionPhaseResult,
)
from top_down_planning.orchestrator.run_transitions import pause_run
from top_down_planning.domain.run_lifecycle import StopRecord
from top_down_planning.persistence import FileRunStore
from tests.conftest import run_cli
from tests.helpers import (
    create_run_kwargs,
    done_events,
    grant_capability,
    minimal_resolved_config,
    plan_root_item,
    save_review_payload,
)
from top_down_planning.domain.models import Plan
from top_down_planning.orchestrator.phases import PLANNING
from tests.support.focused_review import (
    advisory_optional_focused_output_loop,
    create_production_run_open_item_second,
    focused_owner_revision_pending_loop,
)


def _evidence_revision_applied_owner_actions_pending(
    store: FileRunStore,
    provider: StubProvider,
    *,
    run_id: str = "run-20260101T009001-009001",
) -> str:
    create_production_run_open_item_second(store, provider, run_id=run_id)
    loop_id = "review-focused-output-01"
    save_review_payload(
        store,
        run_id,
        focused_owner_revision_pending_loop(item_ids=["item-first"]),
    )
    run = store.load_run(run_id)
    workspace = Path(str(run["workspace"]))
    artifact = workspace / "artifacts" / "first-v2.txt"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("revised", encoding="utf-8")
    token = grant_capability(store, run_id, role="producer", phase=PRODUCTION)
    service = ProductionAgentService(store, run_id)
    production_revision = int(store.load_production(run_id)["revision"])
    result = service.apply(
        {
            "production_revision": production_revision,
            "evidence_revision": True,
            "focused_review_loop_id": loop_id,
            "plan_items": ["item-first"],
            "dispositions": {
                "item-first": {
                    "disposition": "completed",
                    "evidence": "Revised artifact.",
                }
            },
            "outputs": [
                {
                    "id": "output-first-v2",
                    "type": "artifact",
                    "ref": "artifacts/first-v2.txt",
                }
            ],
            "contributions": [
                {
                    "item_id": "item-first",
                    "output_refs": ["output-first-v2"],
                    "summary": "Evidence before owner actions.",
                }
            ],
            "summary": "Focused evidence revision first.",
        },
        capability_token=token,
    )
    assert result["ok"] is True
    return loop_id


def test_until_completed_continues_past_focused_owner_work_pending(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T009001-009001"
    loop_id = _evidence_revision_applied_owner_actions_pending(
        store, provider, run_id=run_id
    )

    for index in range(20):
        provider.script_turn(done_events(text=f"continuation turn {index}"))

    phase_runs: list[ProductionPhaseResult] = []
    original_run = ProductionPhaseOrchestrator.run

    def _tracking_run(self: ProductionPhaseOrchestrator) -> ProductionPhaseResult:
        outcome = original_run(self)
        phase_runs.append(outcome)
        return outcome

    engine = RunEngine(store, create_provider=lambda _c, _w: provider)
    with patch.object(ProductionPhaseOrchestrator, "run", _tracking_run):
        continuation = engine.continue_run(run_id, until="completed")

    assert continuation.steps
    assert continuation.steps[0].disposition == PhaseStepDisposition.INTERNAL_HANDOFF
    assert len(phase_runs) >= 2
    assert continuation.reason != "focused review owner work is pending"


def test_until_completed_continues_past_recoverably_incomplete_focused_review(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T009002-009002"
    loop_id = "review-focused-output-01"
    create_production_run_open_item_second(store, provider, run_id=run_id)
    loop = ReviewLoop.from_dict(
        advisory_optional_focused_output_loop(item_ids=["item-first"])
    )
    incomplete = mark_advisory_handoff_incomplete(
        loop,
        missing_finding_ids=["finding-opt"],
    )
    save_review_payload(store, run_id, incomplete.to_dict())

    provider.script_turn(done_events(text="producer owner advisory session start"))
    provider.script_turn(done_events(text="focused output advisory retry"))
    for index in range(20):
        provider.script_turn(done_events(text=f"focused incomplete continuation {index}"))

    engine = RunEngine(store, create_provider=lambda _c, _w: provider)
    continuation = engine.continue_run(run_id, until="completed")

    assert continuation.reason != "focused review is recoverably incomplete"
    assert len(continuation.steps) >= 2


def test_default_resume_single_step_stops_after_one_phase_invocation(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T009003-009003"
    _evidence_revision_applied_owner_actions_pending(store, provider, run_id=run_id)
    provider.script_turn(done_events(text="owner revision session start"))
    provider.script_turn(done_events(text="owner revision turn"))

    engine = RunEngine(store, create_provider=lambda _c, _w: provider)
    continuation = engine.continue_run(run_id, until="completed", single_step=True)

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
    _evidence_revision_applied_owner_actions_pending(store, provider, run_id=run_id)

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


def test_cli_resume_single_step_without_until(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T009004-009004"
    _evidence_revision_applied_owner_actions_pending(store, provider, run_id=run_id)
    provider.script_turn(done_events(text="owner revision session start"))
    provider.script_turn(done_events(text="owner revision turn"))
    with patch("top_down_planning.cli.user.create_provider", return_value=provider):
        result = run_cli(["resume", "--run", run_id, "--runs-dir", str(store.root)])

    assert result.exit_code == 1
    combined = f"{result.stdout}\n{result.stderr}"
    assert "focused review owner work is pending" in combined
