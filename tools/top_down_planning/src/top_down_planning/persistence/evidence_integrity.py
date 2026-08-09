"""Persisted production evidence snapshot verification."""

from __future__ import annotations

from typing import Any

from top_down_planning.agent_tool.artifacts import verify_evidence_snapshot
from top_down_planning.agent_tool.errors import RequestError
from top_down_planning.domain.production import live_output_evidence_entries


def verify_persisted_production_evidence_snapshots(
    store: Any,
    run_id: str,
    production: dict[str, Any],
) -> None:
    """Fail closed when live evidence rows lack valid captured snapshot bytes."""

    for entry in live_output_evidence_entries(production):
        try:
            verify_evidence_snapshot(store, run_id, entry)
        except RequestError as exc:
            from core_tools.persistence import PersistenceError

            raise PersistenceError(str(exc)) from exc


__all__ = ["verify_persisted_production_evidence_snapshots"]
