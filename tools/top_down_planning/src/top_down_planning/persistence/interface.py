"""Run store contract for canonical snapshots and audit events."""

from __future__ import annotations

from pathlib import Path
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
        context_spec_digest: str,
        context_snapshot_digest: str,
        context_snapshot_binding: dict[str, Any],
        phase: str = "planning",
        production: dict[str, Any] | None = None,
        workspace: str,
        invocation: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a new run directory and initial artifacts."""

    def load_run(self, run_id: str) -> dict[str, Any]:
        """Load the current run record under the per-run commit lock."""

    def load_plan(self, run_id: str) -> dict[str, Any]:
        """Load the canonical current plan snapshot under the per-run commit lock."""

    def load_plan_model(self, run_id: str) -> Plan:
        """Load the canonical plan snapshot as a domain model."""

    def load_production(self, run_id: str) -> dict[str, Any]:
        """Load the current production snapshot under the per-run commit lock."""

    def commit(self, run_id: str, spec: CommitSpec) -> dict[str, Any]:
        """Apply a journaled commit under the per-run commit lock."""

    def load_events(self, run_id: str) -> list[dict[str, Any]]:
        """Load audit events under the per-run commit lock."""

    def append_event(self, run_id: str, event: dict[str, Any]) -> None:
        """Append a single audit event to events.jsonl."""

    def load_resolved_config(self, run_id: str) -> dict[str, Any]:
        """Load the resolved configuration snapshot for a run."""

    def save_review(
        self,
        run_id: str,
        review: dict[str, Any],
        *,
        expected_revision: int | None = None,
    ) -> None:
        """Persist a review-loop record under reviews/."""

    def load_review(self, run_id: str, review_id: str) -> dict[str, Any]:
        """Load a single review-loop record under the per-run commit lock."""

    def list_reviews(self, run_id: str) -> list[dict[str, Any]]:
        """Load all review-loop records for a run under the per-run commit lock."""

    def create_capability(
        self,
        run_id: str,
        *,
        role: str,
        phase: str,
        allowed_ops: frozenset[str],
        session_id: str,
        session_kind: str = "primary",
        loop_id: str | None = None,
        session_instance_id: str | None = None,
        generation: int | None = None,
    ) -> tuple[str, dict[str, Any], str]:
        """Create a session capability token for agent mutations."""

    def load_capability(self, run_id: str, capability_id: str) -> dict[str, Any]:
        """Load a capability record."""

    def list_capabilities(self, run_id: str) -> list[dict[str, Any]]:
        """Load all capability records for a run."""

    def revoke_capability(self, run_id: str, capability_id: str) -> None:
        """Revoke a capability token."""

    def revoke_capabilities_for_session(self, run_id: str, session_id: str) -> None:
        """Revoke all live capabilities bound to a provider session."""

    def agent_requests_dir(self, run_id: str) -> Path:
        """Return the designated agent-authored request-input directory."""

    def artifact_path(self, run_id: str, snapshot_id: str, filename: str) -> Any:
        """Return a contained artifact snapshot path under the run store."""

    def write_artifact_bytes(
        self,
        run_id: str,
        snapshot_id: str,
        filename: str,
        data: bytes,
    ) -> str:
        """Write artifact bytes under an immutable snapshot id and return the relative ref."""
