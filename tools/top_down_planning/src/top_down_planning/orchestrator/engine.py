"""Central run continuation loop for user CLI commands."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from core_tools.observability import ConsoleEvent
from top_down_planning.domain.production import has_pending_amendment
from top_down_planning.observability import (
    ObservabilityContext,
    cancel_console_event,
)
from top_down_planning.domain.run_lifecycle import StopRecord, continuation_ok_from_run
from top_down_planning.domain.run_ownership import (
    resolve_run_dir,
    run_ownership,
)
from top_down_planning.orchestrator.agent_process_cleanup import (
    finalize_user_cancel,
    kill_orphan_agents,
)
from core_tools.provider.errors import ProviderTurnError
from top_down_planning.orchestrator.errors import (
    OrchestratorInvariantError,
    ProviderRunError,
    SessionRecoveryPaused,
)
from top_down_planning.orchestrator.failure import (
    mark_run_failed,
    sanitize_operational_error,
)
from top_down_planning.orchestrator.provider_teardown import teardown_provider_sessions
from top_down_planning.orchestrator.run_signals import trap_run_interrupt_signals
from top_down_planning.orchestrator.run_transitions import pause_run
from top_down_planning.orchestrator.session_policy import execute_session_policy_if_registered
from top_down_planning.orchestrator.session_policy_execution import (
    derive_session_policy,
    execute_session_policy,
)
import top_down_planning.orchestrator.session_policy_execution  # noqa: F401 — registers executor
from top_down_planning.orchestrator.plan_amendment import (
    PlanAmendmentOrchestrator,
    PlanAmendmentResult,
)
from top_down_planning.orchestrator.planning import PlanningPhaseOrchestrator
from top_down_planning.domain.run_kind import (
    RUN_KIND_PARENT_EXECUTION,
    RUN_KIND_SUB_TDP_EXECUTION,
    resolve_run_kind,
)
from top_down_planning.orchestrator.production import ProductionPhaseOrchestrator
from top_down_planning.orchestrator.sub_tdps import SubTdpsPhaseOrchestrator
from top_down_planning.orchestrator.whole_output_review import WholeOutputReviewOrchestrator
from top_down_planning.orchestrator.whole_plan_review import WholePlanReviewOrchestrator
from top_down_planning.orchestrator.phases import (
    OUTPUT_VALIDATED,
    PLANNING,
    PLAN_AMENDMENT,
    PLAN_VALIDATED,
    PRODUCTION,
    SUB_TDPS,
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
    target_reached: bool = False


def _target_reached(run: dict[str, Any], until: str) -> bool:
    phase = str(run.get("phase") or "")
    status = str(run.get("status") or "")
    if until == "plan":
        return phase != PLANNING
    if until == "validated":
        return phase in {
            PLAN_VALIDATED,
            PRODUCTION,
            SUB_TDPS,
            WHOLE_OUTPUT_REVIEW,
            OUTPUT_VALIDATED,
        }
    if until == "completed":
        return phase == OUTPUT_VALIDATED or status == "completed"
    raise ValueError(f"unsupported until target: {until!r}")


def _continuation_ok_from_run(run: dict[str, Any]) -> bool:
    return continuation_ok_from_run(run)


def _continuation_cancelled_from_run(run: dict[str, Any]) -> bool:
    if str(run.get("status") or "") != "paused":
        return False
    stop = run.get("stop")
    if not isinstance(stop, dict):
        return False
    return str(stop.get("code") or "") == "user_cancelled"


def _maybe_stopped_continuation_result(
    run: dict[str, Any],
    run_id: str,
    *,
    until: str,
    steps: list[RunStepResult],
) -> RunContinuationResult | None:
    status = str(run.get("status") or "")
    if status == "completed":
        return _continuation_result_from_run(
            run,
            run_id,
            until=until,
            steps=steps,
            reason="run already terminated",
        )
    if status == "failed":
        return _continuation_result_from_run(
            run,
            run_id,
            until=until,
            steps=steps,
            ok=False,
            reason="failed runs cannot be resumed",
        )
    if status == "paused":
        stop = run.get("stop")
        stop_code = stop.get("code") if isinstance(stop, dict) else None
        return _continuation_result_from_run(
            run,
            run_id,
            until=until,
            steps=steps,
            ok=False,
            reason=f"run is paused ({stop_code or 'unknown'})",
        )
    return None


def _continuation_result_from_run(
    run: dict[str, Any],
    run_id: str,
    *,
    until: str,
    steps: list[RunStepResult],
    ok: bool | None = None,
    reason: str | None = None,
    cancelled: bool | None = None,
    target_reached: bool | None = None,
) -> RunContinuationResult:
    if ok is None:
        ok = _continuation_ok_from_run(run)
    if cancelled is None:
        cancelled = _continuation_cancelled_from_run(run)
    if target_reached is None:
        target_reached = _target_reached(run, until)
    return RunContinuationResult(
        ok=ok,
        run_id=run_id,
        phase=str(run.get("phase") or ""),
        status=str(run.get("status") or ""),
        outcome=run.get("outcome"),
        steps=steps,
        reason=reason,
        cancelled=cancelled,
        target_reached=target_reached,
    )


_AMENDMENT_SOURCE_PHASES = frozenset(
    {
        PLANNING,
        WHOLE_PLAN_REVIEW,
        WHOLE_OUTPUT_REVIEW,
        PLAN_VALIDATED,
        PLAN_AMENDMENT,
        SUB_TDPS,
    }
)


def _is_continuable_phase(run: dict[str, Any], production: dict[str, Any]) -> bool:
    phase = str(run.get("phase") or "")
    if has_pending_amendment(production) and phase != PRODUCTION:
        return phase in _AMENDMENT_SOURCE_PHASES
    return phase in {
        PLANNING,
        WHOLE_PLAN_REVIEW,
        WHOLE_OUTPUT_REVIEW,
        PRODUCTION,
        SUB_TDPS,
        PLAN_VALIDATED,
        PLAN_AMENDMENT,
    }


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
        session_policy: dict[str, Any] | None = None,
    ) -> RunContinuationResult:
        started_at = time.monotonic()
        with trap_run_interrupt_signals():
            run = self._store.load_run(run_id)
            terminal = _maybe_stopped_continuation_result(
                run,
                run_id,
                until=until,
                steps=[],
            )
            if terminal is not None:
                self._emit_done(terminal, started_at=started_at)
                return terminal

            run_dir = resolve_run_dir(self._store, run_id)
            if run_dir is not None:
                with run_ownership(run_id, run_dir=run_dir):
                    return self._continue_run_unlocked(
                        run_id,
                        until=until,
                        single_step=single_step,
                        session_policy=session_policy,
                        started_at=started_at,
                    )
            return self._continue_run_unlocked(
                run_id,
                until=until,
                single_step=single_step,
                session_policy=session_policy,
                started_at=started_at,
            )

    def _continue_run_unlocked(
        self,
        run_id: str,
        *,
        until: str = "plan",
        single_step: bool = False,
        session_policy: dict[str, Any] | None = None,
        started_at: float | None = None,
    ) -> RunContinuationResult:
        if started_at is None:
            started_at = time.monotonic()
        steps: list[RunStepResult] = []
        run = self._store.load_run(run_id)
        stopped = _maybe_stopped_continuation_result(
            run,
            run_id,
            until=until,
            steps=steps,
        )
        if stopped is not None:
            self._emit_done(stopped, started_at=started_at)
            return stopped

        if str(run.get("status") or "") == "running":
            try:
                if session_policy is not None:
                    execute_session_policy_if_registered(
                        self._store,
                        run_id,
                        session_policy,
                    )
                else:
                    derived_policy = derive_session_policy(
                        run,
                        self._store.list_reviews(run_id),
                    )
                    execute_session_policy(self._store, run_id, derived_policy)
                kill_orphan_agents(
                    self._store,
                    run_id,
                    exclude_pids=frozenset({os.getpid()}),
                )
            except Exception as exc:
                message = sanitize_operational_error(exc)
                run_before = self._store.load_run(run_id)
                if str(run_before.get("status") or "") == "running":
                    mark_run_failed(self._store, run_id, message=message)
                run = self._store.load_run(run_id)
                stopped = _maybe_stopped_continuation_result(
                    run,
                    run_id,
                    until=until,
                    steps=steps,
                )
                if stopped is not None and str(run.get("status") or "") != "running":
                    result = stopped
                else:
                    result = _continuation_result_from_run(
                        run,
                        run_id,
                        until=until,
                        steps=steps,
                        ok=False,
                        reason=message,
                    )
                self._emit_done(result, started_at=started_at)
                return result

        if not single_step:
            run = self._store.load_run(run_id)
            if str(run.get("status") or "") == "running" and _target_reached(run, until):
                result = _continuation_result_from_run(
                    run,
                    run_id,
                    until=until,
                    steps=steps,
                    ok=True,
                    target_reached=True,
                )
                self._emit_done(result, started_at=started_at)
                return result

        while True:
            run = self._store.load_run(run_id)
            stopped = _maybe_stopped_continuation_result(
                run,
                run_id,
                until=until,
                steps=steps,
            )
            if stopped is not None:
                self._emit_done(stopped, started_at=started_at)
                return stopped

            if not single_step and str(run.get("status") or "") == "running" and _target_reached(
                run, until
            ):
                result = _continuation_result_from_run(
                    run,
                    run_id,
                    until=until,
                    steps=steps,
                    ok=True,
                    target_reached=True,
                )
                self._emit_done(result, started_at=started_at)
                return result

            phase_for_entry = str(run.get("phase") or "")

            provider: Provider | None = None
            cancelled = False
            phase = phase_for_entry

            try:
                self._append_phase_entry_event(
                    run_id,
                    "phase_entry_attempted",
                    phase=phase_for_entry,
                )
                production = self._store.load_production(run_id)
                if not _is_continuable_phase(run, production):
                    result = _continuation_result_from_run(
                        run,
                        run_id,
                        until=until,
                        steps=steps,
                        ok=False,
                        reason=f"cannot continue unsupported phase: {phase!r}",
                    )
                    self._emit_done(result, started_at=started_at)
                    return result

                config = self._store.load_resolved_config(run_id)
                workspace = run_workspace(run)
                provider = self._create_provider(config, workspace)

                if has_pending_amendment(production) and phase != PRODUCTION:
                    kind = resolve_run_kind(run)
                    if kind in {RUN_KIND_PARENT_EXECUTION, RUN_KIND_SUB_TDP_EXECUTION}:
                        stop = StopRecord(
                            code="prepared_plan_amendment_required",
                            category="operational",
                            phase=phase,
                            message=(
                                "prepared execution cannot amend the approved plan in place; "
                                "re-run tdp prepare to materialize a new package"
                            ),
                        )
                        pause_run(
                            self._store,
                            run_id,
                            stop=stop,
                            revoke_phase=phase,
                            event_type="prepared_plan_amendment_required",
                        )
                        result = PlanAmendmentResult(
                            ok=False,
                            phase=phase,
                            status="paused",
                            outcome=None,
                            amendment_id=str(
                                production.get("pending_amendment_id") or ""
                            ),
                            planner_session_id=None,
                            producer_session_id=None,
                            reason=stop.message,
                        )
                    else:
                        result = PlanAmendmentOrchestrator(
                            self._store, run_id, provider
                        ).run()
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
                elif phase == SUB_TDPS or (
                    phase == PLAN_VALIDATED
                    and resolve_run_kind(run) == RUN_KIND_PARENT_EXECUTION
                ):
                    def _child_provider_factory(
                        child_config: dict[str, Any],
                        child_workspace: Any,
                    ) -> Provider:
                        return self._create_provider(child_config, child_workspace)

                    result = SubTdpsPhaseOrchestrator(
                        self._store,
                        run_id,
                        provider,
                        create_provider=_child_provider_factory,
                        observability=self._observability,
                    ).run()
                    step = RunStepResult(
                        phase=str(result.phase),
                        ok=result.ok,
                        status=str(self._store.load_run(run_id).get("status") or ""),
                        outcome=self._store.load_run(run_id).get("outcome"),
                        details={"units_completed": result.units_completed},
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
                    result = _continuation_result_from_run(
                        run,
                        run_id,
                        until=until,
                        steps=steps,
                        ok=False,
                        reason=f"cannot continue unsupported phase: {phase!r}",
                    )
                    self._emit_done(result, started_at=started_at)
                    return result
            except SessionRecoveryPaused as exc:
                run = self._store.load_run(run_id)
                result = _continuation_result_from_run(
                    run,
                    run_id,
                    until=until,
                    steps=steps,
                    ok=False,
                    reason=str(exc),
                )
                self._emit_done(result, started_at=started_at)
                return result
            except OrchestratorInvariantError as exc:
                message = sanitize_operational_error(exc)
                run_before = self._store.load_run(run_id)
                if str(run_before.get("status") or "") == "running":
                    mark_run_failed(self._store, run_id, message=message)
                run = self._store.load_run(run_id)
                result = _continuation_result_from_run(
                    run,
                    run_id,
                    until=until,
                    steps=steps,
                    ok=False,
                    reason=message,
                )
                self._emit_done(result, started_at=started_at)
                return result
            except (ProviderRunError, ProviderTurnError) as exc:
                run = self._store.load_run(run_id)
                if str(run.get("status") or "") != "running":
                    result = _continuation_result_from_run(
                        run,
                        run_id,
                        until=until,
                        steps=steps,
                        ok=False,
                        reason=str(exc),
                    )
                    self._emit_done(result, started_at=started_at)
                    return result
                stop = StopRecord(
                    code="provider_turn_failed",
                    category="operational",
                    phase=phase,
                    message=str(exc),
                )
                pause_run(self._store, run_id, stop=stop)
                run = self._store.load_run(run_id)
                result = _continuation_result_from_run(
                    run,
                    run_id,
                    until=until,
                    steps=steps,
                    ok=False,
                    reason=str(exc),
                )
                self._emit_done(result, started_at=started_at)
                return result
            except KeyboardInterrupt:
                self._emit(cancel_console_event(run_id=run_id, phase=phase))
                cancelled = True
            except Exception as exc:
                message = sanitize_operational_error(exc)
                run_before = self._store.load_run(run_id)
                if str(run_before.get("status") or "") == "running":
                    mark_run_failed(self._store, run_id, message=message)
                run = self._store.load_run(run_id)
                result = _continuation_result_from_run(
                    run,
                    run_id,
                    until=until,
                    steps=steps,
                    ok=False,
                    reason=message,
                )
                self._emit_done(result, started_at=started_at)
                return result
            finally:
                if provider is not None:
                    def append_event(event_type: str, **fields: Any) -> None:
                        self._store.append_event(
                            run_id,
                            {"type": event_type, **fields},
                        )

                    terminated_pids: list[int] = []
                    try:
                        terminated_pids = teardown_provider_sessions(
                            provider,
                            run_id=run_id,
                            phase=phase,
                            append_event=append_event,
                            emit_console=self._emit,
                            audit_cancel=cancelled,
                        )
                    except KeyboardInterrupt:
                        cancelled = True
                    except Exception as exc:
                        try:
                            append_event(
                                "provider_teardown_failed",
                                phase=phase,
                                message=sanitize_operational_error(exc),
                            )
                        except Exception:
                            pass
                    if cancelled:
                        run = self._store.load_run(run_id)
                        cancel_phase = str(run.get("phase") or phase)
                        finalize_user_cancel(
                            self._store,
                            run_id,
                            phase=cancel_phase,
                            provider_terminated_pids=terminated_pids,
                            exclude_pids=frozenset({os.getpid()}),
                        )

            if cancelled:
                run = self._store.load_run(run_id)
                user_cancelled = _continuation_cancelled_from_run(run)
                return _continuation_result_from_run(
                    run,
                    run_id,
                    until=until,
                    steps=steps,
                    reason=(
                        "cancelled by user"
                        if user_cancelled
                        else "interrupt during continuation"
                    ),
                    cancelled=user_cancelled,
                )

            steps.append(step)
            if not step.ok:
                run = self._store.load_run(run_id)
                result = _continuation_result_from_run(
                    run,
                    run_id,
                    until=until,
                    steps=steps,
                    ok=False,
                    reason=step.reason,
                )
                self._emit_done(result, started_at=started_at)
                return result
            if single_step:
                run = self._store.load_run(run_id)
                result = _continuation_result_from_run(
                    run,
                    run_id,
                    until=until,
                    steps=steps,
                )
                self._emit_done(result, started_at=started_at)
                return result

    def _append_phase_entry_event(
        self,
        run_id: str,
        event_type: str,
        **fields: Any,
    ) -> None:
        payload = {"type": event_type, **fields}
        self._store.append_event(run_id, payload)

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
