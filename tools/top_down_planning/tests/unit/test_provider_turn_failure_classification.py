"""Provider-turn failure classification vs orchestration state conflicts."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from core_tools.provider import StubProvider
from core_tools.provider.errors import ProviderTurnError

from top_down_planning.orchestrator import RunEngine
from top_down_planning.orchestrator.errors import ReviewStateConflict
from top_down_planning.orchestrator.planning import PlanningPhaseOrchestrator
from top_down_planning.orchestrator.provider_turns import run_pending_focused_review
from top_down_planning.persistence import FileRunStore
from tests.support.run_builders import _create_planning_run


def test_engine_maps_review_state_conflict_without_provider_turn_failed(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T001701-001701"
    _create_planning_run(store, run_id)
    engine = RunEngine(
        store,
        create_provider=lambda _config, _workspace: StubProvider(),
    )

    with patch.object(
        PlanningPhaseOrchestrator,
        "run",
        side_effect=ReviewStateConflict(
            "advisory handoff already completed for finding_set_id 'fs-01'"
        ),
    ):
        result = engine.continue_run(run_id, single_step=True)

    assert result.ok is False
    run = store.load_run(run_id)
    assert run["status"] == "paused"
    assert run["stop"]["code"] == "review_state_conflict"
    assert run["phase_action_id"] is None


def test_engine_records_interrupted_phase_action_on_provider_turn_failed(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T001701-001701"
    _create_planning_run(store, run_id)
    run = store.load_run(run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["phase_action_id"] = "action-live"
    store.save_run(run_id, run, expected)
    engine = RunEngine(
        store,
        create_provider=lambda _config, _workspace: StubProvider(),
    )

    with patch.object(
        PlanningPhaseOrchestrator,
        "run",
        side_effect=ProviderTurnError("stream stalled", session_id="stub-session"),
    ):
        result = engine.continue_run(run_id, single_step=True)

    assert result.ok is False
    paused = store.load_run(run_id)
    assert paused["status"] == "paused"
    assert paused["stop"]["code"] == "provider_turn_failed"
    assert paused["stop"]["details"]["phase_action_id"] == "action-live"
    assert paused["stop"]["details"]["domain_committed"] is False


def test_pending_focused_review_failure_is_review_state_conflict(
    tmp_path: Path,
) -> None:
    from top_down_planning.orchestrator.focused_review import (
        FocusedReviewOrchestrator,
        FocusedReviewResult,
    )

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T001701-001701"
    _create_planning_run(store, run_id)

    with patch(
        "top_down_planning.orchestrator.provider_turns.find_pending_focused_review_loop_id",
        return_value="review-focused-plan-01",
    ):
        with patch.object(
            FocusedReviewOrchestrator,
            "run",
            return_value=FocusedReviewResult(
                ok=False,
                loop_id="review-focused-plan-01",
                status="blocked",
                reviewer_session_id="sess",
                revision_cycles=0,
                reason="focused reviewer blocked the scoped review",
            ),
        ):
            with pytest.raises(ReviewStateConflict, match="focused reviewer blocked"):
                run_pending_focused_review(
                    store,
                    run_id,
                    StubProvider(),
                    review_type="focused_plan",
                )


def test_focused_review_unexpected_driver_result_is_review_state_conflict(
    tmp_path: Path,
) -> None:
    from top_down_planning.orchestrator.focused_review import FocusedReviewOrchestrator
    from top_down_planning.orchestrator.review_loop_driver import ReviewLoopDriver
    from tests.support.focused_review import create_production_run
    from tests.helpers import request_focused_review

    store = FileRunStore(tmp_path)
    create_production_run(store)
    run_id = "run-20260101T000501-000501"
    request_focused_review(
        store,
        run_id,
        {"type": "focused_output", "scope": {"item_ids": ["item-first"]}},
        role="producer",
        phase="production",
    )()

    with patch.object(ReviewLoopDriver, "run", return_value=object()):
        with pytest.raises(ReviewStateConflict, match="unexpected result"):
            FocusedReviewOrchestrator(store, run_id, StubProvider()).run(
                "review-focused-output-01"
            )
