"""Persisted session-recovery enforcement state (proposal §13.3, §18.2)."""

from __future__ import annotations

from typing import Any

from top_down_planning.domain.run_lifecycle import RunLifecycleError


def validate_session_recovery_fields(run: dict[str, Any]) -> None:
    for field in ("session_replacement_phase_action_id", "phase_action_domain_committed_id"):
        value = run.get(field)
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise RunLifecycleError(f"run.{field} must be a non-empty string or null")


def session_replacement_phase_action_id(run: dict[str, Any]) -> str | None:
    value = run.get("session_replacement_phase_action_id")
    if value is None or not str(value).strip():
        return None
    return str(value).strip()


def phase_action_domain_committed_id(run: dict[str, Any]) -> str | None:
    value = run.get("phase_action_domain_committed_id")
    if value is None or not str(value).strip():
        return None
    return str(value).strip()


def replacement_attempted_for_phase_action(run: dict[str, Any], phase_action_id: str) -> bool:
    recorded = session_replacement_phase_action_id(run)
    return recorded is not None and recorded == str(phase_action_id).strip()


def domain_budget_committed_for_phase_action(run: dict[str, Any], phase_action_id: str) -> bool:
    recorded = phase_action_domain_committed_id(run)
    return recorded is not None and recorded == str(phase_action_id).strip()


__all__ = [
    "domain_budget_committed_for_phase_action",
    "phase_action_domain_committed_id",
    "replacement_attempted_for_phase_action",
    "session_replacement_phase_action_id",
    "validate_session_recovery_fields",
]
