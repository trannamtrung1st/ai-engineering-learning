"""Reconcile phase actions when provider session sync fails after domain commit."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from top_down_planning.domain.session_lineage import SESSION_REPLACEMENT_STARTED
from top_down_planning.domain.session_recovery_state import (
    domain_budget_committed_for_phase_action,
)
from top_down_planning.orchestrator.phases import PRODUCTION
from top_down_planning.orchestrator.phases import WHOLE_OUTPUT_REVIEW
from top_down_planning.orchestrator.focused_review import FocusedReviewOrchestrator
from top_down_planning.orchestrator.production import ProductionPhaseOrchestrator
from top_down_planning.orchestrator.producer_session import (
    PRODUCER_BATCH_COMPLETE_SIGNAL,
    PRODUCER_COMPLETION_COMPLETE_SIGNAL,
    PRODUCER_FOCUSED_REVIEW_REQUESTED_SIGNAL,
)
from top_down_planning.orchestrator.provider_turns import (
    build_producer_turn_recovery,
    build_reviewer_turn_recovery,
    consume_owner_finding_action_turn_with_session_recovery,
    consume_producer_provider_turn_with_session_recovery,
    consume_reviewer_provider_turn_with_session_recovery,
    ensure_phase_action_id,
    focused_review_request_count,
    owner_finding_action_count,
    production_batch_count,
    production_completion_claim_count,
    review_respond_count,
)
from top_down_planning.orchestrator.reviewer_session import (
    OWNER_FINDING_ACTION_COMPLETE_SIGNAL,
    REVIEWER_DECISION_COMPLETE_SIGNAL,
    begin_reviewer_review,
)
from top_down_planning.orchestrator.focused_review import build_focused_review_package
from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.session_bindings import get_primary_binding
from tests.helpers import (
    apply_production,
    done_events,
    mandatory_output_digest,
    record_finding_actions,
    request_focused_review,
    respond_review,
    save_review_payload,
)
from tests.support.focused_review import (
    create_planning_run,
    create_production_run_open_item_second,
    review_respond_request,
)
from tests.support.post_commit_session_reconciliation import (
    sync_failure_after_domain_commit,
)
from tests.support.whole_output_review import create_run_at_whole_output_review
from core_tools.provider import StubProvider


def test_producer_turn_reconciles_phase_action_after_batch_when_session_sync_mismatches(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010301-010301"
    provider = StubProvider()
    create_production_run_open_item_second(store, provider, run_id=run_id)
    phase_action_id = ensure_phase_action_id(store, run_id)
    run = store.load_run(run_id)
    producer_session = run["sessions"]["primary_producer"]["provider_session_id"]
    instance_before = get_primary_binding(run, "producer").session_instance_id
    generation_before = get_primary_binding(run, "producer").generation
    batches_before = production_batch_count(store, run_id)
    output_revision_before = int(store.load_production(run_id)["output_revision"])

    def _apply_batch() -> None:
        apply_production(
            store,
            run_id,
            {
                "production_revision": int(store.load_production(run_id)["revision"]),
                "plan_items": ["item-second"],
                "dispositions": {
                    "item-second": {
                        "disposition": "completed",
                        "evidence": "batch",
                    }
                },
                "outputs": [
                    {
                        "id": "output-second-batch",
                        "type": "artifact",
                        "ref": "artifacts/second.txt",
                    }
                ],
                "contributions": [
                    {
                        "item_id": "item-second",
                        "output_refs": ["output-second-batch"],
                        "summary": "batch",
                    }
                ],
                "summary": "batch",
            },
            handler="apply",
        )()

    provider.script_turn(
        done_events(text="producer batch"),
        mutate_store=_apply_batch,
    )
    provider.script_turn(done_events(text="replacement session bootstrap"))
    provider.resume_primary_session(
        producer_session,
        {"action": "continue", "phase": PRODUCTION},
        role="producer",
    )

    with patch(
        "top_down_planning.orchestrator.provider_turns.sync_persisted_session_id",
        side_effect=sync_failure_after_domain_commit(store, run_id, phase_action_id),
    ):
        outcome = consume_producer_provider_turn_with_session_recovery(
            store,
            run_id,
            provider,
            producer_session,
            recovery=build_producer_turn_recovery(
                store,
                run_id,
                phase=PRODUCTION,
                expected_next_action="continue production",
                append_event=lambda *_args, **_kwargs: None,
                model=None,
            ),
        )

    assert outcome.domain_budget_committed is True
    assert outcome.replaced is True
    assert outcome.signal == PRODUCER_BATCH_COMPLETE_SIGNAL
    assert outcome.session_id != producer_session
    run_after = store.load_run(run_id)
    assert run_after.get("phase_action_id") is None
    assert run_after.get("session_replacement_phase_action_id") is None
    assert domain_budget_committed_for_phase_action(run_after, phase_action_id)
    assert production_batch_count(store, run_id) == batches_before + 1
    assert int(store.load_production(run_id)["output_revision"]) == output_revision_before + 1
    binding_after = get_primary_binding(run_after, "producer")
    assert binding_after is not None
    assert binding_after.provider_session_id == outcome.session_id
    assert binding_after.generation > generation_before
    assert binding_after.session_instance_id != instance_before
    replacement_events = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == SESSION_REPLACEMENT_STARTED
    ]
    assert replacement_events

    batches_after_first = production_batch_count(store, run_id)
    safe_session = outcome.session_id
    provider.script_turn(done_events(text="next turn bookkeeping"))
    provider.resume_primary_session(
        safe_session,
        {"action": "continue", "phase": PRODUCTION},
        role="producer",
    )
    follow_up = consume_producer_provider_turn_with_session_recovery(
        store,
        run_id,
        provider,
        safe_session,
        recovery=build_producer_turn_recovery(
            store,
            run_id,
            phase=PRODUCTION,
            expected_next_action="continue production",
            append_event=lambda *_args, **_kwargs: None,
            model=None,
        ),
    )
    assert production_batch_count(store, run_id) == batches_after_first
    assert follow_up.replaced is False


def _complete_open_production_item_second(store: FileRunStore, run_id: str) -> None:
    apply_production(
        store,
        run_id,
        {
            "production_revision": int(store.load_production(run_id)["revision"]),
            "plan_items": ["item-second"],
            "dispositions": {
                "item-second": {
                    "disposition": "completed",
                    "evidence": "ready for completion claim",
                }
            },
            "outputs": [
                {
                    "id": "output-second-ready",
                    "type": "artifact",
                    "ref": "artifacts/second.txt",
                }
            ],
            "contributions": [
                {
                    "item_id": "item-second",
                    "output_refs": ["output-second-ready"],
                    "summary": "Second item complete.",
                }
            ],
            "summary": "Complete item-second.",
        },
        handler="apply",
    )()


def test_producer_turn_reconciles_phase_action_after_completion_when_session_sync_mismatches(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010302-010302"
    provider = StubProvider()
    create_production_run_open_item_second(store, provider, run_id=run_id)
    _complete_open_production_item_second(store, run_id)
    phase_action_id = ensure_phase_action_id(store, run_id)
    run = store.load_run(run_id)
    producer_session = run["sessions"]["primary_producer"]["provider_session_id"]
    instance_before = get_primary_binding(run, "producer").session_instance_id
    generation_before = get_primary_binding(run, "producer").generation
    claims_before = production_completion_claim_count(store, run_id)
    production_revision_before = int(store.load_production(run_id)["revision"])

    def _submit_completion() -> None:
        apply_production(
            store,
            run_id,
            {
                "production_revision": int(store.load_production(run_id)["revision"]),
                "goal_assessment": "Output goal is fully met.",
                "summary": "Submit completion.",
            },
            handler="submit_completion",
        )()

    provider.script_turn(
        done_events(text="producer completion claim"),
        mutate_store=_submit_completion,
    )
    provider.script_turn(done_events(text="replacement session bootstrap"))
    provider.resume_primary_session(
        producer_session,
        {"action": "continue", "phase": PRODUCTION},
        role="producer",
    )

    with patch(
        "top_down_planning.orchestrator.provider_turns.sync_persisted_session_id",
        side_effect=sync_failure_after_domain_commit(store, run_id, phase_action_id),
    ):
        outcome = consume_producer_provider_turn_with_session_recovery(
            store,
            run_id,
            provider,
            producer_session,
            recovery=build_producer_turn_recovery(
                store,
                run_id,
                phase=PRODUCTION,
                expected_next_action="continue production",
                append_event=lambda *_args, **_kwargs: None,
                model=None,
            ),
        )

    completion_events = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == "production_completion_claimed"
    ]
    assert len(completion_events) == 1
    assert completion_events[0].get("phase_action_id") == phase_action_id

    assert outcome.domain_budget_committed is True
    assert outcome.replaced is True
    assert outcome.signal == PRODUCER_COMPLETION_COMPLETE_SIGNAL
    assert outcome.session_id != producer_session
    run_after = store.load_run(run_id)
    assert run_after.get("phase_action_id") is None
    assert run_after.get("session_replacement_phase_action_id") is None
    assert domain_budget_committed_for_phase_action(run_after, phase_action_id)
    assert production_completion_claim_count(store, run_id) == claims_before + 1
    assert int(store.load_production(run_id)["revision"]) == production_revision_before + 1
    binding_after = get_primary_binding(run_after, "producer")
    assert binding_after is not None
    assert binding_after.provider_session_id == outcome.session_id
    assert binding_after.generation > generation_before
    assert binding_after.session_instance_id != instance_before

    claims_after_mismatch = production_completion_claim_count(store, run_id)
    follow_provider = StubProvider()
    safe_session = outcome.session_id
    follow_provider._ensure_durable_session(  # noqa: SLF001 — test harness
        safe_session,
        role="producer",
        kind="primary",
    )
    follow_provider.script_turn(done_events(text="production phase entry bookkeeping"))
    result = ProductionPhaseOrchestrator(store, run_id, follow_provider).run()
    assert result.ok is True
    assert store.load_run(run_id)["phase"] == WHOLE_OUTPUT_REVIEW
    assert production_completion_claim_count(store, run_id) == claims_after_mismatch
    assert store.load_production(run_id).get("completion_claim") is not None


def test_producer_turn_reconciles_phase_action_after_focused_review_request_when_session_sync_mismatches(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010303-010303"
    provider = StubProvider()
    create_production_run_open_item_second(store, provider, run_id=run_id)
    phase_action_id = ensure_phase_action_id(store, run_id)
    run = store.load_run(run_id)
    producer_session = run["sessions"]["primary_producer"]["provider_session_id"]
    requests_before = focused_review_request_count(store, run_id)
    reviews_before = len(store.list_reviews(run_id))

    def _request_focused_output_review() -> None:
        request_focused_review(
            store,
            run_id,
            {
                "type": "focused_output",
                "scope": {"item_ids": ["item-first"]},
            },
            role="producer",
            phase=PRODUCTION,
        )()

    provider.script_turn(
        done_events(text="focused review request"),
        mutate_store=_request_focused_output_review,
    )
    provider.script_turn(done_events(text="replacement session bootstrap"))
    provider.resume_primary_session(
        producer_session,
        {"action": "continue", "phase": PRODUCTION},
        role="producer",
    )

    with patch(
        "top_down_planning.orchestrator.provider_turns.sync_persisted_session_id",
        side_effect=sync_failure_after_domain_commit(store, run_id, phase_action_id),
    ):
        outcome = consume_producer_provider_turn_with_session_recovery(
            store,
            run_id,
            provider,
            producer_session,
            recovery=build_producer_turn_recovery(
                store,
                run_id,
                phase=PRODUCTION,
                expected_next_action="continue production",
                append_event=lambda *_args, **_kwargs: None,
                model=None,
            ),
        )

    request_events = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == "focused_review_requested"
    ]
    assert len(request_events) == 1
    assert request_events[0].get("phase_action_id") == phase_action_id
    assert focused_review_request_count(store, run_id) == requests_before + 1
    assert len(store.list_reviews(run_id)) == reviews_before + 1

    assert outcome.replaced is True
    assert outcome.signal == PRODUCER_FOCUSED_REVIEW_REQUESTED_SIGNAL
    run_after = store.load_run(run_id)
    assert run_after.get("phase_action_id") is None
    assert run_after.get("session_replacement_phase_action_id") is None
    assert domain_budget_committed_for_phase_action(run_after, phase_action_id)

    requests_after = focused_review_request_count(store, run_id)
    loop_id = "review-focused-output-01"
    follow_provider = StubProvider()
    safe_session = outcome.session_id
    follow_provider._ensure_durable_session(  # noqa: SLF001
        safe_session,
        role="producer",
        kind="primary",
    )
    output_revision = int(store.load_production(run_id)["output_revision"])
    follow_provider.script_turn(
        done_events(text="reviewer approve"),
        mutate_store=respond_review(
            store,
            run_id,
            review_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                decision="approved",
                target_revision=output_revision,
            ),
            phase=PRODUCTION,
            loop_id=loop_id,
        ),
    )
    focused_result = FocusedReviewOrchestrator(store, run_id, follow_provider).run(
        loop_id
    )
    assert focused_result.ok is True
    assert focused_review_request_count(store, run_id) == requests_after
    assert store.load_review(run_id, loop_id)["status"] == "approved"


def test_owner_finding_action_turn_reconciles_when_session_sync_mismatches(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010304-010304"
    loop_id = "review-whole-output-01"
    provider = StubProvider()
    producer_session = create_run_at_whole_output_review(
        store,
        run_id=run_id,
        provider=provider,
    )
    assert producer_session is not None
    save_review_payload(
        store,
        run_id,
        {
            **dict(store.load_review(run_id, loop_id)),
            "finding_set_id": "review-whole-output-01-fs-01",
            "findings": [
                {
                    "id": "finding-01",
                    "severity": "minor",
                    "category": "maintainability",
                    "target_refs": ["item-leaf"],
                    "issue": "Optional polish.",
                    "recommended_change": "Improve wording.",
                    "status": "unresolved",
                }
            ],
        },
    )
    phase_action_id = ensure_phase_action_id(store, run_id)
    actions_before = owner_finding_action_count(store, run_id, loop_id)

    def _record_actions() -> None:
        record_finding_actions(
            store,
            run_id,
            {
                "loop_id": loop_id,
                "target_revision": 1,
                "target_digest": mandatory_output_digest(store, run_id),
                "finding_set_id": "review-whole-output-01-fs-01",
                "finding_actions": [
                    {
                        "finding_id": "finding-01",
                        "action": "defer",
                        "actor_role": "producer",
                        "rationale": "Defer polish",
                    }
                ],
            },
            role="producer",
            phase=WHOLE_OUTPUT_REVIEW,
            loop_id=loop_id,
        )()

    provider.script_turn(
        done_events(text="owner record actions"),
        mutate_store=_record_actions,
    )
    provider.script_turn(done_events(text="replacement session bootstrap"))
    provider.resume_primary_session(
        producer_session,
        {"action": "continue", "phase": WHOLE_OUTPUT_REVIEW},
        role="producer",
    )

    with patch(
        "top_down_planning.orchestrator.provider_turns.sync_persisted_session_id",
        side_effect=sync_failure_after_domain_commit(store, run_id, phase_action_id),
    ):
        outcome = consume_owner_finding_action_turn_with_session_recovery(
            store,
            run_id,
            provider,
            producer_session,
            loop_id=loop_id,
            recovery=build_producer_turn_recovery(
                store,
                run_id,
                phase=WHOLE_OUTPUT_REVIEW,
                expected_next_action="record owner finding actions",
                append_event=lambda *_args, **_kwargs: None,
                model=None,
            ),
        )

    assert owner_finding_action_count(store, run_id, loop_id) == actions_before + 1
    assert outcome.replaced is True
    assert outcome.signal == OWNER_FINDING_ACTION_COMPLETE_SIGNAL
    run_after = store.load_run(run_id)
    assert run_after.get("session_replacement_phase_action_id") is None


def test_reviewer_turn_reconciles_when_session_sync_mismatches_without_replacement(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010305-010305"
    loop_id = "review-focused-plan-01"
    from tests.helpers import review_loop_dict_with_binding
    from tests.support.focused_review import review_respond_request as focused_review_respond_request

    create_planning_run(store, run_id=run_id)
    save_review_payload(
        store,
        run_id,
        review_loop_dict_with_binding(
            {
                "id": loop_id,
                "type": "focused_plan",
                "target_revision": 0,
                "scope": {"kind": "focused_plan", "item_ids": ["item-api"]},
                "status": "pending",
                "revise_at": "blocker",
                "revision_cycles": 0,
                "finding_set_id": "fs-01",
                "findings": [],
            }
        ),
    )
    provider = StubProvider()
    run = store.load_run(run_id)
    config = store.load_resolved_config(run_id)
    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    package = build_focused_review_package(
        run_id,
        run,
        config,
        loop,
        plan=store.load_plan_model(run_id),
    )
    provider.script_turn(done_events(text="reviewer bootstrap"))
    session_id, _token = begin_reviewer_review(
        provider,
        store,
        run_id,
        loop_id=loop_id,
        review_package=package,
        phase=PLANNING,
    )
    phase_action_id = ensure_phase_action_id(store, run_id)
    responds_before = review_respond_count(store, run_id, loop_id)

    def _respond_changes_requested() -> None:
        respond_review(
            store,
            run_id,
            focused_review_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                decision="changes_requested",
                findings=[
                    {
                        "id": "finding-01",
                        "severity": "blocker",
                        "category": "correctness",
                        "target_refs": ["item-api"],
                        "issue": "Gap.",
                        "recommended_change": "Fix.",
                        "status": "unresolved",
                    }
                ],
            ),
            phase=PLANNING,
            loop_id=loop_id,
        )()

    provider.script_session_turn(
        session_id,
        done_events(text="reviewer respond"),
        mutate_store=_respond_changes_requested,
    )
    provider.send(session_id, {"prompt": "reviewer respond", "kind": "user"})

    with patch(
        "top_down_planning.orchestrator.provider_turns.sync_persisted_session_id",
        side_effect=sync_failure_after_domain_commit(store, run_id, phase_action_id),
    ):
        outcome = consume_reviewer_provider_turn_with_session_recovery(
            store,
            run_id,
            provider,
            session_id,
            loop_id=loop_id,
            recovery=build_reviewer_turn_recovery(
                store,
                run_id,
                loop_id=loop_id,
                phase=PLANNING,
                expected_next_action="continue reviewer turn",
                append_event=lambda *_args, **_kwargs: None,
                model=None,
                review_package=package,
            ),
        )

    assert review_respond_count(store, run_id, loop_id) == responds_before + 1
    assert outcome.replaced is False
    assert outcome.signal == REVIEWER_DECISION_COMPLETE_SIGNAL
    run_after = store.load_run(run_id)
    assert run_after.get("phase_action_id") is None
    assert domain_budget_committed_for_phase_action(run_after, phase_action_id)
    responded = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == "review_responded"
    ]
    assert len(responded) == 1
    assert responded[0].get("phase_action_id") == phase_action_id
