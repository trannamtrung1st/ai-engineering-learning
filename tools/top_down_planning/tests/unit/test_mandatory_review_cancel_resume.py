"""Cancel/resume durability for mandatory whole_* review owner-revision boundaries."""

from __future__ import annotations

import copy
from pathlib import Path
from unittest.mock import patch

import pytest

from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.domain.run_lifecycle import StopRecord
from top_down_planning.orchestrator.apply_resume import apply_resume_plan_atomically
from top_down_planning.orchestrator.mandatory_review_stages import mark_findings_open
from top_down_planning.orchestrator.phases import (
    PLAN_VALIDATED,
    WHOLE_OUTPUT_REVIEW,
    WHOLE_PLAN_REVIEW,
)
from top_down_planning.orchestrator.prepare_resume import prepare_resume
from top_down_planning.orchestrator.review_loop_driver import ReviewLoopDriver
from top_down_planning.orchestrator.run_transitions import pause_run
from top_down_planning.persistence import FileRunStore
from core_tools.provider import StubProvider
from tests.helpers import (
    apply_plan,
    done_events,
    mandatory_initial_respond_request,
    mandatory_scope_review_respond_request,
    mandatory_verification_respond_request,
    respond_review,
    save_review_payload,
    seed_mandatory_interrupted_owner_revision_loop,
)
from tests.unit.test_mandatory_whole_review_driver import (
    _blocker_finding,
    _create_driver_run,
    _FakeAdapter,
)


def _pause_user_cancelled(
    store: FileRunStore,
    run_id: str,
    *,
    phase: str,
) -> None:
    pause_run(
        store,
        run_id,
        stop=StopRecord(
            code="user_cancelled",
            category="operational",
            phase=phase,
            message="cancelled by user",
            details={},
        ),
    )


def _resume_from_user_cancel(store: FileRunStore, run_id: str) -> None:
    stored = store.load_resolved_config(run_id)
    plan = prepare_resume(store, run_id, stored)
    apply_resume_plan_atomically(
        store,
        plan,
        resolved_config=stored,
        invocation=store.load_invocation(run_id),
    )


def _seed_revision_in_progress_with_stale_verification(
    store: FileRunStore,
    run_id: str,
    loop_id: str,
    *,
    target_revision: int,
    revision_cycles: int = 1,
    pending_revision_cycle_entry: bool = False,
    review_type: str = "whole_plan",
    findings: list[dict] | None = None,
) -> None:
    save_review_payload(
        store,
        run_id,
        {
            "id": loop_id,
            "type": review_type,
            "revise_at": "blocker",
            "target_revision": target_revision,
            "scope": {"kind": review_type},
            "status": "pending",
            "findings": findings or [_blocker_finding()],
            "revision_cycles": revision_cycles,
            "lifecycle_status": "revision_in_progress",
            "active_stage": "finding_verification",
            "finding_set_id": f"{loop_id}-fs-01",
            "verification_result": {"decision": "needs_revision"},
            "pending_revision_cycle_entry": pending_revision_cycle_entry,
            "scope_review_rounds": 0,
            "review_record_schema_version": 2,
            "review_contract_version": 2,
        },
    )


def test_mandatory_stage_respond_decision_ignores_stale_verification_in_revision_in_progress() -> None:
    from top_down_planning.domain.reviews import mandatory_stage_respond_decision
    from tests.helpers import make_review_loop

    loop = make_review_loop(
        id="review-whole-output-01",
        type="whole_output",
        reviewer_session_id="s",
        target_revision=4,
        scope={"kind": "whole_output"},
        status="pending",
        lifecycle_status="revision_in_progress",
        active_stage="finding_verification",
        verification_result={"decision": "needs_revision"},
        revise_at="blocker",
    )
    assert mandatory_stage_respond_decision(loop) == "pending"


def test_resume_revision_in_progress_does_not_replay_verification_needs_revision_whole_plan(
    tmp_path: Path,
) -> None:
    """Case A: owner revision pending; stale verification_result must not reopen findings."""

    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260824T031448-0bede2"
    planner_session_id, loop_id = _create_driver_run(store, run_id, provider=provider)
    adapter = _FakeAdapter(store, run_id, owner_session_id=planner_session_id)
    respond_review(
        store,
        run_id,
        mandatory_initial_respond_request(
            store,
            run_id,
            loop_id=loop_id,
            target_revision=0,
            review_type="whole_plan",
            decision="changes_requested",
            findings=[_blocker_finding()],
        ),
        phase=WHOLE_PLAN_REVIEW,
        loop_id=loop_id,
    )()
    seed_mandatory_interrupted_owner_revision_loop(store, run_id, loop_id)
    loop = store.load_review(run_id, loop_id)
    loop["verification_result"] = {"decision": "needs_revision"}
    save_review_payload(store, run_id, loop)
    _pause_user_cancelled(store, run_id, phase=WHOLE_PLAN_REVIEW)
    _resume_from_user_cancel(store, run_id)

    mark_calls: list[str] = []
    real_mark = mark_findings_open

    def _track_mark(loop: ReviewLoop) -> ReviewLoop:
        mark_calls.append(str(loop.lifecycle_status))
        return real_mark(loop)

    provider.script_turn(
        done_events(text="turn complete"),
        mutate_store=apply_plan(
            store,
            run_id,
            base_revision=0,
            operations=[
                {
                    "op": "update_item",
                    "item_id": "item-root",
                    "patch": {"outcome": "Improved outcome."},
                }
            ],
            phase=WHOLE_PLAN_REVIEW,
        ),
    )

    def _verification_respond() -> None:
        payload = store.load_review(run_id, loop_id)
        finding_set_id = str(payload.get("finding_set_id") or f"{loop_id}-fs-01")
        respond_review(
            store,
            run_id,
            mandatory_verification_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=1,
                review_type="whole_plan",
                finding_set_id=finding_set_id,
                finding_results=[
                    {
                        "finding_id": "finding-01",
                        "disposition": "resolved",
                        "evidence": ["fixed"],
                        "direct_side_effects": [],
                    }
                ],
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=loop_id,
        )()

    def _scope_clear() -> None:
        respond_review(
            store,
            run_id,
            mandatory_scope_review_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=1,
                review_type="whole_plan",
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=loop_id,
        )()

    provider.script_turn(done_events(text="turn complete"), mutate_store=_verification_respond)
    provider.script_turn(done_events(text="turn complete"), mutate_store=_scope_clear)
    from top_down_planning.orchestrator.mandatory_whole_review import MandatoryWholeReviewResult

    adapter.approval_result = MandatoryWholeReviewResult(
        ok=True,
        phase=PLAN_VALIDATED,
        status="running",
        outcome=None,
        loop_id=loop_id,
        reviewer_session_id="stub-reviewer",
        revision_cycles=1,
    )

    with patch(
        "top_down_planning.orchestrator.review_loop_driver.mark_findings_open",
        side_effect=_track_mark,
    ):
        result = ReviewLoopDriver(store, run_id, provider, adapter).run()

    assert result.ok is True
    assert "revision_in_progress" not in mark_calls
    run = store.load_run(run_id)
    assert (run.get("stop") or {}).get("code") != "orchestrator_invariant_failure"
    review = store.load_review(run_id, loop_id)
    assert review["revision_cycles"] == 1


def test_resume_revision_in_progress_after_owner_mutation_prepares_recheck_whole_plan(
    tmp_path: Path,
) -> None:
    """Case B: artifact advanced before cancel; resume must recheck without rerunning owner."""

    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260824T031500-a1b2c3"
    planner_session_id, loop_id = _create_driver_run(store, run_id, provider=provider)
    adapter = _FakeAdapter(store, run_id, owner_session_id=planner_session_id)
    _seed_revision_in_progress_with_stale_verification(
        store,
        run_id,
        loop_id,
        target_revision=0,
        revision_cycles=1,
    )
    apply_plan(
        store,
        run_id,
        base_revision=0,
        operations=[
            {
                "op": "update_item",
                "item_id": "item-root",
                "patch": {"outcome": "Owner already revised."},
            }
        ],
        phase=WHOLE_PLAN_REVIEW,
    )()
    _pause_user_cancelled(store, run_id, phase=WHOLE_PLAN_REVIEW)
    _resume_from_user_cancel(store, run_id)

    owner_turns = {"count": 0}
    real_resume_owner = ReviewLoopDriver._resume_owner_with_findings

    def _track_owner(self: ReviewLoopDriver, loop: ReviewLoop) -> None:
        owner_turns["count"] += 1
        return real_resume_owner(self, loop)

    provider.script_turn(
        done_events(text="turn complete"),
        mutate_store=respond_review(
            store,
            run_id,
            mandatory_verification_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=1,
                review_type="whole_plan",
                finding_set_id=f"{loop_id}-fs-01",
                finding_results=[
                    {
                        "finding_id": "finding-01",
                        "disposition": "resolved",
                        "evidence": ["fixed"],
                        "direct_side_effects": [],
                    }
                ],
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=loop_id,
        ),
    )

    with patch.object(ReviewLoopDriver, "_resume_owner_with_findings", _track_owner):
        loop_before = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
        normalized, delivered = ReviewLoopDriver(
            store, run_id, provider, adapter
        )._normalize_loop_for_resume(loop_before)
        assert delivered is True
        assert normalized.lifecycle_status == "verification_pending"
        assert owner_turns["count"] == 0



def test_repeated_cancel_resume_revision_in_progress_is_idempotent_whole_plan(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260824T031700-c3d4e5"
    planner_session_id, loop_id = _create_driver_run(store, run_id, provider=provider)
    adapter = _FakeAdapter(store, run_id, owner_session_id=planner_session_id)
    _seed_revision_in_progress_with_stale_verification(
        store,
        run_id,
        loop_id,
        target_revision=0,
    )

    for _ in range(2):
        _pause_user_cancelled(store, run_id, phase=WHOLE_PLAN_REVIEW)
        _resume_from_user_cancel(store, run_id)
        review = store.load_review(run_id, loop_id)
        assert review["lifecycle_status"] == "revision_in_progress"
        assert review["revision_cycles"] == 1

    provider.script_turn(
        done_events(text="turn complete"),
        mutate_store=apply_plan(
            store,
            run_id,
            base_revision=0,
            operations=[
                {
                    "op": "update_item",
                    "item_id": "item-root",
                    "patch": {"outcome": "Improved."},
                }
            ],
            phase=WHOLE_PLAN_REVIEW,
        ),
    )

    def _verification_respond() -> None:
        payload = store.load_review(run_id, loop_id)
        finding_set_id = str(payload.get("finding_set_id") or f"{loop_id}-fs-01")
        respond_review(
            store,
            run_id,
            mandatory_verification_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=1,
                review_type="whole_plan",
                finding_set_id=finding_set_id,
                finding_results=[
                    {
                        "finding_id": "finding-01",
                        "disposition": "resolved",
                        "evidence": ["fixed"],
                        "direct_side_effects": [],
                    }
                ],
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=loop_id,
        )()

    def _scope_clear() -> None:
        respond_review(
            store,
            run_id,
            mandatory_scope_review_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=1,
                review_type="whole_plan",
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=loop_id,
        )()

    provider.script_turn(done_events(text="turn complete"), mutate_store=_verification_respond)
    provider.script_turn(done_events(text="turn complete"), mutate_store=_scope_clear)
    from top_down_planning.orchestrator.mandatory_whole_review import MandatoryWholeReviewResult

    adapter.approval_result = MandatoryWholeReviewResult(
        ok=True,
        phase=PLAN_VALIDATED,
        status="running",
        outcome=None,
        loop_id=loop_id,
        reviewer_session_id="stub-reviewer",
        revision_cycles=1,
    )
    result = ReviewLoopDriver(store, run_id, provider, adapter).run()
    assert (store.load_run(run_id).get("stop") or {}).get("code") != (
        "orchestrator_invariant_failure"
    )
    assert result.ok is True


def test_limit_extension_pending_revision_cycle_entry_charges_once_on_resume(
    tmp_path: Path,
) -> None:
    """Case C: pending_revision_cycle_entry must charge exactly one revision cycle."""

    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260824T031800-d4e5f6"
    planner_session_id, loop_id = _create_driver_run(
        store,
        run_id,
        provider=provider,
        limits={"max_revision_cycles": 1},
    )
    adapter = _FakeAdapter(store, run_id, owner_session_id=planner_session_id)
    _seed_revision_in_progress_with_stale_verification(
        store,
        run_id,
        loop_id,
        target_revision=0,
        revision_cycles=1,
        pending_revision_cycle_entry=True,
    )
    stored = store.load_resolved_config(run_id)
    candidate = copy.deepcopy(stored)
    candidate["limits"]["whole_plan_review"]["max_revision_cycles"] = 2
    resume_plan = prepare_resume(store, run_id, candidate, allow_config_drift=True)
    apply_resume_plan_atomically(
        store,
        resume_plan,
        resolved_config=candidate,
        invocation=store.load_invocation(run_id),
    )
    review = store.load_review(run_id, loop_id)
    assert review["lifecycle_status"] == "revision_in_progress"
    assert review.get("pending_revision_cycle_entry") is True

    provider.script_turn(
        done_events(text="turn complete"),
        mutate_store=apply_plan(
            store,
            run_id,
            base_revision=0,
            operations=[
                {
                    "op": "update_item",
                    "item_id": "item-root",
                    "patch": {"outcome": "Cycle two fix."},
                }
            ],
            phase=WHOLE_PLAN_REVIEW,
        ),
    )

    cycles_before = int(store.load_review(run_id, loop_id)["revision_cycles"])
    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    with patch.object(
        ReviewLoopDriver,
        "_prepare_recheck",
        return_value=loop,
    ):
        ReviewLoopDriver(store, run_id, provider, adapter)._resume_interrupted_owner_revision(
            loop
        )
    review_after = store.load_review(run_id, loop_id)
    assert int(review_after["revision_cycles"]) == cycles_before + 1
    assert not review_after.get("pending_revision_cycle_entry")
