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
    consume_planner_provider_turn_with_session_recovery,
    consume_producer_provider_turn_with_session_recovery,
    consume_reviewer_provider_turn_with_session_recovery,
    build_planner_turn_recovery,
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
from top_down_planning.orchestrator.planner_session import (
    PLANNER_FOCUSED_REVIEW_REQUESTED_SIGNAL,
)
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
    reviewer_sync_failure_after_domain_commit,
    sync_failure_after_domain_commit,
)
from tests.support.whole_output_review import create_run_at_whole_output_review
from core_tools.provider import StubProvider
from core_tools.provider.errors import ProviderSessionMismatchError


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
    run = store.load_run(run_id)
    instance_before = get_primary_binding(run, "producer").session_instance_id
    generation_before = get_primary_binding(run, "producer").generation
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
    assert run_after.get("phase_action_id") is None
    assert run_after.get("session_replacement_phase_action_id") is None
    assert domain_budget_committed_for_phase_action(run_after, phase_action_id)
    binding_after = get_primary_binding(run_after, "producer")
    assert binding_after is not None
    assert binding_after.provider_session_id == outcome.session_id
    assert binding_after.generation > generation_before
    assert binding_after.session_instance_id != instance_before
    assert binding_after.provider_session_id != producer_session
    finding_action_events = [
        event
        for event in store.load_events(run_id)
        if event.get("type") == "review_finding_action_recorded"
    ]
    assert len(finding_action_events) == 1
    assert finding_action_events[0].get("phase_action_id") == phase_action_id


def test_reviewer_turn_reconciles_terminal_respond_when_session_sync_mismatches(
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
        "top_down_planning.orchestrator.provider_turns.sync_reviewer_loop_session_id",
        side_effect=reviewer_sync_failure_after_domain_commit(
            store,
            run_id,
            loop_id,
            phase_action_id,
        ),
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


def test_planner_turn_reconciles_after_focused_plan_request_when_session_sync_mismatches(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010307-010307"
    provider = StubProvider()
    create_planning_run(store, run_id=run_id)
    from tests.helpers import bind_primary_session_for_tests

    provider.script_turn(done_events(text="planner bootstrap"))
    planner_session = provider.start_primary_session(
        "planner",
        {"run_id": run_id, "phase": PLANNING},
    )
    list(provider.stream_events(planner_session))
    run = store.load_run(run_id)
    config = store.load_resolved_config(run_id)
    run = dict(run)
    run["revision"] = int(run["revision"]) + 1
    run["sessions"] = bind_primary_session_for_tests(
        run["sessions"],
        role="planner",
        provider_session_id=planner_session,
        config=config,
        workspace=store.root,
    )
    store.save_run(run_id, run, int(run["revision"]) - 1)
    phase_action_id = ensure_phase_action_id(store, run_id)
    requests_before = focused_review_request_count(store, run_id)

    def _request_focused_plan_review() -> None:
        request_focused_review(
            store,
            run_id,
            {
                "type": "focused_plan",
                "scope": {"item_ids": ["item-api"]},
            },
            role="planner",
            phase=PLANNING,
        )()

    provider.script_turn(
        done_events(text="focused plan review request"),
        mutate_store=_request_focused_plan_review,
    )
    provider.script_turn(done_events(text="replacement session bootstrap"))
    provider.resume_primary_session(
        planner_session,
        {"action": "continue", "phase": PLANNING},
        role="planner",
    )

    with patch(
        "top_down_planning.orchestrator.provider_turns.sync_persisted_session_id",
        side_effect=sync_failure_after_domain_commit(store, run_id, phase_action_id),
    ):
        outcome = consume_planner_provider_turn_with_session_recovery(
            store,
            run_id,
            provider,
            planner_session,
            recovery=build_planner_turn_recovery(
                store,
                run_id,
                phase=PLANNING,
                expected_next_action="continue planning",
                append_event=lambda *_args, **_kwargs: None,
                model=None,
            ),
        )

    assert outcome.signal == PLANNER_FOCUSED_REVIEW_REQUESTED_SIGNAL
    assert outcome.replaced is True
    assert focused_review_request_count(store, run_id) == requests_before + 1
    loop_id = "review-focused-plan-01"
    follow_provider = StubProvider()
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
            ),
            phase=PLANNING,
            loop_id=loop_id,
        ),
    )
    focused_result = FocusedReviewOrchestrator(store, run_id, follow_provider).run(
        loop_id
    )
    assert focused_result.ok is True
    assert focused_review_request_count(store, run_id) == requests_before + 1


def test_reviewer_turn_replaces_session_when_sync_mismatches_after_nonterminal_respond(
    tmp_path: Path,
) -> None:
    from tests.helpers import (
        enter_mandatory_verification_pending,
        mandatory_verification_needs_revision_request,
    )
    from top_down_planning.orchestrator.whole_output_review import (
        build_whole_output_review_package,
    )
    from top_down_planning.orchestrator.reviewer_session import reviewer_loop_binding

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010308-010308"
    loop_id = "review-whole-output-01"
    provider = StubProvider()
    create_run_at_whole_output_review(store, run_id=run_id, provider=provider)
    finding_set_id = "review-whole-output-01-fs-01"
    save_review_payload(
        store,
        run_id,
        {
            **dict(store.load_review(run_id, loop_id)),
            "finding_set_id": finding_set_id,
            "findings": [
                {
                    "id": "finding-01",
                    "severity": "blocker",
                    "category": "correctness",
                    "target_refs": ["item-leaf"],
                    "issue": "Output evidence is missing.",
                    "recommended_change": "Add artifact reference.",
                    "status": "unresolved",
                }
            ],
        },
    )
    enter_mandatory_verification_pending(
        store,
        run_id,
        loop_id,
        target_revision=1,
        finding_set_id=finding_set_id,
    )
    run = store.load_run(run_id)
    config = store.load_resolved_config(run_id)
    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    package = build_whole_output_review_package(
        run_id,
        run,
        config,
        store.load_plan_model(run_id),
        store.load_production(run_id),
        loop,
    )
    provider.script_turn(done_events(text="reviewer bootstrap"))
    session_id, _token = begin_reviewer_review(
        provider,
        store,
        run_id,
        loop_id=loop_id,
        review_package=package,
        phase=WHOLE_OUTPUT_REVIEW,
    )
    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    binding_before = reviewer_loop_binding(loop)
    assert binding_before is not None
    old_reviewer_session = binding_before.provider_session_id
    phase_action_id = ensure_phase_action_id(store, run_id)
    responds_before = review_respond_count(store, run_id, loop_id)

    def _verification_needs_revision() -> None:
        respond_review(
            store,
            run_id,
            mandatory_verification_needs_revision_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=1,
                review_type="whole_output",
                finding_set_id=finding_set_id,
                finding_results=[
                    {
                        "finding_id": "finding-01",
                        "disposition": "unresolved",
                        "evidence": [],
                        "direct_side_effects": [],
                    }
                ],
            ),
            phase=WHOLE_OUTPUT_REVIEW,
            loop_id=loop_id,
        )()

    provider.script_session_turn(
        session_id,
        done_events(text="verification respond"),
        mutate_store=_verification_needs_revision,
    )
    provider.send(session_id, {"prompt": "verification respond", "kind": "user"})
    provider.script_turn(done_events(text="replacement reviewer session bootstrap"))

    with patch(
        "top_down_planning.orchestrator.provider_turns.sync_reviewer_loop_session_id",
        side_effect=reviewer_sync_failure_after_domain_commit(
            store,
            run_id,
            loop_id,
            phase_action_id,
        ),
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
                phase=WHOLE_OUTPUT_REVIEW,
                expected_next_action="continue reviewer turn",
                append_event=lambda *_args, **_kwargs: None,
                model=None,
                review_package=package,
            ),
        )

    assert review_respond_count(store, run_id, loop_id) == responds_before + 1
    assert outcome.replaced is True
    assert outcome.session_id != old_reviewer_session
    loop_after = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    binding_after = reviewer_loop_binding(loop_after)
    assert binding_after is not None
    assert binding_after.provider_session_id == outcome.session_id
    assert binding_after.generation > binding_before.generation
    assert loop_after.lifecycle_status == "verification_pending"
    assert str(loop_after.status) == "needs_revision"
    from top_down_planning.orchestrator.provider_turns import (
        reviewer_needs_further_provider_turns_after_respond,
    )

    assert reviewer_needs_further_provider_turns_after_respond(store, run_id, loop_id) is True
    assert any(
        event.get("type") == "session_replaced"
        for event in store.load_events(run_id)
    )


def test_mandatory_whole_output_driver_recovers_after_nonterminal_reviewer_mismatch(
    tmp_path: Path,
) -> None:
    from tests.helpers import (
        mandatory_initial_respond_request,
        mandatory_scope_review_respond_request,
        prepare_loop_for_scope_review_respond,
    )
    from top_down_planning.orchestrator.mandatory_whole_review import ReviewLoopDriver
    from top_down_planning.orchestrator.whole_output_review import (
        OutputWholeReviewAdapter,
    )

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T010309-010309"
    loop_id = "review-whole-output-01"
    provider = StubProvider()
    create_run_at_whole_output_review(store, run_id=run_id, provider=provider)
    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    target_revision = int(loop.target_revision)
    from top_down_planning.orchestrator.reviewer_session import reviewer_loop_binding

    binding_before = reviewer_loop_binding(loop)
    old_sessions: list[str] = []

    def _initial_review_respond() -> None:
        loop_payload = store.load_review(run_id, loop_id)
        binding = reviewer_loop_binding(ReviewLoop.from_dict(loop_payload))
        if binding and binding.provider_session_id:
            old_sessions.append(binding.provider_session_id)
        respond_review(
            store,
            run_id,
            mandatory_initial_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=target_revision,
                review_type="whole_output",
            ),
            phase=WHOLE_OUTPUT_REVIEW,
            loop_id=loop_id,
        )()
        prepare_loop_for_scope_review_respond(
            store,
            run_id,
            loop_id,
            target_revision=target_revision,
        )

    def _scope_review_respond() -> None:
        respond_review(
            store,
            run_id,
            mandatory_scope_review_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=target_revision,
                review_type="whole_output",
            ),
            phase=WHOLE_OUTPUT_REVIEW,
            loop_id=loop_id,
        )()

    provider.script_turn(done_events(text="reviewer bootstrap"))
    provider.script_turn(
        done_events(text="initial review respond"),
        mutate_store=_initial_review_respond,
    )
    provider.script_turn(done_events(text="replacement reviewer session bootstrap"))
    provider.script_turn(done_events(text="scope review delivery"))
    provider.script_turn(
        done_events(text="scope review respond"),
        mutate_store=_scope_review_respond,
    )

    adapter = OutputWholeReviewAdapter(store, run_id)
    driver = ReviewLoopDriver(store, run_id, provider, adapter)
    adapter.bind_driver(driver)

    from top_down_planning.orchestrator.phase_action_domain_audit import (
        phase_action_domain_proven_by_audit,
    )
    from top_down_planning.orchestrator.session_events import sync_reviewer_loop_session_id

    post_commit_sync_failures_remaining = 1

    def _sync_after_active_phase_action(
        bound_provider,
        bound_store,
        bound_run_id,
        bound_loop_id,
        session_id,
    ) -> str:
        nonlocal post_commit_sync_failures_remaining
        run_row = bound_store.load_run(bound_run_id)
        phase_action_id = str(run_row.get("phase_action_id") or "").strip()
        if (
            post_commit_sync_failures_remaining > 0
            and phase_action_id
            and phase_action_domain_proven_by_audit(
                bound_store,
                bound_run_id,
                phase_action_id,
            )
        ):
            post_commit_sync_failures_remaining -= 1
            raise ProviderSessionMismatchError(
                "simulated post-commit session sync failure",
                session_id=session_id,
            )
        return sync_reviewer_loop_session_id(
            bound_provider,
            bound_store,
            bound_run_id,
            bound_loop_id,
            session_id,
        )

    with patch(
        "top_down_planning.orchestrator.provider_turns.sync_reviewer_loop_session_id",
        side_effect=_sync_after_active_phase_action,
    ):
        result = driver.run(loop_id)

    assert result.ok is True
    assert review_respond_count(store, run_id, loop_id) == 2
    loop_after = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    binding_after = reviewer_loop_binding(loop_after)
    assert binding_after is not None
    if binding_before is not None and binding_before.provider_session_id:
        assert binding_after.provider_session_id != binding_before.provider_session_id
    if old_sessions:
        assert binding_after.provider_session_id not in old_sessions
    assert str(loop_after.status) == "approved"
