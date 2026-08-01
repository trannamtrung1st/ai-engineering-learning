"""Derive and execute resume continuation session policy."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.domain.session_bindings import (
    PRIMARY_PLANNER_SLOT,
    PRIMARY_PRODUCER_SLOT,
    SessionBinding,
)
from top_down_planning.orchestrator.capability import (
    revoke_all_capabilities_for_session_instance,
)
from top_down_planning.persistence.interface import RunStore
from top_down_planning.persistence.review_commit import (
    review_record_revision,
    save_review_with_expected_revision,
)
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
        "provider_session_id": payload.get("provider_session_id"),
        "action": action,
    }


def _is_stale_starting_binding(binding: SessionBinding) -> bool:
    return binding.state == "starting" and bool(binding.provider_session_id)


def _primary_binding_action(binding: SessionBinding) -> str | None:
    if _is_stale_starting_binding(binding):
        return "clear_stale_starting"
    if binding.state == "bound" and binding.provider_session_id:
        return "resume_then_replace_if_missing"
    return None


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
        if binding is None:
            continue
        action = _primary_binding_action(binding)
        if action is not None:
            entry = _binding_policy_entry(binding, action=action)
            entry["role"] = role
            bindings[slot_key] = entry

    for review in reviews:
        loop_id = str(review.get("id") or "").strip()
        if not loop_id:
            continue
        loop = ReviewLoop.from_dict(review)
        binding = loop.reviewer_binding
        if binding is None:
            continue
        if _is_stale_starting_binding(binding):
            action = "clear_stale_starting"
        elif binding.state == "bound" and binding.provider_session_id:
            action = "resume_then_replace_if_missing"
        else:
            continue
        entry = _binding_policy_entry(binding, action=action)
        entry["role"] = "reviewer"
        bindings[f"{_REVIEWER_KEY_PREFIX}{loop_id}"] = entry

    if not bindings:
        return {"requires_correction": False, "bindings": {}}
    requires_correction = any(
        entry.get("action") == "clear_stale_starting"
        for entry in bindings.values()
    )
    return {"requires_correction": requires_correction, "bindings": bindings}


def execute_session_policy(
    store: RunStore,
    run_id: str,
    session_policy: dict[str, Any],
) -> None:
    """Apply continuation-path session corrections after apply_resume_plan_atomically."""

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
    if (
        binding is None
        or binding.state != "starting"
        or not binding.provider_session_id
    ):
        return False
    revoke_all_capabilities_for_session_instance(
        store,
        run_id,
        session_instance_id=binding.session_instance_id,
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
    if (
        binding is None
        or binding.state != "starting"
        or not binding.provider_session_id
    ):
        return
    revoke_all_capabilities_for_session_instance(
        store,
        run_id,
        session_instance_id=binding.session_instance_id,
    )
    updated_loop = replace(
        loop,
        reviewer_binding=binding.released_for_reallocation(),
    )
    save_review_with_expected_revision(
        store,
        run_id,
        updated_loop,
        expected_revision=review_record_revision(review),
    )


from top_down_planning.orchestrator.session_policy import register_session_policy_executor

register_session_policy_executor(execute_session_policy)

__all__ = [
    "derive_session_policy",
    "execute_session_policy",
]
