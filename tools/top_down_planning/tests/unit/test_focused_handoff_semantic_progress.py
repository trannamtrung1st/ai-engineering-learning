"""Semantic focused-review progress tokens for internal continuation."""

from __future__ import annotations

from pathlib import Path

from top_down_planning.orchestrator.focused_review_handoff_progress import (
    focused_review_semantic_progress_token,
)
from top_down_planning.persistence import FileRunStore
from tests.helpers import record_finding_actions, save_review_payload
from tests.support.focused_review import (
    create_production_run_open_item_second,
    focused_owner_revision_pending_loop,
)
from tests.support.focused_until_completed import (
    seed_focused_output_owner_pending_after_evidence,
)
from core_tools.provider import StubProvider
from top_down_planning.orchestrator.phases import PRODUCTION


def test_review_progress_token_changes_when_finding_actions_recorded_without_production_revision_change(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T010101-010101"
    loop_id = seed_focused_output_owner_pending_after_evidence(
        store,
        provider,
        run_id=run_id,
        record_owner_finding_actions=False,
    )
    production_revision_before = int(store.load_production(run_id)["revision"])
    token_before = focused_review_semantic_progress_token(store, run_id, loop_id)

    loop_payload = store.load_review(run_id, loop_id)
    record_finding_actions(
        store,
        run_id,
        {
            "loop_id": loop_id,
            "finding_set_id": str(loop_payload.get("finding_set_id") or ""),
            "finding_actions": [
                {
                    "finding_id": "finding-01",
                    "action": "fix",
                    "actor_role": "producer",
                    "rationale": "done",
                }
            ],
        },
        role="producer",
        phase="production",
        loop_id=loop_id,
    )()

    token_after = focused_review_semantic_progress_token(store, run_id, loop_id)
    assert token_before != token_after
    assert int(store.load_production(run_id)["revision"]) == production_revision_before


def test_internal_handoff_stall_detects_repeated_semantic_token(tmp_path: Path) -> None:
    from top_down_planning.orchestrator.engine import (
        RunStepResult,
        _internal_handoff_stalled,
    )
    from top_down_planning.orchestrator.phase_step_disposition import PhaseStepDisposition

    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T010102-010102"
    loop_id = seed_focused_output_owner_pending_after_evidence(
        store,
        provider,
        run_id=run_id,
        record_owner_finding_actions=False,
    )
    token = focused_review_semantic_progress_token(store, run_id, loop_id)
    step = RunStepResult(
        phase="production",
        ok=False,
        status="running",
        outcome=None,
        disposition=PhaseStepDisposition.INTERNAL_HANDOFF,
        progress_key=token,
    )
    assert not _internal_handoff_stalled([step])
    assert _internal_handoff_stalled([step, step])


def test_internal_handoff_allows_a_b_a_semantic_progress(tmp_path: Path) -> None:
    from top_down_planning.orchestrator.engine import (
        RunStepResult,
        _internal_handoff_stalled,
    )
    from top_down_planning.orchestrator.phase_step_disposition import PhaseStepDisposition

    token_a = ("loop", "focused_output", "pending", "", 1, "fs", 1, (), False, 2, 1, "rev", "")
    token_b = ("loop", "focused_output", "pending", "finding_verification", 1, "fs", 2, (), True, 2, 1, "rev", "")
    steps = [
        RunStepResult(
            phase="production",
            ok=False,
            status="running",
            outcome=None,
            disposition=PhaseStepDisposition.INTERNAL_HANDOFF,
            progress_key=token_a,
        ),
        RunStepResult(
            phase="production",
            ok=False,
            status="running",
            outcome=None,
            disposition=PhaseStepDisposition.INTERNAL_HANDOFF,
            progress_key=token_b,
        ),
        RunStepResult(
            phase="production",
            ok=False,
            status="running",
            outcome=None,
            disposition=PhaseStepDisposition.INTERNAL_HANDOFF,
            progress_key=token_a,
        ),
    ]
    assert _internal_handoff_stalled(steps)
