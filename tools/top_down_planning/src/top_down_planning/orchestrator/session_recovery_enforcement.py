"""Session recovery enforcement helpers (proposal §13, §18.2; item 1.5.3)."""

from __future__ import annotations

from typing import Any

from top_down_planning.domain.run_lifecycle import StopRecord
from top_down_planning.domain.session_recovery_state import (
    domain_budget_committed_for_phase_action,
    replacement_attempted_for_phase_action,
)
from top_down_planning.orchestrator.errors import SessionRecoveryExhausted
from top_down_planning.orchestrator.run_transitions import fail_run
from top_down_planning.orchestrator.session_lineage import emit_session_replacement_failed
from top_down_planning.persistence.interface import RunStore
from top_down_planning.persistence.session_bindings import get_primary_binding


def record_session_replacement_attempt(
    store: RunStore,
    run_id: str,
    phase_action_id: str,
) -> dict[str, Any]:
    """Persist replacement attempt for the current logical phase action (§13.3)."""

    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    updated = dict(run)
    updated["revision"] = expected_revision + 1
    updated["session_replacement_phase_action_id"] = str(phase_action_id).strip()
    store.save_run(run_id, updated, expected_revision)
    store.append_event(
        run_id,
        {
            "type": "session_replacement_recorded",
            "run_id": run_id,
            "phase_action_id": str(phase_action_id).strip(),
        },
    )
    return store.load_run(run_id)


def record_phase_action_domain_commit(
    store: RunStore,
    run_id: str,
    phase_action_id: str,
) -> bool:
    """Record domain budget commit for a phase action once (§18.2 boundary 4)."""

    run = store.load_run(run_id)
    if domain_budget_committed_for_phase_action(run, phase_action_id):
        return False

    expected_revision = int(run["revision"])
    updated = dict(run)
    updated["revision"] = expected_revision + 1
    updated["phase_action_domain_committed_id"] = str(phase_action_id).strip()
    store.save_run(run_id, updated, expected_revision)
    store.append_event(
        run_id,
        {
            "type": "phase_action_domain_committed",
            "run_id": run_id,
            "phase_action_id": str(phase_action_id).strip(),
        },
    )
    return True


def clear_phase_action_recovery_state(store: RunStore, run_id: str) -> None:
    """Clear active phase-action and replacement markers after a turn completes."""

    run = store.load_run(run_id)
    if (
        run.get("phase_action_id") is None
        and run.get("session_replacement_phase_action_id") is None
    ):
        return

    expected_revision = int(run["revision"])
    updated = dict(run)
    updated["revision"] = expected_revision + 1
    updated["phase_action_id"] = None
    updated["session_replacement_phase_action_id"] = None
    store.save_run(run_id, updated, expected_revision)


def assert_replacement_allowed(
    store: RunStore,
    run_id: str,
    *,
    phase_action_id: str,
    phase: str,
    role: str,
    provider_session_id: str,
    loop_id: str | None = None,
) -> None:
    """Refuse a second replacement for the same logical phase action (§13.3, test 33)."""

    run = store.load_run(run_id)
    if not replacement_attempted_for_phase_action(run, phase_action_id):
        return

    _emit_replacement_exhausted(
        store,
        run_id,
        phase=phase,
        role=role,
        provider_session_id=provider_session_id,
        phase_action_id=phase_action_id,
        loop_id=loop_id,
        reason="replacement_already_attempted_for_phase_action",
    )
    fail_session_recovery_exhausted(
        store,
        run_id,
        phase=phase,
        role=role,
        phase_action_id=phase_action_id,
        message=(
            "provider session recovery failed after the allowed replacement "
            f"attempt for phase_action_id {phase_action_id}"
        ),
        loop_id=loop_id,
    )


def mark_replacement_attempt(
    store: RunStore,
    run_id: str,
    phase_action_id: str,
) -> None:
    """Persist the replacement attempt before mutating session bindings."""

    record_session_replacement_attempt(store, run_id, phase_action_id)


def finalize_successful_phase_action_turn(
    store: RunStore,
    run_id: str,
    phase_action_id: str,
) -> bool:
    """Commit domain budget once and clear phase-action recovery markers."""

    committed = record_phase_action_domain_commit(store, run_id, phase_action_id)
    clear_phase_action_recovery_state(store, run_id)
    return committed


def domain_budget_should_apply(store: RunStore, run_id: str, phase_action_id: str) -> bool:
    """Return whether orchestrators should apply domain counters for this action."""

    run = store.load_run(run_id)
    return not domain_budget_committed_for_phase_action(run, phase_action_id)


def fail_session_recovery_exhausted(
    store: RunStore,
    run_id: str,
    *,
    phase: str,
    role: str,
    phase_action_id: str,
    message: str,
    loop_id: str | None = None,
) -> None:
    """Mark the run failed with session_recovery_exhausted (§12.3, test 34)."""

    stop = StopRecord(
        code="session_recovery_exhausted",
        category="invariant",
        phase=phase,
        role=role,
        message=message,
        details={
            "phase_action_id": phase_action_id,
            **({"loop_id": loop_id} if loop_id is not None else {}),
        },
    )
    fail_run(
        store,
        run_id,
        stop=stop,
        phase_action_id=phase_action_id,
        loop_id=loop_id,
    )
    raise SessionRecoveryExhausted(message)


def _emit_replacement_exhausted(
    store: RunStore,
    run_id: str,
    *,
    phase: str,
    role: str,
    provider_session_id: str,
    phase_action_id: str,
    reason: str,
    loop_id: str | None = None,
) -> None:
    run = store.load_run(run_id)
    if role == "reviewer" and loop_id is not None:
        from top_down_planning.domain.reviews import ReviewLoop

        loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
        binding = loop.reviewer_binding
        if binding is None:
            return
        emit_session_replacement_failed(
            store,
            run_id,
            phase=phase,
            role=role,
            session_instance_id=binding.session_instance_id,
            generation=binding.generation,
            reason=reason,
            provider_session_id=provider_session_id,
            phase_action_id=phase_action_id,
            loop_id=loop_id,
        )
        return

    binding = get_primary_binding(run, role)
    if binding is None:
        return
    emit_session_replacement_failed(
        store,
        run_id,
        phase=phase,
        role=role,
        session_instance_id=binding.session_instance_id,
        generation=binding.generation,
        reason=reason,
        provider_session_id=provider_session_id,
        phase_action_id=phase_action_id,
        loop_id=loop_id,
    )


__all__ = [
    "assert_replacement_allowed",
    "clear_phase_action_recovery_state",
    "domain_budget_should_apply",
    "fail_session_recovery_exhausted",
    "finalize_successful_phase_action_turn",
    "mark_replacement_attempt",
    "record_phase_action_domain_commit",
    "record_session_replacement_attempt",
]
