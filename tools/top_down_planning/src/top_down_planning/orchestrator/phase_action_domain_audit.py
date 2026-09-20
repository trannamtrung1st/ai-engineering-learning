"""Audit events that prove a phase action crossed its durable domain boundary."""

from __future__ import annotations

from top_down_planning.orchestrator.producer_session import (
    PRODUCER_BATCH_COMPLETE_SIGNAL,
    PRODUCER_COMPLETION_COMPLETE_SIGNAL,
    PRODUCER_FOCUSED_REVIEW_REQUESTED_SIGNAL,
)
from top_down_planning.orchestrator.reviewer_session import (
    OWNER_FINDING_ACTION_COMPLETE_SIGNAL,
    REVIEWER_DECISION_COMPLETE_SIGNAL,
)
from top_down_planning.persistence.interface import RunStore

PHASE_ACTION_DOMAIN_BOUNDARY_EVENTS: frozenset[str] = frozenset(
    {
        "production_batch_recorded",
        "production_completion_claimed",
        "focused_review_requested",
        "review_finding_action_recorded",
        "review_challenge_submitted",
        "review_responded",
    }
)

_BOUNDARY_EVENT_SIGNALS: dict[str, str] = {
    "production_batch_recorded": PRODUCER_BATCH_COMPLETE_SIGNAL,
    "production_completion_claimed": PRODUCER_COMPLETION_COMPLETE_SIGNAL,
    "focused_review_requested": PRODUCER_FOCUSED_REVIEW_REQUESTED_SIGNAL,
    "review_finding_action_recorded": OWNER_FINDING_ACTION_COMPLETE_SIGNAL,
    "review_challenge_submitted": OWNER_FINDING_ACTION_COMPLETE_SIGNAL,
    "review_responded": REVIEWER_DECISION_COMPLETE_SIGNAL,
}


def phase_action_domain_proven_by_audit(
    store: RunStore,
    run_id: str,
    phase_action_id: str,
) -> bool:
    from top_down_planning.domain.session_recovery_state import (
        domain_budget_committed_for_phase_action,
    )

    run = store.load_run(run_id)
    if domain_budget_committed_for_phase_action(run, phase_action_id):
        return True
    action = str(phase_action_id).strip()
    if not action:
        return False
    for event in store.load_events(run_id):
        if event.get("type") not in PHASE_ACTION_DOMAIN_BOUNDARY_EVENTS:
            continue
        if str(event.get("phase_action_id") or "").strip() == action:
            return True
    return False


def phase_action_domain_boundary_signal(
    store: RunStore,
    run_id: str,
    phase_action_id: str,
) -> str | None:
    """Return the turn boundary signal implied by a proven domain audit event."""

    action = str(phase_action_id).strip()
    if not action:
        return None
    for event in reversed(store.load_events(run_id)):
        if event.get("type") not in PHASE_ACTION_DOMAIN_BOUNDARY_EVENTS:
            continue
        if str(event.get("phase_action_id") or "").strip() != action:
            continue
        return _BOUNDARY_EVENT_SIGNALS.get(str(event.get("type") or ""))
    return None


__all__ = [
    "PHASE_ACTION_DOMAIN_BOUNDARY_EVENTS",
    "phase_action_domain_boundary_signal",
    "phase_action_domain_proven_by_audit",
]
