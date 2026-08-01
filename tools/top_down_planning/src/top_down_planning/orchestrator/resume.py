"""Interim resume guards until Phase 3 ``prepare_resume`` lands (proposal §18)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from top_down_planning.domain.run_ownership import (
    RunOwnershipError,
    assert_expected_run_revision,
    assert_no_live_process_owns_run,
    resolve_run_dir,
)
from top_down_planning.orchestrator.errors import OrchestratorError
from top_down_planning.orchestrator.phases import OUTPUT_VALIDATED
from top_down_planning.orchestrator.apply_resume import (
    ApplyResumeError,
    apply_resume_plan_atomically,
)
from top_down_planning.orchestrator.prepare_resume import (
    PrepareResumeBlockedError,
    prepare_resume,
)
from top_down_planning.orchestrator.session_policy_execution import execute_session_policy
from top_down_planning.persistence.interface import RunStore

__all__ = [
    "ApplyResumeError",
    "PrepareResumeBlockedError",
    "ResumeNotAllowedError",
    "RunResumeSnapshot",
    "apply_resume_plan_atomically",
    "assert_resume_allowed",
    "assert_resume_apply_preconditions",
    "assert_running_continuation_preconditions",
    "execute_session_policy",
    "is_terminal_resume_snapshot",
    "load_run_resume_snapshot",
    "prepare_resume",
    "short_digest_for_observability",
]


def short_digest_for_observability(digest: str | None) -> str | None:
    """Return a shortened digest suitable for durable audit events."""

    if digest is None:
        return None
    text = str(digest)
    if len(text) <= 12:
        return text
    return f"{text[:8]}..."


class ResumeNotAllowedError(OrchestratorError):
    """Resume blocked until Phase 3 resume apply (failed/paused runs)."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "resume_not_allowed",
        stop: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code)
        self.stop = stop


@dataclass(frozen=True)
class RunResumeSnapshot:
    run_id: str
    phase: str
    status: str
    outcome: str | None
    stop: dict[str, Any] | None


def load_run_resume_snapshot(store: RunStore, run_id: str) -> RunResumeSnapshot:
    run = store.load_run(run_id)
    stop = run.get("stop")
    outcome = run.get("outcome")
    return RunResumeSnapshot(
        run_id=run_id,
        phase=str(run.get("phase") or ""),
        status=str(run.get("status") or "running"),
        outcome=outcome if isinstance(outcome, str) else None,
        stop=dict(stop) if isinstance(stop, dict) else None,
    )


def assert_resume_allowed(snapshot: RunResumeSnapshot) -> None:
    """Reject failed and paused runs until Phase 3 resume apply."""

    if snapshot.status == "failed":
        raise ResumeNotAllowedError(
            "failed runs cannot be resumed",
            code="failed_run_not_resumable",
            stop=snapshot.stop,
        )

    if snapshot.status == "paused":
        stop_code = (snapshot.stop or {}).get("code", "unknown")
        raise ResumeNotAllowedError(
            "paused runs cannot be resumed via tdp resume until resume apply "
            f"is available (stop={stop_code})",
            code="paused_run_not_resumable",
            stop=snapshot.stop,
        )


def is_terminal_resume_snapshot(snapshot: RunResumeSnapshot) -> bool:
    return snapshot.status == "completed" or snapshot.phase == OUTPUT_VALIDATED


def assert_resume_apply_preconditions(
    store: RunStore,
    run_id: str,
    *,
    expected_run_revision: int,
) -> RunResumeSnapshot:
    """Validate revision CAS and live-process ownership before resume apply."""

    run = store.load_run(run_id)
    assert_expected_run_revision(run, expected_run_revision)
    run_dir = resolve_run_dir(store, run_id)
    if run_dir is not None:
        assert_no_live_process_owns_run(run_id, run_dir=run_dir)
    return load_run_resume_snapshot(store, run_id)


def assert_running_continuation_preconditions(
    store: RunStore,
    run_id: str,
    *,
    expected_run_revision: int,
) -> RunResumeSnapshot:
    """Validate ownership and revision for interrupted running→running continuation."""

    snapshot = assert_resume_apply_preconditions(
        store,
        run_id,
        expected_run_revision=expected_run_revision,
    )
    if snapshot.status != "running":
        raise ResumeNotAllowedError(
            f"running continuation requires status=running (found {snapshot.status!r})",
            code="running_continuation_invalid_status",
            stop=snapshot.stop,
        )
    return snapshot
