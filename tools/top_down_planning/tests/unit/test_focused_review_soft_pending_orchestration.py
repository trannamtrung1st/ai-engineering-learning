"""Focused review recoverable incomplete must not resume primary planner/producer turns."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from core_tools.provider import StubProvider
from top_down_planning.agent_tool import ReviewAgentService
from top_down_planning.domain.reviews import ReviewLoop, mark_advisory_handoff_incomplete
from top_down_planning.domain.session_bindings import new_session_binding
from top_down_planning.orchestrator import PlanningPhaseOrchestrator, ProductionPhaseOrchestrator
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.orchestrator.provider_turns import (
    FocusedReviewRunOutcome,
    run_pending_focused_review,
)
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.digests import compute_plan_digest
from top_down_planning.persistence.session_bindings import primary_provider_session_id
from tests.helpers import (
    apply_plan,
    done_events,
    grant_capability,
    review_loop_dict_with_binding,
    save_review_payload,
    with_root_contract,
)
from tests.support.focused_review import (
    create_planning_run,
    create_production_run_open_item_second,
)


def _advisory_optional_focused_output_loop(*, item_ids: list[str]) -> dict:
    binding = new_session_binding(
        role="reviewer",
        kind="reviewer",
    ).with_provider_session_id("reviewer-sess-advisory")
    loop = review_loop_dict_with_binding(
        {
            "id": "review-focused-output-01",
            "type": "focused_output",
            "target_revision": 1,
            "scope": {"kind": "focused_output", "item_ids": item_ids},
            "status": "advisory_pending",
            "revise_at": "blocker",
            "revision_cycles": 0,
            "finding_set_id": "fs-advisory-01",
            "findings": [
                {
                    "id": "finding-opt",
                    "severity": "minor",
                    "category": "correctness",
                    "target_refs": item_ids[:1],
                    "issue": "Optional polish.",
                    "recommended_change": "Improve wording.",
                    "status": "unresolved",
                }
            ],
            "finding_actions": [],
        }
    )
    loop["reviewer_binding"] = binding.to_dict()
    return loop


def _focused_plan_incomplete_loop(*, target_revision: int = 0) -> ReviewLoop:
    payload = review_loop_dict_with_binding(
        {
            "id": "review-focused-plan-01",
            "type": "focused_plan",
            "reviewer_session_id": "reviewer-sess",
            "target_revision": target_revision,
            "scope": {"kind": "focused_plan", "item_ids": ["item-root"]},
            "status": "advisory_pending",
            "revise_at": "blocker",
            "finding_set_id": "fs-01",
            "revision_cycles": 0,
            "findings": [
                {
                    "id": "finding-opt",
                    "severity": "minor",
                    "category": "correctness",
                    "target_refs": ["item-root"],
                    "issue": "Optional gap",
                    "recommended_change": "Fix",
                    "status": "unresolved",
                }
            ],
            "finding_actions": [],
        }
    )
    loop = ReviewLoop.from_dict(payload)
    return mark_advisory_handoff_incomplete(loop, missing_finding_ids=["finding-opt"])


def test_run_pending_focused_review_returns_review_incomplete_outcome(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000601-000601"
    loop_id = "review-focused-output-01"
    create_production_run_open_item_second(store, provider, run_id=run_id)
    loop = ReviewLoop.from_dict(_advisory_optional_focused_output_loop(item_ids=["item-first"]))
    incomplete = mark_advisory_handoff_incomplete(
        loop,
        missing_finding_ids=["finding-opt"],
    )
    save_review_payload(store, run_id, incomplete.to_dict())

    provider.script_turn(done_events(text="advisory retry without owner action"))

    outcome = run_pending_focused_review(
        store,
        run_id,
        provider,
        review_type="focused_output",
    )
    assert outcome == FocusedReviewRunOutcome.REVIEW_INCOMPLETE
    assert store.load_review(run_id, loop_id)["status"] == "review_incomplete"


def test_planning_phase_review_incomplete_does_not_consume_planner_turn(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000602-000602"
    create_planning_run(store, run_id)
    save_review_payload(
        store,
        run_id,
        _focused_plan_incomplete_loop().to_dict(),
    )

    provider.script_turn(done_events(text="planner primary session start"))
    provider.script_turn(done_events(text="planner owner advisory session start"))
    provider.script_turn(done_events(text="focused plan advisory retry still incomplete"))

    with patch(
        "top_down_planning.orchestrator.planning.consume_provider_turn_with_session_recovery",
    ) as consume_mock:
        result = PlanningPhaseOrchestrator(store, run_id, provider).run()

    consume_mock.assert_not_called()
    assert result.ok is False
    run = store.load_run(run_id)
    assert run["status"] == "running"
    assert store.load_plan_model(run_id).revision == 0


def test_planning_phase_review_incomplete_then_defer_approves_and_resumes_planning(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000603-000603"
    loop_id = "review-focused-plan-01"
    create_planning_run(store, run_id)
    save_review_payload(
        store,
        run_id,
        _focused_plan_incomplete_loop().to_dict(),
    )

    provider.script_turn(done_events(text="planner primary session start"))
    provider.script_turn(done_events(text="planner owner advisory session start"))
    provider.script_turn(done_events(text="focused plan advisory retry still incomplete"))

    first = PlanningPhaseOrchestrator(store, run_id, provider).run()
    assert first.ok is False
    assert store.load_plan_model(run_id).revision == 0
    assert store.load_review(run_id, loop_id)["status"] == "review_incomplete"

    from top_down_planning.domain.reviews import prepare_review_incomplete_retry

    def _planner_defers() -> None:
        loop_payload = store.load_review(run_id, loop_id)
        token = grant_capability(
            store,
            run_id,
            role="planner",
            phase=PLANNING,
            session_id=str(
                primary_provider_session_id(store.load_run(run_id), "planner") or ""
            ),
        )
        ReviewAgentService(store, run_id).record_finding_actions(
            {
                "loop_id": loop_id,
                "target_revision": int(store.load_plan_model(run_id).revision),
                "target_digest": compute_plan_digest(store.load_plan_model(run_id)),
                "finding_set_id": str(loop_payload.get("finding_set_id") or ""),
                "finding_actions": [
                    {
                        "finding_id": "finding-opt",
                        "action": "defer",
                        "actor_role": "planner",
                        "rationale": "Accept risk for now.",
                    }
                ],
            },
            capability_token=token,
        )

    retried = prepare_review_incomplete_retry(
        ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    )
    save_review_payload(store, run_id, retried.to_dict())
    _planner_defers()
    assert store.load_review(run_id, loop_id)["status"] == "approved"

    apply_plan(
        store,
        run_id,
        base_revision=0,
        operations=with_root_contract(
            [
                {
                    "op": "add_item",
                    "temp_id": "item-ui",
                    "parent_id": "item-root",
                    "placement": {"last_child": True},
                    "item": {
                        "kind": "work",
                        "title": "UI",
                        "outcome": "UI exists.",
                    },
                },
            ]
        ),
    )()
    assert store.load_plan_model(run_id).revision == 1


def test_production_phase_review_incomplete_does_not_consume_producer_turn(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    run_id = "run-20260101T000604-000604"
    loop_id = "review-focused-output-01"
    create_production_run_open_item_second(store, provider, run_id=run_id)
    loop = ReviewLoop.from_dict(_advisory_optional_focused_output_loop(item_ids=["item-first"]))
    incomplete = mark_advisory_handoff_incomplete(
        loop,
        missing_finding_ids=["finding-opt"],
    )
    save_review_payload(store, run_id, incomplete.to_dict())
    production_revision_before = int(store.load_production(run_id)["revision"])

    provider.script_turn(done_events(text="producer owner advisory session start"))
    provider.script_turn(done_events(text="focused output advisory retry"))

    with patch(
        "top_down_planning.orchestrator.production.consume_producer_provider_turn_with_session_recovery",
    ) as consume_mock:
        result = ProductionPhaseOrchestrator(store, run_id, provider).run()

    consume_mock.assert_not_called()
    assert result.ok is False
    run = store.load_run(run_id)
    assert run["status"] == "running"
    assert store.load_review(run_id, loop_id)["status"] == "review_incomplete"
    assert int(store.load_production(run_id)["revision"]) == production_revision_before
