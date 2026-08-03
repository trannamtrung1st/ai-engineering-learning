"""In-process mandatory review transitions (respond during Orchestrator.run)."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.orchestrator import WholePlanReviewOrchestrator
from top_down_planning.orchestrator.phases import WHOLE_PLAN_REVIEW
from top_down_planning.persistence import FileRunStore
from core_tools.provider import StubProvider
from tests.helpers import (
    apply_plan,
    done_events,
    mandatory_scope_review_found_respond_request,
    mandatory_initial_respond_request,
    mandatory_verification_needs_revision_request,
    respond_review,
)
from tests.unit.test_whole_plan_review import _create_run_at_whole_plan_review


def _blocker_finding() -> dict:
    return {
        "id": "finding-blocker-01",
        "severity": "blocker",
        "category": "correctness",
        "target_refs": ["item-api"],
        "issue": "Coverage gap.",
        "recommended_change": "Add acceptance checks.",
        "status": "unresolved",
    }


def test_in_process_scope_review_changes_requested_emits_event_and_enters_revision(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_plan_review(
        store,
        provider=provider,
        limits={"review": {"max_agent_turns_per_gate": 1}},
    )
    run_id = "run-20260101T000301-000301"

    provider.script_turn(
        done_events(text="initial clear"),
        mutate_store=lambda: respond_review(
            store,
            run_id,
            mandatory_initial_respond_request(
                store,
                run_id,
                loop_id="review-whole-plan-01",
                target_revision=0,
                review_type="whole_plan",
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id="review-whole-plan-01",
        )(),
    )
    provider.script_turn(
        done_events(text="blockers found"),
        mutate_store=lambda: respond_review(
            store,
            run_id,
            mandatory_scope_review_found_respond_request(
                store,
                run_id,
                loop_id="review-whole-plan-01",
                target_revision=0,
                review_type="whole_plan",
                findings=[_blocker_finding()],
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id="review-whole-plan-01",
        )(),
    )
    provider.script_turn(
        done_events(text="planner revise"),
        mutate_store=apply_plan(
            store,
            run_id,
            base_revision=0,
            operations=[
                {
                    "op": "update_item",
                    "item_id": "item-api",
                    "patch": {
                        "acceptance": [
                            "API behavior is verifiable.",
                            "Health check exists.",
                        ]
                    },
                }
            ],
            phase=WHOLE_PLAN_REVIEW,
        ),
    )
    provider.script_turn(done_events(text="verification delivery"))

    result = WholePlanReviewOrchestrator(store, run_id, provider).run()
    assert result.ok is False
    assert store.load_run(run_id)["stop"]["code"] == "limit_exhausted"

    review = store.load_review(run_id, "review-whole-plan-01")
    events = store.load_events(run_id)
    blocker_events = [
        event
        for event in events
        if event.get("type") == "whole_plan_scope_review_changes_requested"
    ]
    assert blocker_events
    assert blocker_events[-1]["finding_set_id"] == review["finding_set_id"]
    assert "prior_finding_set_id" in blocker_events[-1]
    assert review["lifecycle_status"] == "verification_pending"
    assert review["active_stage"] == "finding_verification"
    assert review["revision_cycles"] == 1
    assert review["finding_set_id"]


def test_in_process_needs_revision_enters_revision_without_illegal_transition(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_plan_review(
        store,
        provider=provider,
        limits={"review": {"max_agent_turns_per_gate": 1}},
    )
    run_id = "run-20260101T000301-000301"

    provider.script_turn(
        done_events(text="initial clear"),
        mutate_store=lambda: respond_review(
            store,
            run_id,
            mandatory_initial_respond_request(
                store,
                run_id,
                loop_id="review-whole-plan-01",
                target_revision=0,
                review_type="whole_plan",
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id="review-whole-plan-01",
        )(),
    )
    provider.script_turn(
        done_events(text="blockers found"),
        mutate_store=lambda: respond_review(
            store,
            run_id,
            mandatory_scope_review_found_respond_request(
                store,
                run_id,
                loop_id="review-whole-plan-01",
                target_revision=0,
                review_type="whole_plan",
                findings=[_blocker_finding()],
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id="review-whole-plan-01",
        )(),
    )
    provider.script_turn(
        done_events(text="planner revise"),
        mutate_store=apply_plan(
            store,
            run_id,
            base_revision=0,
            operations=[
                {
                    "op": "update_item",
                    "item_id": "item-api",
                    "patch": {
                        "acceptance": [
                            "API behavior is verifiable.",
                            "Health check exists.",
                        ]
                    },
                }
            ],
            phase=WHOLE_PLAN_REVIEW,
        ),
    )
    provider.script_turn(
        done_events(text="needs revision"),
        mutate_store=lambda: respond_review(
            store,
            run_id,
            mandatory_verification_needs_revision_request(
                store,
                run_id,
                loop_id="review-whole-plan-01",
                target_revision=1,
                review_type="whole_plan",
                finding_set_id="review-whole-plan-01-fs-01",
                finding_results=[
                    {
                        "finding_id": "finding-blocker-01",
                        "disposition": "partially_resolved",
                        "evidence": ["partial fix"],
                        "direct_side_effects": [],
                    }
                ],
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id="review-whole-plan-01",
        )(),
    )
    provider.script_turn(
        done_events(text="planner revise again"),
        mutate_store=apply_plan(
            store,
            run_id,
            base_revision=1,
            operations=[
                {
                    "op": "update_item",
                    "item_id": "item-api",
                    "patch": {
                        "acceptance": [
                            "API behavior is verifiable.",
                            "Health check exists.",
                            "Load test added.",
                        ]
                    },
                }
            ],
            phase=WHOLE_PLAN_REVIEW,
        ),
    )
    provider.script_turn(done_events(text="verification delivery again"))

    result = WholePlanReviewOrchestrator(store, run_id, provider).run()
    assert result.ok is False
    assert store.load_run(run_id)["stop"]["code"] == "limit_exhausted"

    review = store.load_review(run_id, "review-whole-plan-01")
    assert review["lifecycle_status"] == "verification_pending"
    assert review["active_stage"] == "finding_verification"
    assert review["revision_cycles"] == 2
