"""Attach active provider-turn ``phase_action_id`` to durable audit events."""

from __future__ import annotations

from typing import Any, Protocol


class _RunPhaseActionReader(Protocol):
    def load_run(self, run_id: str) -> dict[str, Any]: ...


def with_active_phase_action_id(
    store: _RunPhaseActionReader,
    run_id: str,
    event: dict[str, Any],
) -> dict[str, Any]:
    """Return ``event`` with ``phase_action_id`` when a provider turn action is active."""

    run = store.load_run(run_id)
    phase_action_id = str(run.get("phase_action_id") or "").strip()
    if not phase_action_id:
        return dict(event)
    merged = dict(event)
    merged["phase_action_id"] = phase_action_id
    return merged


__all__ = ["with_active_phase_action_id"]
