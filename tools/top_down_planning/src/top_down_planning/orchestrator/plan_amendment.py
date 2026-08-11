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
    adopt_replacement_capability,
    bind_provider_capability,
    issue_session_capability,
    rebind_primary_session_capability,
    rotate_session_capability,
)
from top_down_planning.orchestrator.run_transitions import (
    complete_run_with_outcome,
    pause_for_limit_exhausted,
    reconcile_pending_capability_revocation,
)
from top_down_planning.persistence.commit import CommitSpec
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
from top_down_planning.orchestrator.agent_context import resolve_activity_session_context
from top_down_planning.orchestrator.activity_context import (
    session_continuation_decision,
)
from top_down_planning.orchestrator.session_context import (
    ensure_primary_session,
    rotate_primary_session,
)
from top_down_planning.domain.session_bindings import new_session_binding
from top_down_planning.persistence.session_bindings import get_primary_binding
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
            revision_cycles = int(amendment.get("revision_cycles") or 0)
            config = self._store.load_resolved_config(self._run_id)
            max_revision_cycles = _amendment_revision_limit(config)
            planner_session_id = self._resume_planner_for_amendment(amendment)
            for record in self._store.list_capabilities(self._run_id):
                if record.get("revoked") is True:
                    continue
                capability_id = str(record.get("id") or "")
                if capability_id:
                    self._store.revoke_capability(self._run_id, capability_id)
            from top_down_planning.persistence.capabilities import clear_capability_token_file

            clear_capability_token_file(self._store, self._run_id)
            rebound = rebind_primary_session_capability(
                self._store,
                self._run_id,
                self._provider,
                role="planner",
            )
            if rebound is None:
                raise ProviderRunError("failed to rebind planner capability for amendment")
            self._capability_token = rebound
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
                planner_session_id = self._resume_planner_for_amendment(amendment)
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
                bind_provider_capability(self._provider, self._capability_token, store=self._store, run_id=self._run_id)

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
        production_expected = int(production["revision"])
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
        production_payload = dict(production)
        production_payload["revision"] = production_expected + 1
        production_payload["amendment_requests"] = updated_requests

        run = self._store.load_run(self._run_id)
        run_expected = int(run["revision"])
        source_phase = str(run.get("phase") or "")
        stop = StopRecord(
            code="amendment_pending",
            category="operational",
            phase=PLAN_AMENDMENT,
            message="plan amendment requested",
            details={"pending_amendment_id": amendment_id},
        )
        run_payload = dict(run)
        run_payload["revision"] = run_expected + 1
        run_payload["phase"] = PLAN_AMENDMENT
        run_payload["status"] = "paused"
        run_payload["outcome"] = None
        run_payload["stop"] = stop.to_dict()
        if source_phase:
            run_payload["pending_capability_revoke_phase"] = source_phase
        self._store.commit(
            self._run_id,
            CommitSpec(
                run=run_payload,
                run_expected_revision=run_expected,
                production=production_payload,
                production_expected_revision=production_expected,
                events=[
                    {
                        "type": "run_paused",
                        "run_id": self._run_id,
                        "amendment_id": amendment_id,
                        "stop": stop.to_dict(),
                    },
                    {
                        "type": "plan_amendment_started",
                        "run_id": self._run_id,
                        "amendment_id": amendment_id,
                    },
                ],
            ),
        )
        if source_phase:
            reconcile_pending_capability_revocation(self._store, self._run_id)
        return self._store.load_run(self._run_id)

    def _activate_amendment_execution(self) -> dict[str, Any]:
        """Resume active amendment orchestration after recording amendment_pending pause."""

        run = self._store.load_run(self._run_id)
        status = str(run.get("status") or "")
        if status == "running" and run.get("stop") is None:
            return run
        if status in {"completed", "failed"}:
            raise ProviderRunError(f"cannot activate amendment from {status} run")

        production = self._store.load_production(self._run_id)
        pending_id = str(production.get("pending_amendment_id") or "").strip()
        prior_stop = run.get("stop")
        if status != "paused" or not isinstance(prior_stop, dict):
            raise ProviderRunError("run is not paused for plan amendment")
        stop_code = str(prior_stop.get("code") or "")
        if stop_code != "amendment_pending":
            raise ProviderRunError(
                f"cannot activate amendment from stop code {stop_code!r}"
            )
        details = prior_stop.get("details") or {}
        if str(details.get("pending_amendment_id") or "") != pending_id:
            raise ProviderRunError(
                "amendment_pending stop does not match production pending amendment"
            )

        expected_revision = int(run["revision"])
        prior_status = status
        prior_phase = str(run.get("phase") or "")
        run_payload = dict(run)
        run_payload["revision"] = expected_revision + 1
        run_payload["status"] = "running"
        run_payload["outcome"] = None
        run_payload["stop"] = None
        run_payload["pending_capability_revoke_all"] = True
        events: list[dict[str, Any]] = []
        if prior_status == "paused" and isinstance(prior_stop, dict):
            events.append(
                {
                    "type": "amendment_execution_resumed",
                    "run_id": self._run_id,
                    "expected_revision": expected_revision,
                    "resulting_revision": expected_revision + 1,
                    "phase": prior_phase,
                    "prior_status": prior_status,
                    "prior_stop": prior_stop,
                }
            )
        self._store.commit(
            self._run_id,
            CommitSpec(
                run=run_payload,
                run_expected_revision=expected_revision,
                events=events,
            ),
        )
        reconcile_pending_capability_revocation(self._store, self._run_id)
        return self._store.load_run(self._run_id)

    def _transition_to_whole_plan_review(self) -> dict[str, Any]:
        run = self._store.load_run(self._run_id)
        expected_revision = int(run["revision"])
        plan = self._store.load_plan(self._run_id)
        run_payload = dict(run)
        run_payload["revision"] = expected_revision + 1
        run_payload["phase"] = WHOLE_PLAN_REVIEW
        run_payload["pending_capability_revoke_phase"] = PLAN_AMENDMENT
        digests = dict(run_payload.get("digests") or {})
        digests["plan"] = compute_plan_digest(plan)
        run_payload["digests"] = digests
        self._store.commit(
            self._run_id,
            CommitSpec(
                run=run_payload,
                run_expected_revision=expected_revision,
                events=[
                    {
                        "type": "plan_amendment_revision_ready",
                        "run_id": self._run_id,
                        "plan_revision": int(plan["revision"]),
                    }
                ],
            ),
        )
        reconcile_pending_capability_revocation(self._store, self._run_id)
        return self._store.load_run(self._run_id)

    def _resume_production_phase(self, plan_revision: int) -> dict[str, Any]:
        run = self._store.load_run(self._run_id)
        expected_revision = int(run["revision"])
        plan = self._store.load_plan(self._run_id)
        run_payload = dict(run)
        run_payload["revision"] = expected_revision + 1
        run_payload["phase"] = PRODUCTION
        run_payload["status"] = "running"
        run_payload["stop"] = None
        run_payload["pending_capability_revoke_phase"] = WHOLE_PLAN_REVIEW
        digests = dict(run_payload.get("digests") or {})
        digests["plan"] = compute_plan_digest(plan)
        run_payload["digests"] = digests
        self._store.commit(
            self._run_id,
            CommitSpec(
                run=run_payload,
                run_expected_revision=expected_revision,
                events=[
                    {
                        "type": "plan_amendment_production_resumed",
                        "run_id": self._run_id,
                        "approved_plan_revision": plan_revision,
                    }
                ],
            ),
        )
        reconcile_pending_capability_revocation(self._store, self._run_id)
        rebind_primary_session_capability(
            self._store,
            self._run_id,
            self._provider,
            role="producer",
        )
        return self._store.load_run(self._run_id)

    def _resume_planner_for_amendment(
        self,
        amendment: dict[str, Any],
    ) -> str:
        run = self._store.load_run(self._run_id)
        config = self._store.load_resolved_config(self._run_id)
        activity_context = resolve_activity_session_context(
            config,
            run,
            "planner",
            "plan_amendment",
        )
        from top_down_planning.orchestrator.planning import build_planner_context_manifest

        manifest = build_planner_context_manifest(
            self._run_id,
            run,
            config,
            self._store.load_plan_model(self._run_id),
            activity="plan_amendment",
        )
        manifest.update(
            {
                "amendment_id": amendment.get("id"),
                "evidence": amendment.get("evidence"),
                "affected_refs": list(amendment.get("affected_refs") or []),
                "summary": amendment.get("summary"),
                "completion_signal": _AMENDMENT_REVISION_READY_SIGNAL,
            }
        )
        amendment_request = {
            "action": "revise_for_amendment",
            "phase": PLAN_AMENDMENT,
            "amendment_id": amendment.get("id"),
            "evidence": amendment.get("evidence"),
            "affected_refs": list(amendment.get("affected_refs") or []),
            "summary": amendment.get("summary"),
            "completion_signal": _AMENDMENT_REVISION_READY_SIGNAL,
        }
        binding = get_primary_binding(run, "planner")
        decision_source = binding or new_session_binding(
            role="planner",
            kind="primary",
            state="unbound",
        )
        decision = session_continuation_decision(decision_source, activity_context)

        if (
            binding is not None
            and decision == "resume"
            and binding.provider_session_id is not None
        ):
            return ensure_primary_session(
                self._store,
                self._run_id,
                self._provider,
                role="planner",
                phase=PLAN_AMENDMENT,
                requested=activity_context,
                manifest=manifest,
                append_event=self._append_event,
                resume_request=amendment_request,
            )

        if (
            binding is not None
            and binding.state == "bound"
            and binding.provider_session_id is not None
        ):
            return rotate_primary_session(
                self._store,
                self._run_id,
                self._provider,
                role="planner",
                phase=PLAN_AMENDMENT,
                old_provider_session_id=binding.provider_session_id,
                requested=activity_context,
                manifest=manifest,
                append_event=self._append_event,
                handoff_request=amendment_request,
            )

        return ensure_primary_session(
            self._store,
            self._run_id,
            self._provider,
            role="planner",
            phase=PLAN_AMENDMENT,
            requested=activity_context,
            manifest=manifest,
            append_event=self._append_event,
            resume_request=amendment_request,
        )

    def _consume_planner_turn(self, session_id: str) -> str | None:
        run = self._store.load_run(self._run_id)
        config = self._store.load_resolved_config(self._run_id)
        role_context = resolve_activity_session_context(
            config,
            run,
            "planner",
            "plan_amendment",
        )
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
                    activity="plan_amendment",
                ),
            )
        except SessionRecoveryPaused:
            raise
        if turn_outcome.replaced:
            self._capability_token = adopt_replacement_capability(
                self._store,
                self._run_id,
                current_token=self._capability_token,
                replacement_token=turn_outcome.capability_token,
                provider=self._provider,
            )
        return turn_outcome.signal

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
            limit=f"limits.amendment.{limit}",
            consumed=consumed,
            configured=configured,
            role="planner",
            revoke_phase=PLAN_AMENDMENT,
            amendment_id=amendment_id,
            additional_events=[
                {
                    "type": "plan_amendment_limit_exceeded",
                    "amendment_id": amendment_id,
                    "limit": limit,
                    "message": message,
                }
            ],
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

