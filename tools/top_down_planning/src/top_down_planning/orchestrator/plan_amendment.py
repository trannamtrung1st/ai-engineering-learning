"""Controlled plan-amendment orchestration (proposal §10.4, §13)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.domain.reconciliation import (
    apply_reconciliation,
    build_reconciliation_report,
)
from top_down_planning.domain.reviews import find_whole_plan_approval
from top_down_planning.domain.run_lifecycle import StopRecord
from top_down_planning.orchestrator.capability import (
    bind_provider_capability,
    issue_session_capability,
    revoke_capabilities_for_phase,
    rotate_session_capability,
)
from top_down_planning.orchestrator.run_transitions import (
    complete_run_with_outcome,
    pause_for_limit_exhausted,
)
from top_down_planning.orchestrator.errors import ProviderRunError, SessionRecoveryPaused
from top_down_planning.orchestrator.phases import (
    PLAN_AMENDMENT,
    PLAN_VALIDATED,
    PRODUCTION,
    WHOLE_PLAN_REVIEW,
)
from top_down_planning.orchestrator.provider_turns import (
    build_planner_turn_recovery,
    consume_provider_turn_with_session_recovery,
)
from top_down_planning.orchestrator.agent_context import resolve_role_session_context
from top_down_planning.orchestrator.session_events import (
    resume_primary_session_with_audit,
    sync_persisted_session_id,
)
from top_down_planning.orchestrator.planner_session import primary_planner_provider_session_id
from top_down_planning.orchestrator.producer_session import primary_producer_provider_session_id
from top_down_planning.orchestrator.whole_plan_review import WholePlanReviewOrchestrator
from top_down_planning.persistence.digests import compute_plan_digest
from top_down_planning.persistence.interface import RunStore
from core_tools.provider import Provider

_AMENDMENT_LIMIT_DEFAULTS = DEFAULT_CONFIG["limits"]["amendment"]
_AMENDMENT_REVISION_READY_SIGNAL = "amendment_revision_ready"
_COMPLETION_SIGNALS = frozenset({_AMENDMENT_REVISION_READY_SIGNAL})


@dataclass(frozen=True)
class PlanAmendmentResult:
    ok: bool
    phase: str
    status: str
    outcome: str | None
    amendment_id: str | None
    planner_session_id: str | None
    producer_session_id: str | None
    reconciliation: dict[str, Any] | None = None
    reason: str | None = None


class PlanAmendmentOrchestrator:
    """Drive amendment: pause production, planner revision, review, reconcile, resume."""

    def __init__(
        self,
        store: RunStore,
        run_id: str,
        provider: Provider,
    ) -> None:
        self._store = store
        self._run_id = run_id
        self._provider = provider
        self._capability_token: str | None = None

    def run(self) -> PlanAmendmentResult:
        production = self._store.load_production(self._run_id)
        amendment_id = production.get("pending_amendment_id")
        if not isinstance(amendment_id, str) or not amendment_id.strip():
            raise ProviderRunError("no pending plan amendment request")

        amendment = _find_amendment_request(production, amendment_id)
        if amendment is None:
            raise ProviderRunError(f"amendment request not found: {amendment_id}")

        run = self._store.load_run(self._run_id)
        phase = str(run.get("phase") or "")
        if phase not in {PRODUCTION, PLAN_AMENDMENT, WHOLE_PLAN_REVIEW, PLAN_VALIDATED}:
            raise ProviderRunError(f"run is not ready for plan amendment: {phase}")

        planner_session_id = primary_planner_provider_session_id(run)
        producer_session_id = primary_producer_provider_session_id(run)
        if planner_session_id is None:
            raise ProviderRunError("primary planner session is missing for amendment")
        if producer_session_id is None:
            raise ProviderRunError("primary producer session is missing for amendment")

        if phase == PRODUCTION:
            prior_plan = self._store.load_plan_model(self._run_id)
            run = self._enter_plan_amendment_phase(amendment_id, prior_plan)
            amendment = _find_amendment_request(
                self._store.load_production(self._run_id),
                amendment_id,
            )
            if amendment is None:
                raise ProviderRunError(f"amendment request not found: {amendment_id}")
        else:
            prior_plan = _require_prior_plan_snapshot(amendment)

        if str(run.get("phase") or "") == PLAN_AMENDMENT:
            run = self._activate_amendment_execution()
            phase = str(run.get("phase") or PLAN_AMENDMENT)
            self._capability_token = issue_session_capability(
                self._store,
                self._run_id,
                role="planner",
                phase=phase,
                session_id=planner_session_id,
                session_kind="primary",
            )
            bind_provider_capability(self._provider, self._capability_token)
            revision_cycles = int(amendment.get("revision_cycles") or 0)
            config = self._store.load_resolved_config(self._run_id)
            max_revision_cycles = _amendment_revision_limit(config)
            self._resume_planner_for_amendment(
                planner_session_id,
                amendment,
            )
            while True:
                signal = self._consume_planner_turn(planner_session_id)
                revision_cycles += 1
                amendment = self._persist_amendment_revision_cycles(
                    amendment_id,
                    revision_cycles,
                )
                if signal == _AMENDMENT_REVISION_READY_SIGNAL:
                    break
                if revision_cycles >= max_revision_cycles:
                    return self._pause_for_amendment_limit(
                        message=(
                            "plan amendment exceeded max_revision_cycles_per_request "
                            f"({max_revision_cycles})"
                        ),
                        limit="max_revision_cycles_per_request",
                        consumed=revision_cycles,
                        configured=max_revision_cycles,
                        amendment_id=amendment_id,
                        planner_session_id=planner_session_id,
                        producer_session_id=producer_session_id,
                    )
                self._resume_planner_for_amendment(
                    planner_session_id,
                    amendment,
                )
                run = self._store.load_run(self._run_id)
                phase = str(run.get("phase") or PLAN_AMENDMENT)
                self._capability_token = rotate_session_capability(
                    self._store,
                    self._run_id,
                    current_token=self._capability_token,
                    role="planner",
                    phase=phase,
                    session_id=planner_session_id,
                    session_kind="primary",
                )
                bind_provider_capability(self._provider, self._capability_token)

            run = self._transition_to_whole_plan_review()
            run = self._activate_amendment_execution()

        phase = str(run.get("phase") or "")
        if phase in {WHOLE_PLAN_REVIEW, PLAN_VALIDATED}:
            run = self._activate_amendment_execution()
            review_result = WholePlanReviewOrchestrator(
                self._store,
                self._run_id,
                self._provider,
            ).run()
            if not review_result.ok:
                return PlanAmendmentResult(
                    ok=False,
                    phase=review_result.phase,
                    status=review_result.status,
                    outcome=review_result.outcome,
                    amendment_id=amendment_id,
                    planner_session_id=planner_session_id,
                    producer_session_id=producer_session_id,
                    reason=review_result.reason,
                )

        new_plan = self._store.load_plan_model(self._run_id)
        approval = find_whole_plan_approval(
            self._store.list_reviews(self._run_id),
            new_plan.revision,
        )
        if approval is None:
            raise ProviderRunError(
                "amended plan requires an approved whole-plan review "
                "before production can resume"
            )

        production = self._store.load_production(self._run_id)
        report = build_reconciliation_report(
            amendment_id=amendment_id,
            prior_plan=prior_plan,
            new_plan=new_plan,
            production=production,
        )
        production = apply_reconciliation(production, report)
        expected_revision = int(production["revision"])
        production["revision"] = expected_revision + 1
        self._store.save_production(self._run_id, production, expected_revision)

        run = self._resume_production_phase(new_plan.revision)

        self._append_event(
            "plan_amendment_completed",
            amendment_id=amendment_id,
            prior_plan_revision=report.prior_plan_revision,
            new_plan_revision=report.new_plan_revision,
            planner_session_id=planner_session_id,
            producer_session_id=producer_session_id,
        )
        return PlanAmendmentResult(
            ok=True,
            phase=PRODUCTION,
            status=str(run.get("status") or "running"),
            outcome=run.get("outcome"),
            amendment_id=amendment_id,
            planner_session_id=planner_session_id,
            producer_session_id=producer_session_id,
            reconciliation=report.to_dict(),
        )

    def _enter_plan_amendment_phase(self, amendment_id: str, prior_plan: Any) -> dict[str, Any]:
        production = self._store.load_production(self._run_id)
        expected_revision = int(production["revision"])
        requests = list(production.get("amendment_requests") or [])
        updated_requests: list[dict[str, Any]] = []
        for request in requests:
            if not isinstance(request, dict):
                continue
            if str(request.get("id") or "") != amendment_id:
                updated_requests.append(request)
                continue
            patched = dict(request)
            patched["prior_plan_snapshot"] = prior_plan.to_dict()
            updated_requests.append(patched)
        production = dict(production)
        production["revision"] = expected_revision + 1
        production["amendment_requests"] = updated_requests
        self._store.save_production(self._run_id, production, expected_revision)

        run = self._store.load_run(self._run_id)
        expected_revision = int(run["revision"])
        revoke_capabilities_for_phase(self._store, self._run_id, str(run.get("phase") or ""))
        run = dict(run)
        run["revision"] = expected_revision + 1
        run["phase"] = PLAN_AMENDMENT
        stop = StopRecord(
            code="amendment_pending",
            category="operational",
            phase=PLAN_AMENDMENT,
            message="plan amendment requested",
            details={"pending_amendment_id": amendment_id},
        )
        run["status"] = "paused"
        run["outcome"] = None
        run["stop"] = stop.to_dict()
        self._store.save_run(self._run_id, run, expected_revision)
        self._append_event(
            "run_paused",
            amendment_id=amendment_id,
            stop=stop.to_dict(),
        )
        self._append_event("plan_amendment_started", amendment_id=amendment_id)
        return self._store.load_run(self._run_id)

    def _activate_amendment_execution(self) -> dict[str, Any]:
        """Resume active amendment orchestration after recording amendment_pending pause."""

        run = self._store.load_run(self._run_id)
        if str(run.get("status") or "") == "running" and run.get("stop") is None:
            return run
        expected_revision = int(run["revision"])
        run = dict(run)
        run["revision"] = expected_revision + 1
        run["status"] = "running"
        run["outcome"] = None
        run["stop"] = None
        self._store.save_run(self._run_id, run, expected_revision)
        return self._store.load_run(self._run_id)

    def _transition_to_whole_plan_review(self) -> dict[str, Any]:
        run = self._store.load_run(self._run_id)
        expected_revision = int(run["revision"])
        revoke_capabilities_for_phase(self._store, self._run_id, PLAN_AMENDMENT)
        run = dict(run)
        run["revision"] = expected_revision + 1
        run["phase"] = WHOLE_PLAN_REVIEW
        plan = self._store.load_plan(self._run_id)
        digests = dict(run.get("digests") or {})
        digests["plan"] = compute_plan_digest(plan)
        run["digests"] = digests
        self._store.save_run(self._run_id, run, expected_revision)
        self._append_event(
            "plan_amendment_revision_ready",
            plan_revision=int(plan["revision"]),
        )
        return self._store.load_run(self._run_id)

    def _resume_production_phase(self, plan_revision: int) -> dict[str, Any]:
        run = self._store.load_run(self._run_id)
        expected_revision = int(run["revision"])
        revoke_capabilities_for_phase(self._store, self._run_id, WHOLE_PLAN_REVIEW)
        run = dict(run)
        run["revision"] = expected_revision + 1
        run["phase"] = PRODUCTION
        run["status"] = "running"
        run["stop"] = None
        digests = dict(run.get("digests") or {})
        plan = self._store.load_plan(self._run_id)
        digests["plan"] = compute_plan_digest(plan)
        run["digests"] = digests
        self._store.save_run(self._run_id, run, expected_revision)
        self._append_event(
            "plan_amendment_production_resumed",
            approved_plan_revision=plan_revision,
        )
        return self._store.load_run(self._run_id)

    def _resume_planner_for_amendment(
        self,
        session_id: str,
        amendment: dict[str, Any],
    ) -> None:
        run = self._store.load_run(self._run_id)
        config = self._store.load_resolved_config(self._run_id)
        role_context = resolve_role_session_context(config, run, "planner")
        resume_primary_session_with_audit(
            self._append_event,
            self._provider,
            role="planner",
            phase=PLAN_AMENDMENT,
            session_id=session_id,
            request={
                "action": "revise_for_amendment",
                "phase": PLAN_AMENDMENT,
                "amendment_id": amendment.get("id"),
                "evidence": amendment.get("evidence"),
                "affected_refs": list(amendment.get("affected_refs") or []),
                "summary": amendment.get("summary"),
                "completion_signal": _AMENDMENT_REVISION_READY_SIGNAL,
            },
            model=role_context.model,
            amendment_id=amendment.get("id"),
        )

    def _consume_planner_turn(self, session_id: str) -> str | None:
        run = self._store.load_run(self._run_id)
        config = self._store.load_resolved_config(self._run_id)
        role_context = resolve_role_session_context(config, run, "planner")
        phase = str(run.get("phase") or PLAN_AMENDMENT)
        try:
            turn_outcome = consume_provider_turn_with_session_recovery(
                self._store,
                self._run_id,
                self._provider,
                session_id,
                allowed_signals=_COMPLETION_SIGNALS,
                recovery=build_planner_turn_recovery(
                    self._store,
                    self._run_id,
                    phase=phase,
                    expected_next_action="revise plan for pending amendment",
                    append_event=self._append_event,
                    model=role_context.model,
                ),
            )
        except SessionRecoveryPaused as exc:
            raise ProviderRunError(str(exc)) from exc
        session_id = turn_outcome.session_id
        signal = turn_outcome.signal
        sync_persisted_session_id(
            self._provider,
            self._store,
            self._run_id,
            session_id,
            field="primary_planner_session_id",
        )
        return signal

    def _persist_amendment_revision_cycles(
        self,
        amendment_id: str,
        revision_cycles: int,
    ) -> dict[str, Any]:
        production = self._store.load_production(self._run_id)
        expected_revision = int(production["revision"])
        requests = list(production.get("amendment_requests") or [])
        updated_requests: list[dict[str, Any]] = []
        amendment: dict[str, Any] | None = None
        for request in requests:
            if not isinstance(request, dict):
                continue
            if str(request.get("id") or "") != amendment_id:
                updated_requests.append(request)
                continue
            patched = dict(request)
            patched["revision_cycles"] = revision_cycles
            updated_requests.append(patched)
            amendment = patched
        if amendment is None:
            raise ProviderRunError(f"amendment request not found: {amendment_id}")

        updated = dict(production)
        updated["revision"] = expected_revision + 1
        updated["amendment_requests"] = updated_requests
        self._store.save_production(self._run_id, updated, expected_revision)
        return amendment

    def _pause_for_amendment_limit(
        self,
        *,
        message: str,
        limit: str,
        consumed: int,
        configured: int,
        amendment_id: str,
        planner_session_id: str,
        producer_session_id: str,
    ) -> PlanAmendmentResult:
        pause_for_limit_exhausted(
            self._store,
            self._run_id,
            phase=PLAN_AMENDMENT,
            message=message,
            limit=limit,
            consumed=consumed,
            configured=configured,
            role="planner",
            revoke_phase=PLAN_AMENDMENT,
            amendment_id=amendment_id,
        )
        self._append_event(
            "plan_amendment_limit_exceeded",
            amendment_id=amendment_id,
            limit=limit,
            message=message,
        )
        run = self._store.load_run(self._run_id)
        return PlanAmendmentResult(
            ok=False,
            phase=str(run.get("phase") or PLAN_AMENDMENT),
            status=str(run.get("status") or "paused"),
            outcome=None,
            amendment_id=amendment_id,
            planner_session_id=planner_session_id,
            producer_session_id=producer_session_id,
            reason=message,
        )

    def _terminate(
        self,
        outcome: str,
        message: str,
        *,
        amendment_id: str,
        planner_session_id: str,
        producer_session_id: str,
    ) -> PlanAmendmentResult:
        complete_run_with_outcome(
            self._store,
            self._run_id,
            outcome,
            revoke_phase=PLAN_AMENDMENT,
            event_type="plan_amendment_failed",
            amendment_id=amendment_id,
            message=message,
        )
        run = self._store.load_run(self._run_id)
        return PlanAmendmentResult(
            ok=False,
            phase=str(run.get("phase") or PLAN_AMENDMENT),
            status=str(run.get("status") or "completed"),
            outcome=outcome,
            amendment_id=amendment_id,
            planner_session_id=planner_session_id,
            producer_session_id=producer_session_id,
            reason=message,
        )

    def _append_event(self, event_type: str, **fields: Any) -> None:
        payload = {"type": event_type, "run_id": self._run_id, **fields}
        self._store.append_event(self._run_id, payload)


def _require_prior_plan_snapshot(amendment: dict[str, Any]) -> Any:
    from top_down_planning.domain.models import Plan

    snapshot = amendment.get("prior_plan_snapshot")
    if not isinstance(snapshot, dict):
        raise ProviderRunError(
            "amendment is missing prior_plan_snapshot; "
            "cannot reconcile production evidence"
        )
    return Plan.from_dict(snapshot)


def _amendment_revision_limit(config: dict[str, Any]) -> int:
    amendment_limits = (config.get("limits") or {}).get("amendment") or {}
    return int(
        amendment_limits.get(
            "max_revision_cycles_per_request",
            _AMENDMENT_LIMIT_DEFAULTS["max_revision_cycles_per_request"],
        )
    )


def _find_amendment_request(
    production: dict[str, Any],
    amendment_id: str,
) -> dict[str, Any] | None:
    for request in production.get("amendment_requests") or []:
        if not isinstance(request, dict):
            continue
        if str(request.get("id") or "") == amendment_id:
            return request
    return None

