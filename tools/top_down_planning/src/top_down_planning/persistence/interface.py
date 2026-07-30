"""Run store contract for canonical snapshots and audit events."""

from __future__ import annotations

from typing import Any, Protocol

from top_down_planning.domain.models import Plan
from top_down_planning.persistence.commit import CommitSpec


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
        context_digest: str,
        phase: str = "planning",
        production: dict[str, Any] | None = None,
        workspace: str,
    ) -> dict[str, Any]:
        """Create a new run directory and initial artifacts."""

    def load_run(self, run_id: str) -> dict[str, Any]:
        """Load the current run record."""

    def load_plan(self, run_id: str) -> dict[str, Any]:
        """Load the canonical current plan snapshot."""

    def load_plan_model(self, run_id: str) -> Plan:
        """Load the canonical plan snapshot as a domain model."""

    def load_production(self, run_id: str) -> dict[str, Any]:
        """Load the current production snapshot."""

    def commit(self, run_id: str, spec: CommitSpec) -> dict[str, Any]:
        """Apply a single logical transaction across run artifacts."""

    def load_events(self, run_id: str) -> list[dict[str, Any]]:
        """Load all persisted audit events for a run."""

    def load_resolved_config(self, run_id: str) -> dict[str, Any]:
        """Load the resolved configuration snapshot for a run."""

    def save_review(self, run_id: str, review: dict[str, Any]) -> None:
        """Persist a review-loop record under reviews/."""

    def load_review(self, run_id: str, review_id: str) -> dict[str, Any]:
        """Load a single review-loop record."""

    def list_reviews(self, run_id: str) -> list[dict[str, Any]]:
        """Load all review-loop records for a run."""

    def create_capability(
        self,
        run_id: str,
        *,
        role: str,
        phase: str,
        allowed_ops: frozenset[str],
        session_id: str | None = None,
        session_kind: str = "primary",
    ) -> tuple[str, dict[str, Any]]:
        """Create a session capability token for agent mutations."""

    def load_capability(self, run_id: str, capability_id: str) -> dict[str, Any]:
        """Load a capability record."""

    def revoke_capability(self, run_id: str, capability_id: str) -> None:
        """Revoke a capability token."""

    def artifact_path(self, run_id: str, artifact_id: str, filename: str) -> Any:
        """Return a contained artifact path under the run store."""

    def write_artifact_bytes(
        self,
        run_id: str,
        artifact_id: str,
        filename: str,
        data: bytes,
    ) -> str:
        """Write artifact bytes into the run store and return the relative ref."""
