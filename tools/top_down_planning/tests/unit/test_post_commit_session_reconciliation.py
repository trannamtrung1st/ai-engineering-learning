"""Reconcile phase actions when provider session sync fails after domain commit."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from core_tools.provider.errors import ProviderSessionMismatchError
from top_down_planning.domain.session_lineage import SESSION_REPLACEMENT_STARTED
from top_down_planning.domain.session_recovery_state import (
    domain_budget_committed_for_phase_action,
)
from top_down_planning.orchestrator.phase_action_domain_audit import (
    phase_action_domain_proven_by_audit,
)
from top_down_planning.orchestrator.phases import PRODUCTION
from top_down_planning.orchestrator.phases import WHOLE_OUTPUT_REVIEW
from top_down_planning.orchestrator.production import ProductionPhaseOrchestrator
from top_down_planning.orchestrator.producer_session import (
    PRODUCER_BATCH_COMPLETE_SIGNAL,
    PRODUCER_COMPLETION_COMPLETE_SIGNAL,
)
from top_down_planning.orchestrator.provider_turns import (
    build_producer_turn_recovery,
    consume_producer_provider_turn_with_session_recovery,
    ensure_phase_action_id,
    production_batch_count,
    production_completion_claim_count,
)
from top_down_planning.orchestrator.session_events import sync_persisted_session_id
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.session_bindings import get_primary_binding
from tests.helpers import apply_production, done_events
from tests.support.focused_review import create_production_run_open_item_second
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

    def _sync_with_post_commit_failure(
        bound_provider,
        bound_store,
        bound_run_id,
        session_id,
        *,
        role: str,
    ) -> str:
        if phase_action_domain_proven_by_audit(bound_store, bound_run_id, phase_action_id):
            raise ProviderSessionMismatchError(
                "simulated post-commit session sync failure",
                session_id=session_id,
            )
        return sync_persisted_session_id(
            bound_provider,
            bound_store,
            bound_run_id,
            session_id,
            role=role,
        )

    with patch(
        "top_down_planning.orchestrator.provider_turns.sync_persisted_session_id",
        side_effect=_sync_with_post_commit_failure,
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

    def _sync_with_post_commit_failure(
        bound_provider,
        bound_store,
        bound_run_id,
        session_id,
        *,
        role: str,
    ) -> str:
        if phase_action_domain_proven_by_audit(bound_store, bound_run_id, phase_action_id):
            raise ProviderSessionMismatchError(
                "simulated post-commit session sync failure",
                session_id=session_id,
            )
        return sync_persisted_session_id(
            bound_provider,
            bound_store,
            bound_run_id,
            session_id,
            role=role,
        )

    with patch(
        "top_down_planning.orchestrator.provider_turns.sync_persisted_session_id",
        side_effect=_sync_with_post_commit_failure,
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
