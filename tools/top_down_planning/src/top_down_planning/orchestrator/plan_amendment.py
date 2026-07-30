"""Controlled plan-amendment orchestration (proposal §10.4, §13)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from top_down_planning.agent_tool.plan_service import PlanAgentService
from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.domain.reconciliation import (
    apply_reconciliation,
    build_reconciliation_report,
)
from top_down_planning.domain.reviews import find_whole_plan_approval
from top_down_planning.orchestrator.capability import (
    bind_provider_capability,
    issue_session_capability,
)
from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.orchestrator.phases import (
    PLAN_AMENDMENT,
    PLAN_VALIDATED,
    PRODUCTION,
    WHOLE_PLAN_REVIEW,
)
from top_down_planning.orchestrator.whole_plan_review import WholePlanReviewOrchestrator
from top_down_planning.persistence.digests import compute_plan_digest
from top_down_planning.persistence.interface import RunStore
from core_tools.provider import Provider

_AMENDMENT_LIMIT_DEFAULTS = DEFAULT_CONFIG["limits"]["amendment"]
_AMENDMENT_REVISION_READY_SIGNAL = "amendment_revision_ready"


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
        self._plan_service = PlanAgentService(store, run_id)
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

        planner_session_id = _primary_planner_session_id(run)
        producer_session_id = _primary_producer_session_id(run)
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
            run = self._store.load_run(self._run_id)
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
                    return self._terminate(
                        "blocked",
                        (
                            "plan amendment exceeded max_revision_cycles_per_request "
                            f"({max_revision_cycles})"
                        ),
                        amendment_id=amendment_id,
                        planner_session_id=planner_session_id,
                        producer_session_id=producer_session_id,
                    )
                self._resume_planner_for_amendment(
                    planner_session_id,
                    amendment,
                )

            run = self._transition_to_whole_plan_review()

        phase = str(run.get("phase") or "")
        if phase in {WHOLE_PLAN_REVIEW, PLAN_VALIDATED}:
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
        run = dict(run)
        run["revision"] = expected_revision + 1
        run["phase"] = PLAN_AMENDMENT
        run["status"] = "paused"
        self._store.save_run(self._run_id, run, expected_revision)
        self._append_event("plan_amendment_started", amendment_id=amendment_id)
        return self._store.load_run(self._run_id)

    def _transition_to_whole_plan_review(self) -> dict[str, Any]:
        run = self._store.load_run(self._run_id)
        expected_revision = int(run["revision"])
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
        run = dict(run)
        run["revision"] = expected_revision + 1
        run["phase"] = PRODUCTION
        run["status"] = "running"
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
        self._provider.resume_primary_session(
            session_id,
            {
                "action": "revise_for_amendment",
                "phase": PLAN_AMENDMENT,
                "amendment_id": amendment.get("id"),
                "evidence": amendment.get("evidence"),
                "affected_refs": list(amendment.get("affected_refs") or []),
                "summary": amendment.get("summary"),
                "completion_signal": _AMENDMENT_REVISION_READY_SIGNAL,
            },
        )

    def _consume_planner_turn(self, session_id: str) -> str | None:
        signal: str | None = None
        for event in self._provider.stream_events(session_id):
            event_type = str(event.get("type") or "")
            if event_type == "error":
                text = event.get("text") or "provider error"
                raise ProviderRunError(str(text))
            if event_type == "tool_call":
                self._handle_plan_tool_call(event)
                continue
            if event_type == "done":
                if event.get("is_error"):
                    text = event.get("text") or "planner amendment turn failed"
                    raise ProviderRunError(str(text))
                signal = event.get("signal")
                if signal is not None:
                    signal = str(signal)
        return signal

    def _handle_plan_tool_call(self, event: dict[str, Any]) -> None:
        tool = str(event.get("tool") or "")
        if tool != "plan_apply":
            return

        request = event.get("request")
        if not isinstance(request, dict):
            raise ProviderRunError("plan_apply tool_call requires a request object")

        self._plan_service.apply(request, capability_token=self._capability_token)

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

    def _terminate(
        self,
        outcome: str,
        message: str,
        *,
        amendment_id: str,
        planner_session_id: str,
        producer_session_id: str,
    ) -> PlanAmendmentResult:
        run = self._store.load_run(self._run_id)
        expected_revision = int(run["revision"])
        run = dict(run)
        run["revision"] = expected_revision + 1
        run["status"] = "completed"
        run["outcome"] = outcome
        self._store.save_run(self._run_id, run, expected_revision)
        self._append_event(
            "plan_amendment_failed",
            amendment_id=amendment_id,
            outcome=outcome,
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


def _primary_planner_session_id(run: dict[str, Any]) -> str | None:
    sessions = run.get("sessions") or {}
    session_id = sessions.get("primary_planner_session_id")
    if session_id is None:
        return None
    return str(session_id)


def _primary_producer_session_id(run: dict[str, Any]) -> str | None:
    sessions = run.get("sessions") or {}
    session_id = sessions.get("primary_producer_session_id")
    if session_id is None:
        return None
    return str(session_id)
