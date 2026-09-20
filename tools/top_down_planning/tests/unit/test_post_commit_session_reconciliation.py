"""Reconcile phase actions when provider session sync fails after domain commit."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from core_tools.provider.errors import ProviderSessionMismatchError
from top_down_planning.domain.session_recovery_state import (
    domain_budget_committed_for_phase_action,
)
from top_down_planning.orchestrator.phases import PRODUCTION
from top_down_planning.orchestrator.provider_turns import (
    build_producer_turn_recovery,
    consume_producer_provider_turn_with_session_recovery,
    ensure_phase_action_id,
    production_batch_count,
)
from top_down_planning.orchestrator.session_events import sync_persisted_session_id
from top_down_planning.orchestrator.session_recovery_enforcement import (
    phase_action_domain_proven_by_audit,
)
from top_down_planning.persistence import FileRunStore
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
    run_after = store.load_run(run_id)
    assert run_after.get("phase_action_id") is None
    assert domain_budget_committed_for_phase_action(run_after, phase_action_id)
    assert production_batch_count(store, run_id) == batches_before + 1
    assert int(store.load_production(run_id)["output_revision"]) == output_revision_before + 1

    batches_after_first = production_batch_count(store, run_id)
    provider.script_turn(done_events(text="next turn bookkeeping"))
    provider.resume_primary_session(
        producer_session,
        {"action": "continue", "phase": PRODUCTION},
        role="producer",
    )
    consume_producer_provider_turn_with_session_recovery(
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
    assert production_batch_count(store, run_id) == batches_after_first
