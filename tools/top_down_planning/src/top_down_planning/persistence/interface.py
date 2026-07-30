"""Run store contract for canonical snapshots and audit events (proposal §18)."""

from __future__ import annotations

from typing import Any, Protocol

from top_down_planning.domain.models import Plan


class RunStore(Protocol):
    """Abstract storage for run state, plan revisions, and append-only events."""

    def create_run(
        self,
        run_id: str,
        *,
        plan: Plan | dict[str, Any],
        resolved_config: dict[str, Any],
        input_digest: str,
        output_goal_digest: str,
        context_digest: str | None = None,
        phase: str = "planning",
        production: dict[str, Any] | None = None,
        workspace: str | None = None,
    ) -> dict[str, Any]:
        """Create a new run directory and initial artifacts."""

    def load_run(self, run_id: str) -> dict[str, Any]:
        """Load the current run record."""

    def save_run(self, run_id: str, run: dict[str, Any], expected_revision: int) -> int:
        """Persist a run record with optimistic revision checking."""

    def load_plan(self, run_id: str) -> dict[str, Any]:
        """Load the canonical current plan snapshot."""

    def load_plan_model(self, run_id: str) -> Plan:
        """Load the canonical plan snapshot as a domain model."""

    def save_plan(self, run_id: str, plan: dict[str, Any], expected_revision: int) -> int:
        """Persist a plan snapshot with optimistic revision checking."""

    def save_plan_model(self, run_id: str, plan: Plan, expected_revision: int) -> int:
        """Persist a domain plan snapshot with optimistic revision checking."""

    def load_production(self, run_id: str) -> dict[str, Any]:
        """Load the current production snapshot."""

    def save_production(
        self, run_id: str, production: dict[str, Any], expected_revision: int
    ) -> int:
        """Persist a production snapshot with optimistic revision checking."""

    def append_event(self, run_id: str, event: dict[str, Any]) -> None:
        """Append an audit event to the run event log."""

    def load_events(self, run_id: str) -> list[dict[str, Any]]:
        """Load all persisted audit events for a run."""

    def load_resolved_config(self, run_id: str) -> dict[str, Any]:
        """Load the resolved configuration snapshot for a run."""
