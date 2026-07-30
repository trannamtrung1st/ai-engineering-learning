"""Central run continuation loop for user CLI commands."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from core_tools.observability import ConsoleEvent
from top_down_planning.domain.production import has_pending_amendment
from top_down_planning.observability import (
    ObservabilityContext,
    cancel_console_event,
    session_lifecycle_event,
)
from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.orchestrator.failure import mark_run_failed, sanitize_operational_error
from top_down_planning.orchestrator.plan_amendment import PlanAmendmentOrchestrator
from top_down_planning.orchestrator.planning import PlanningPhaseOrchestrator
from top_down_planning.orchestrator.production import ProductionPhaseOrchestrator
from top_down_planning.orchestrator.resume import ResumeError, validate_resume_preconditions
from top_down_planning.orchestrator.whole_output_review import WholeOutputReviewOrchestrator
from top_down_planning.orchestrator.whole_plan_review import WholePlanReviewOrchestrator
from top_down_planning.orchestrator.phases import (
    OUTPUT_VALIDATED,
    PLANNING,
    PLAN_VALIDATED,
    PRODUCTION,
    WHOLE_OUTPUT_REVIEW,
    WHOLE_PLAN_REVIEW,
)
from top_down_planning.persistence.interface import RunStore
from top_down_planning.workspace import run_workspace
from core_tools.provider import Provider

ProviderFactory = Callable[[dict[str, Any], Any], Provider]


@dataclass
class RunStepResult:
    phase: str
    ok: bool
    status: str
    outcome: str | None
    details: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None


@dataclass
class RunContinuationResult:
    ok: bool
    run_id: str
    phase: str
    status: str
    outcome: str | None
    steps: list[RunStepResult] = field(default_factory=list)
    reason: str | None = None
    cancelled: bool = False


def _target_reached(run: dict[str, Any], until: str) -> bool:
    phase = str(run.get("phase") or "")
    status = str(run.get("status") or "")
    if until == "plan":
        return phase != PLANNING
    if until == "validated":
        return phase in {
            PLAN_VALIDATED,
            PRODUCTION,
            WHOLE_OUTPUT_REVIEW,
            OUTPUT_VALIDATED,
        }
    if until == "completed":
        return phase == OUTPUT_VALIDATED or status in {"completed", "failed"}
    raise ValueError(f"unsupported until target: {until!r}")


class RunEngine:
    """Drive a run forward through phase orchestrators until a target is reached."""

    def __init__(
        self,
        store: RunStore,
        *,
        create_provider: ProviderFactory,
        observability: ObservabilityContext | None = None,
    ) -> None:
        self._store = store
        self._create_provider = create_provider
        self._observability = observability

    def continue_run(
        self,
        run_id: str,
        *,
        until: str = "plan",
        single_step: bool = False,
    ) -> RunContinuationResult:
        started_at = time.monotonic()
        steps: list[RunStepResult] = []
        while True:
            run = self._store.load_run(run_id)
            if not single_step and _target_reached(run, until):
                result = RunContinuationResult(
                    ok=True,
                    run_id=run_id,
                    phase=str(run.get("phase") or ""),
                    status=str(run.get("status") or ""),
                    outcome=run.get("outcome"),
                    steps=steps,
                )
                self._emit_done(result, started_at=started_at)
                return result

            status = str(run.get("status") or "")
            if status in {"completed", "failed"}:
                result = RunContinuationResult(
                    ok=status != "failed",
                    run_id=run_id,
                    phase=str(run.get("phase") or ""),
                    status=status,
                    outcome=run.get("outcome"),
                    steps=steps,
                    reason="run already terminated",
                )
                self._emit_done(result, started_at=started_at)
                return result

            try:
                preconditions = validate_resume_preconditions(self._store, run_id)
            except ResumeError as exc:
                result = RunContinuationResult(
                    ok=False,
                    run_id=run_id,
                    phase=str(run.get("phase") or ""),
                    status=status,
                    outcome=run.get("outcome"),
                    steps=steps,
                    reason=exc.message,
                )
                self._emit_done(result, started_at=started_at)
                return result

            production = self._store.load_production(run_id)
            phase = preconditions.phase
            config = self._store.load_resolved_config(run_id)
            workspace = run_workspace(run)
            provider = self._create_provider(config, workspace)

            try:
                if has_pending_amendment(production) and phase != PRODUCTION:
                    result = PlanAmendmentOrchestrator(self._store, run_id, provider).run()
                    step = RunStepResult(
                        phase=str(result.phase),
                        ok=result.ok,
                        status=str(self._store.load_run(run_id).get("status") or ""),
                        outcome=self._store.load_run(run_id).get("outcome"),
                        details={
                            "amendment_id": result.amendment_id,
                            "planner_session_id": result.planner_session_id,
                            "producer_session_id": result.producer_session_id,
                        },
                        reason=result.reason,
                    )
                elif phase == WHOLE_OUTPUT_REVIEW:
                    result = WholeOutputReviewOrchestrator(self._store, run_id, provider).run()
                    step = RunStepResult(
                        phase=str(result.phase),
                        ok=result.ok,
                        status=str(self._store.load_run(run_id).get("status") or ""),
                        outcome=self._store.load_run(run_id).get("outcome"),
                        details={
                            "loop_id": result.loop_id,
                            "reviewer_session_id": result.reviewer_session_id,
                            "revision_cycles": result.revision_cycles,
                        },
                        reason=result.reason,
                    )
                elif phase in {PLAN_VALIDATED, PRODUCTION}:
                    result = ProductionPhaseOrchestrator(self._store, run_id, provider).run()
                    step = RunStepResult(
                        phase=str(result.phase),
                        ok=result.ok,
                        status=str(self._store.load_run(run_id).get("status") or ""),
                        outcome=self._store.load_run(run_id).get("outcome"),
                        details={
                            "session_id": result.session_id,
                            "batch_count": result.batch_count,
                        },
                        reason=result.reason,
                    )
                elif phase == WHOLE_PLAN_REVIEW:
                    result = WholePlanReviewOrchestrator(self._store, run_id, provider).run()
                    step = RunStepResult(
                        phase=str(result.phase),
                        ok=result.ok,
                        status=str(self._store.load_run(run_id).get("status") or ""),
                        outcome=self._store.load_run(run_id).get("outcome"),
                        details={
                            "loop_id": result.loop_id,
                            "reviewer_session_id": result.reviewer_session_id,
                            "revision_cycles": result.revision_cycles,
                        },
                        reason=result.reason,
                    )
                elif phase == PLANNING:
                    result = PlanningPhaseOrchestrator(self._store, run_id, provider).run()
                    step = RunStepResult(
                        phase=str(result.phase),
                        ok=result.ok,
                        status=str(self._store.load_run(run_id).get("status") or ""),
                        outcome=self._store.load_run(run_id).get("outcome"),
                        details={
                            "session_id": result.session_id,
                            "agent_turns": result.agent_turns,
                            "items_added": result.items_added,
                        },
                        reason=result.reason,
                    )
                else:
                    result = RunContinuationResult(
                        ok=False,
                        run_id=run_id,
                        phase=phase,
                        status=status,
                        outcome=run.get("outcome"),
                        steps=steps,
                        reason=f"cannot continue unsupported phase: {phase!r}",
                    )
                    self._emit_done(result, started_at=started_at)
                    return result
            except ProviderRunError as exc:
                mark_run_failed(self._store, run_id, message=str(exc))
                result = RunContinuationResult(
                    ok=False,
                    run_id=run_id,
                    phase=phase,
                    status=str(self._store.load_run(run_id).get("status") or ""),
                    outcome=self._store.load_run(run_id).get("outcome"),
                    steps=steps,
                    reason=str(exc),
                )
                self._emit_done(result, started_at=started_at)
                return result
            except KeyboardInterrupt:
                self._emit(cancel_console_event(run_id=run_id, phase=phase))
                result = RunContinuationResult(
                    ok=False,
                    run_id=run_id,
                    phase=phase,
                    status=str(self._store.load_run(run_id).get("status") or ""),
                    outcome=self._store.load_run(run_id).get("outcome"),
                    steps=steps,
                    reason="cancelled by user",
                    cancelled=True,
                )
                return result
            except Exception as exc:
                message = sanitize_operational_error(exc)
                mark_run_failed(self._store, run_id, message=message)
                result = RunContinuationResult(
                    ok=False,
                    run_id=run_id,
                    phase=phase,
                    status=str(self._store.load_run(run_id).get("status") or ""),
                    outcome=self._store.load_run(run_id).get("outcome"),
                    steps=steps,
                    reason=message,
                )
                self._emit_done(result, started_at=started_at)
                return result
            finally:
                for session in provider.list_active_sessions():
                    self._emit(
                        session_lifecycle_event(
                            category="session:end",
                            role=session["role"],
                            phase=phase,
                            session_id=session["session_id"],
                            run_id=run_id,
                            kind=session.get("kind"),
                        )
                    )
                provider.terminate_all_sessions()

            steps.append(step)
            if not step.ok:
                result = RunContinuationResult(
                    ok=False,
                    run_id=run_id,
                    phase=step.phase,
                    status=step.status,
                    outcome=step.outcome,
                    steps=steps,
                    reason=step.reason,
                )
                self._emit_done(result, started_at=started_at)
                return result
            if single_step:
                run = self._store.load_run(run_id)
                result = RunContinuationResult(
                    ok=True,
                    run_id=run_id,
                    phase=str(run.get("phase") or ""),
                    status=str(run.get("status") or ""),
                    outcome=run.get("outcome"),
                    steps=steps,
                )
                self._emit_done(result, started_at=started_at)
                return result

    def _emit(self, event: ConsoleEvent) -> None:
        if self._observability is not None:
            self._observability.emit(event)

    def _emit_done(self, result: RunContinuationResult, *, started_at: float) -> None:
        duration_ms = int((time.monotonic() - started_at) * 1000)
        self._emit(
            ConsoleEvent(
                category="done",
                message=(
                    f"run {'completed' if result.ok else 'stopped'} "
                    f"(phase={result.phase}, status={result.status})"
                ),
                fields={
                    "ok": result.ok,
                    "phase": result.phase,
                    "status": result.status,
                    "outcome": result.outcome,
                    "duration_ms": duration_ms,
                    "reason": result.reason,
                },
                run_id=result.run_id,
            )
        )
