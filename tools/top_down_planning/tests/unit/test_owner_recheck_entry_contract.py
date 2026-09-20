"""Owner-response contract for entering mandatory/focused verification recheck."""

from __future__ import annotations

from pathlib import Path

import pytest

from core_tools.provider import StubProvider
from core_tools.provider.errors import ProviderTurnError
from top_down_planning.agent_tool import ReviewAgentService
from top_down_planning.orchestrator import WholePlanReviewOrchestrator
from top_down_planning.orchestrator.focused_review import FocusedReviewOrchestrator
from top_down_planning.orchestrator.phases import PLANNING, WHOLE_PLAN_REVIEW
from top_down_planning.orchestrator.provider_turns import owner_revision_complete
from top_down_planning.persistence import FileRunStore
from tests.helpers import (
    apply_plan,
    apply_plan_and_complete_focused_owner_revision,
    apply_plan_and_complete_mandatory_owner_revision,
    done_events,
    grant_capability,
    mandatory_initial_respond_request,
    respond_review,
)
from tests.support.focused_review import (
    create_planning_run,
    focused_plan_request,
    review_respond_request,
)
from tests.support.whole_plan_review import create_run_at_whole_plan_review

_RUN_ID = "run-20260101T000401-000401"
_WHOLE_PLAN_LOOP_ID = "review-whole-plan-01"


def _blocker_finding(*, target_refs: list[str]) -> dict:
    return {
        "id": "finding-01",
        "severity": "blocker",
        "category": "correctness",
        "target_refs": target_refs,
        "issue": "Needs work.",
        "recommended_change": "Improve outcome.",
        "status": "unresolved",
    }


def test_whole_plan_artifact_without_owner_action_does_not_enter_verification_recheck(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    create_run_at_whole_plan_review(store, provider=provider)
    run_id = "run-20260101T000301-000301"

    provider.script_turn(
        done_events(text="reviewer decision"),
        mutate_store=respond_review(
            store,
            run_id,
            mandatory_initial_respond_request(
                store,
                run_id,
                loop_id=_WHOLE_PLAN_LOOP_ID,
                target_revision=0,
                review_type="whole_plan",
                decision="changes_requested",
                findings=[_blocker_finding(target_refs=["item-root"])],
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=_WHOLE_PLAN_LOOP_ID,
        ),
    )
    provider.script_turn(
        done_events(text="planner revision without owner response"),
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

    with pytest.raises(ProviderTurnError):
        WholePlanReviewOrchestrator(store, run_id, provider).run()

    review = store.load_review(run_id, _WHOLE_PLAN_LOOP_ID)
    assert review["target_revision"] == 0
    assert review["lifecycle_status"] != "verification_pending"
    assert owner_revision_complete(store, run_id, _WHOLE_PLAN_LOOP_ID) is False


def test_whole_plan_owner_response_enters_single_verification_recheck(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    create_run_at_whole_plan_review(
        store,
        provider=provider,
        limits={"review": {"max_agent_turns_per_gate": 1}},
    )
    run_id = "run-20260101T000301-000301"

    provider.script_turn(
        done_events(text="reviewer decision"),
        mutate_store=respond_review(
            store,
            run_id,
            mandatory_initial_respond_request(
                store,
                run_id,
                loop_id=_WHOLE_PLAN_LOOP_ID,
                target_revision=0,
                review_type="whole_plan",
                decision="changes_requested",
                findings=[_blocker_finding(target_refs=["item-root"])],
            ),
            phase=WHOLE_PLAN_REVIEW,
            loop_id=_WHOLE_PLAN_LOOP_ID,
        ),
    )
    provider.script_turn(
        done_events(text="planner revision with owner response"),
        mutate_store=apply_plan_and_complete_mandatory_owner_revision(
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
            loop_id=_WHOLE_PLAN_LOOP_ID,
            changed_refs=["item-root"],
        ),
    )
    provider.script_turn(done_events(text="verification recheck delivery"))

    WholePlanReviewOrchestrator(store, run_id, provider).run()

    review = store.load_review(run_id, _WHOLE_PLAN_LOOP_ID)
    assert review["target_revision"] == 1
    assert review["lifecycle_status"] == "verification_pending"
    assert review["active_stage"] == "finding_verification"
    assert owner_revision_complete(store, run_id, _WHOLE_PLAN_LOOP_ID) is True
    recheck_events = [
        event
        for event in store.load_events(run_id)
        if event.get("type") in {"reviewer_session_started", "reviewer_session_resumed"}
        and event.get("stage") == "finding_verification"
    ]
    assert len(recheck_events) == 1


def test_focused_plan_artifact_without_owner_action_does_not_enter_verification_recheck(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    create_planning_run(store, run_id=_RUN_ID)

    created = ReviewAgentService(store, _RUN_ID).request(
        focused_plan_request(["item-api"], store, run_id=_RUN_ID),
        capability_token=grant_capability(store, _RUN_ID, role="planner", phase=PLANNING),
    )
    loop_id = str(created["loop_id"])
    respond_review(
        store,
        _RUN_ID,
        review_respond_request(
            store,
            _RUN_ID,
            loop_id=loop_id,
            decision="changes_requested",
            findings=[_blocker_finding(target_refs=["item-api"])],
        ),
        phase=PLANNING,
        loop_id=loop_id,
    )()
    provider.script_turn(
        done_events(text="planner revision without owner response"),
        mutate_store=apply_plan(
            store,
            _RUN_ID,
            base_revision=0,
            operations=[
                {
                    "op": "update_item",
                    "item_id": "item-api",
                    "patch": {"outcome": "REST API endpoints exist."},
                }
            ],
        ),
    )

    result = FocusedReviewOrchestrator(store, _RUN_ID, provider).run(loop_id)

    assert result.ok is False
    assert "owner revision" in (result.reason or "").lower()

    review = store.load_review(_RUN_ID, loop_id)
    assert review["target_revision"] == 0
    assert review.get("active_stage") != "finding_verification"
    assert owner_revision_complete(store, _RUN_ID, loop_id) is False


def test_focused_plan_owner_response_enters_single_verification_recheck(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    create_planning_run(
        store,
        run_id=_RUN_ID,
        limits={"review": {"max_agent_turns_per_gate": 1}},
    )

    created = ReviewAgentService(store, _RUN_ID).request(
        focused_plan_request(["item-api"], store, run_id=_RUN_ID),
        capability_token=grant_capability(store, _RUN_ID, role="planner", phase=PLANNING),
    )
    loop_id = str(created["loop_id"])
    respond_review(
        store,
        _RUN_ID,
        review_respond_request(
            store,
            _RUN_ID,
            loop_id=loop_id,
            decision="changes_requested",
            findings=[_blocker_finding(target_refs=["item-api"])],
        ),
        phase=PLANNING,
        loop_id=loop_id,
    )()
    apply_plan_and_complete_focused_owner_revision(
        store,
        _RUN_ID,
        base_revision=0,
        operations=[
            {
                "op": "update_item",
                "item_id": "item-api",
                "patch": {
                    "outcome": "REST API endpoints exist.",
                    "acceptance": ["GET /health returns 200."],
                },
            }
        ],
        phase=PLANNING,
        loop_id=loop_id,
    )()
    provider.script_turn(done_events(text="verification recheck delivery"))

    FocusedReviewOrchestrator(store, _RUN_ID, provider).run(loop_id)

    review = store.load_review(_RUN_ID, loop_id)
    assert review["target_revision"] == 1
    assert review["active_stage"] == "finding_verification"
    assert review["status"] == "pending"
    assert owner_revision_complete(store, _RUN_ID, loop_id) is True
