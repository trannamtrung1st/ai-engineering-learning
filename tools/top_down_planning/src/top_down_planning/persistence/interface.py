"""Run store contract for canonical snapshots and audit events (proposal §18)."""

from __future__ import annotations

from typing import Any, Protocol


class RunStore(Protocol):
    """Abstract storage for run state, plan revisions, and append-only events."""

    def load_run(self, run_id: str) -> dict[str, Any]:
        """Load the current run record."""

    def save_run(self, run_id: str, run: dict[str, Any], expected_revision: int | None) -> int:
        """Persist a run record with optimistic revision checking."""

    def load_plan(self, run_id: str) -> dict[str, Any]:
        """Load the canonical current plan snapshot."""

    def save_plan(self, run_id: str, plan: dict[str, Any], expected_revision: int | None) -> int:
        """Persist a plan snapshot with optimistic revision checking."""

    def append_event(self, run_id: str, event: dict[str, Any]) -> None:
        """Append an audit event to the run event log."""
