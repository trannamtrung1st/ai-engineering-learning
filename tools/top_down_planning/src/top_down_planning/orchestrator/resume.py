"""Resume precondition checks for interrupted runs (proposal §18, §17.6 step 6)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from top_down_planning.agent_tool.artifacts import verify_evidence_snapshot
from top_down_planning.agent_tool.errors import RequestError
from top_down_planning.config import (
    compute_input_digest,
    compute_output_goal_digest,
    compute_context_digest_from_config,
)
from top_down_planning.domain.production import has_pending_amendment
from top_down_planning.domain.reviews import (
    find_active_review_loop,
    find_whole_plan_approval,
)
from top_down_planning.orchestrator.errors import OrchestratorError
from top_down_planning.orchestrator.phases import (
    OUTPUT_VALIDATED,
    PLAN_AMENDMENT,
    PLAN_VALIDATED,
    PLANNING,
    PRODUCTION,
    WHOLE_OUTPUT_REVIEW,
    WHOLE_PLAN_REVIEW,
)
from top_down_planning.persistence.digests import (
    compute_config_digest,
    compute_output_digest,
    compute_plan_digest,
)
from top_down_planning.persistence.interface import RunStore
from top_down_planning.workspace import run_workspace


class ResumeError(OrchestratorError):
    """Resume blocked by missing session refs, digest mismatch, or invalid phase binding."""

    def __init__(self, message: str, *, code: str = "resume_error") -> None:
        super().__init__(message, code=code)


@dataclass(frozen=True)
class ResumePreconditions:
    run_id: str
    phase: str
    status: str
    outcome: str | None


def validate_resume_preconditions(store: RunStore, run_id: str) -> ResumePreconditions:
    """Validate store digests and session ownership before resuming a run."""

    run = store.load_run(run_id)
    phase = str(run.get("phase") or "")
    status = str(run.get("status") or "running")
    outcome = run.get("outcome")

    terminal_outcome = outcome if isinstance(outcome, str) else None

    if status == "completed":
        return ResumePreconditions(
            run_id=run_id,
            phase=phase,
            status=status,
            outcome=terminal_outcome,
        )

    if phase == OUTPUT_VALIDATED:
        return ResumePreconditions(
            run_id=run_id,
            phase=phase,
            status=status,
            outcome=terminal_outcome,
        )

    _validate_digests(store, run_id, run)
    production = store.load_production(run_id)
    _validate_phase_binding(production, phase)
    _validate_session_refs(store, run_id, run, production, phase)
    _validate_plan_approval_binding(store, run_id, production, phase)

    return ResumePreconditions(
        run_id=run_id,
        phase=phase,
        status=status,
        outcome=outcome if isinstance(outcome, str) else None,
    )


def _validate_digests(store: RunStore, run_id: str, run: dict[str, Any]) -> None:
    stored = dict(run.get("digests") or {})
    config = store.load_resolved_config(run_id)
    plan = store.load_plan(run_id)

    expected_config = compute_config_digest(config)
    actual_config = stored.get("config")
    if actual_config != expected_config:
        raise ResumeError(
            "semantic config digest mismatch; refusing to resume with changed configuration",
            code="digest_mismatch",
        )

    expected_plan = compute_plan_digest(plan)
    actual_plan = stored.get("plan")
    if actual_plan != expected_plan:
        raise ResumeError(
            "plan digest mismatch; refusing to resume with divergent plan.json",
            code="digest_mismatch",
        )

    try:
        base_dir = run_workspace(run)
    except ValueError as exc:
        raise ResumeError(
            str(exc),
            code="missing_workspace",
        ) from exc

    expected_goal = compute_output_goal_digest(config, base_dir=base_dir)
    actual_goal = stored.get("output_goal")
    if actual_goal != expected_goal:
        raise ResumeError(
            "output goal digest mismatch; refusing to resume with changed goal",
            code="digest_mismatch",
        )

    expected_input = compute_input_digest(config, base_dir=base_dir)
    actual_input = stored.get("input")
    if actual_input != expected_input:
        raise ResumeError(
            "input digest mismatch; refusing to resume with changed input refs",
            code="digest_mismatch",
        )

    expected_context = compute_context_digest_from_config(
        config,
        workspace=base_dir,
    )
    actual_context = stored.get("context")
    if actual_context != expected_context:
        raise ResumeError(
            "context digest mismatch; refusing to resume with changed agent context",
            code="digest_mismatch",
        )

    production = store.load_production(run_id)
    expected_output = compute_output_digest(production)
    actual_output = stored.get("output")
    if actual_output is not None and actual_output != expected_output:
        raise ResumeError(
            "output digest mismatch; refusing to resume with divergent production.json",
            code="digest_mismatch",
        )
    _validate_output_evidence_snapshots(store, run_id, production)


def _validate_output_evidence_snapshots(
    store: RunStore,
    run_id: str,
    production: dict[str, Any],
) -> None:
    for entry in production.get("output_evidence") or []:
        if not isinstance(entry, dict):
            continue
        try:
            verify_evidence_snapshot(store, run_id, entry)
        except RequestError as exc:
            raise ResumeError(
                str(exc),
                code="evidence_integrity",
            ) from exc


def _validate_phase_binding(
    production: dict[str, Any],
    phase: str,
) -> None:
    if phase == PLAN_AMENDMENT and not has_pending_amendment(production):
        raise ResumeError(
            "run is in plan_amendment phase without a pending amendment request",
            code="invalid_phase_binding",
        )


def _validate_session_refs(
    store: RunStore,
    run_id: str,
    run: dict[str, Any],
    production: dict[str, Any],
    phase: str,
) -> None:
    """Enforce session continuity for phases that already own a primary session.

    Missing primary session ids are allowed only when the phase orchestrator is
    still responsible for *starting* that owner session for the first time
    (``planning`` → planner, ``plan_validated`` / ``production`` → producer).
    Once a later phase depends on an already-established owner (reviews,
    amendment), missing refs block resume — never invent a replacement id.
    """

    sessions = dict(run.get("sessions") or {})
    planner_session_id = sessions.get("primary_planner_session_id")
    producer_session_id = sessions.get("primary_producer_session_id")

    if _requires_amendment_sessions(production, phase):
        _require_session(
            planner_session_id,
            label="primary planner",
            phase=phase,
        )
        _require_session(
            producer_session_id,
            label="primary producer",
            phase=phase,
        )
        return

    if phase == PLANNING:
        # PlanningPhaseOrchestrator starts the primary planner when absent.
        return

    if phase == WHOLE_PLAN_REVIEW:
        _require_session(planner_session_id, label="primary planner", phase=phase)
        _validate_active_reviewer_session(store, run_id, "whole_plan", phase)
        return

    if phase in {PLAN_VALIDATED, PRODUCTION}:
        # ProductionPhaseOrchestrator starts the primary producer when absent
        # (including interrupt after entering ``production`` but before persist).
        return

    if phase == WHOLE_OUTPUT_REVIEW:
        _require_session(producer_session_id, label="primary producer", phase=phase)
        _validate_active_reviewer_session(store, run_id, "whole_output", phase)
        return


def _validate_active_reviewer_session(
    store: RunStore,
    run_id: str,
    loop_type: str,
    phase: str,
) -> None:
    loop = find_active_review_loop(store.list_reviews(run_id), loop_type)
    if loop is None:
        return
    session_id = loop.reviewer_session_id
    if session_id is None or str(session_id).strip() == "":
        raise ResumeError(
            f"active {loop_type} review loop {loop.id} is missing reviewer_session_id; "
            f"refusing to resume phase {phase!r}",
            code="missing_session_ref",
        )


def _requires_amendment_sessions(production: dict[str, Any], phase: str) -> bool:
    if phase == PLAN_AMENDMENT:
        return True
    return has_pending_amendment(production)


def _validate_plan_approval_binding(
    store: RunStore,
    run_id: str,
    production: dict[str, Any],
    phase: str,
) -> None:
    if has_pending_amendment(production):
        return

    if phase not in {PLAN_VALIDATED, PRODUCTION, WHOLE_OUTPUT_REVIEW}:
        return

    plan_revision = int(store.load_plan(run_id)["revision"])
    approval = find_whole_plan_approval(store.list_reviews(run_id), plan_revision)
    if approval is None:
        raise ResumeError(
            "run lacks whole-plan approval for the current plan revision; "
            "cannot resume production or output review",
            code="missing_plan_approval",
        )

    if approval.get("target_revision") is None:
        raise ResumeError(
            "whole-plan approval is missing target_revision binding",
            code="stale_plan_approval",
        )


def _require_session(
    session_id: object,
    *,
    label: str,
    phase: str,
) -> None:
    if session_id is None or str(session_id).strip() == "":
        raise ResumeError(
            f"{label} session reference is missing; refusing to resume phase {phase!r}",
            code="missing_session_ref",
        )
