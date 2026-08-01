"""Derive and execute resume continuation session policy (proposal §9.1, §14)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.domain.session_bindings import (
    PRIMARY_PLANNER_SLOT,
    PRIMARY_PRODUCER_SLOT,
    SessionBinding,
)
from top_down_planning.orchestrator.capability import revoke_capabilities_for_session_binding
from top_down_planning.persistence.interface import RunStore
from top_down_planning.persistence.session_bindings import (
    clear_stale_starting_primary_binding,
    get_primary_binding,
    sessions_for_persistence,
)

_REVIEWER_KEY_PREFIX = "reviewer:"


def _binding_policy_entry(
    binding: SessionBinding | dict[str, Any],
    *,
    action: str,
) -> dict[str, Any]:
    payload = (
        binding.to_dict()
        if isinstance(binding, SessionBinding)
        else SessionBinding.from_dict(binding).to_dict()
    )
    return {
        "session_instance_id": payload["session_instance_id"],
        "generation": int(payload["generation"]),
        "binding_state": payload["state"],
        "action": action,
    }


def derive_session_policy(
    run: dict[str, Any],
    reviews: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build session_policy from structured bindings (prepare_resume / --check)."""

    bindings: dict[str, Any] = {}

    for slot_key, role in (
        (PRIMARY_PLANNER_SLOT, "planner"),
        (PRIMARY_PRODUCER_SLOT, "producer"),
    ):
        binding = get_primary_binding(run, role)
        if binding is not None and binding.state == "starting":
            bindings[slot_key] = _binding_policy_entry(
                binding,
                action="clear_stale_starting",
            )

    for review in reviews:
        loop_id = str(review.get("id") or "").strip()
        if not loop_id:
            continue
        loop = ReviewLoop.from_dict(review)
        binding = loop.reviewer_binding
        if binding is None:
            continue
        if binding.state == "starting":
            bindings[f"{_REVIEWER_KEY_PREFIX}{loop_id}"] = _binding_policy_entry(
                binding,
                action="clear_stale_starting",
            )

    if not bindings:
        return {"requires_correction": False, "bindings": {}}
    return {"requires_correction": True, "bindings": bindings}


def execute_session_policy(
    store: RunStore,
    run_id: str,
    session_policy: dict[str, Any],
) -> None:
    """Apply continuation-path session corrections after apply_resume_plan_atomically."""

    if session_policy.get("status") == "deferred_until_phase_4":
        return
    if not session_policy.get("requires_correction"):
        return

    run = store.load_run(run_id)
    sessions = dict(run.get("sessions") or {})
    sessions_changed = False

    for key, entry in dict(session_policy.get("bindings") or {}).items():
        if entry.get("action") != "clear_stale_starting":
            continue
        if key == PRIMARY_PLANNER_SLOT:
            if _clear_stale_starting_primary(store, run_id, sessions, role="planner"):
                sessions_changed = True
        elif key == PRIMARY_PRODUCER_SLOT:
            if _clear_stale_starting_primary(store, run_id, sessions, role="producer"):
                sessions_changed = True
        elif str(key).startswith(_REVIEWER_KEY_PREFIX):
            loop_id = str(key)[len(_REVIEWER_KEY_PREFIX) :]
            _clear_stale_starting_reviewer(store, run_id, loop_id)

    if sessions_changed:
        run = store.load_run(run_id)
        expected_revision = int(run["revision"])
        run = dict(run)
        run["revision"] = expected_revision + 1
        run["sessions"] = sessions_for_persistence(sessions)
        store.save_run(run_id, run, expected_revision)


def _clear_stale_starting_primary(
    store: RunStore,
    run_id: str,
    sessions: dict[str, Any],
    *,
    role: str,
) -> bool:
    run = store.load_run(run_id)
    binding = get_primary_binding(run, role)
    if binding is None or binding.state != "starting":
        return False
    revoke_capabilities_for_session_binding(
        store,
        run_id,
        session_instance_id=binding.session_instance_id,
        generation=binding.generation + 1,
    )
    updated_sessions = clear_stale_starting_primary_binding(sessions, role=role)
    sessions.clear()
    sessions.update(updated_sessions)
    return True


def _clear_stale_starting_reviewer(
    store: RunStore,
    run_id: str,
    loop_id: str,
) -> None:
    review = dict(store.load_review(run_id, loop_id))
    loop = ReviewLoop.from_dict(review)
    binding = loop.reviewer_binding
    if binding is None or binding.state != "starting":
        return
    revoke_capabilities_for_session_binding(
        store,
        run_id,
        session_instance_id=binding.session_instance_id,
        generation=binding.generation + 1,
    )
    updated_loop = replace(
        loop,
        reviewer_binding=binding.with_next_generation(),
        reviewer_session_id=None,
    )
    store.save_review(run_id, updated_loop.to_dict())


from top_down_planning.orchestrator.session_policy import register_session_policy_executor

register_session_policy_executor(execute_session_policy)

__all__ = [
    "derive_session_policy",
    "execute_session_policy",
]
