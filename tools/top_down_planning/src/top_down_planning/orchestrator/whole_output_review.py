"""Whole-output review orchestration and outcome resolution (proposal §5.3, §11–§12.2, §15, §21)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from top_down_planning.agent_tool.config import planning_limits_from_config
from top_down_planning.agent_tool.errors import AgentToolError
from top_down_planning.agent_tool.production_service import ProductionAgentService
from top_down_planning.agent_tool.review_service import ReviewAgentService
from top_down_planning.config import compute_input_digest, compute_output_goal_digest
from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.domain.outcome import (
    evaluate_acceptance_invariant,
    load_approvals_for_acceptance,
    resolve_quality_outcome,
)
from top_down_planning.domain.production import build_production_review_snapshot
from top_down_planning.domain.reviews import ReviewLoop, find_whole_plan_approval
from top_down_planning.orchestrator.agent_context import (
    attach_role_context_to_manifest,
    resolve_role_session_context,
)
from top_down_planning.orchestrator.capability import (
    bind_provider_capability,
    bind_reviewer_capability,
    issue_session_capability,
    revoke_capabilities_for_loop,
    revoke_capabilities_for_phase,
    rotate_session_capability,
)
from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.orchestrator.phases import OUTPUT_VALIDATED, WHOLE_OUTPUT_REVIEW
from top_down_planning.workspace import run_workspace
from top_down_planning.persistence.digests import (
    compute_config_digest,
    compute_output_digest,
    compute_plan_digest,
)
from top_down_planning.persistence.interface import RunStore
from core_tools.provider import Provider

_WHOLE_OUTPUT_LIMIT_DEFAULTS = DEFAULT_CONFIG["limits"]["whole_output_review"]

_PRODUCTION_TOOL_HANDLERS: dict[str, str] = {
    "production_apply": "apply",
    "production_submit_completion": "submit_completion",
    "production_report_blocked": "report_blocked",
}


@dataclass(frozen=True)
class WholeOutputReviewResult:
    ok: bool
    phase: str
    status: str
    outcome: str | None
    loop_id: str | None
    reviewer_session_id: str | None
    revision_cycles: int
    reason: str | None = None


class WholeOutputReviewOrchestrator:
    """Drive mandatory whole-output review and orchestrator-owned final outcomes."""

    def __init__(
        self,
        store: RunStore,
        run_id: str,
        provider: Provider,
    ) -> None:
        self._store = store
        self._run_id = run_id
        self._provider = provider
        self._review_service = ReviewAgentService(store, run_id)
        self._production_service = ProductionAgentService(store, run_id)
        self._capability_token: str | None = None

    def run(self) -> WholeOutputReviewResult:
        run = self._store.load_run(self._run_id)
        phase = str(run.get("phase") or "")
        if phase == OUTPUT_VALIDATED:
            return self._result_from_run(run, ok=True)
        if phase != WHOLE_OUTPUT_REVIEW:
            raise ProviderRunError(f"run is not in whole-output review phase: {phase}")

        self._require_completion_claim()
        self._require_plan_approval()

        config = self._store.load_resolved_config(self._run_id)
        max_revision_cycles = _whole_output_revision_limit(config)
        loop = self._normalize_loop_for_resume(self._get_or_create_active_loop())

        while True:
            if loop.status == "pending":
                session_id = loop.reviewer_session_id
                if session_id is None:
                    session_id = self._start_reviewer_session(loop)
                    loop = self._reload_loop(loop.id)
                else:
                    run = self._store.load_run(self._run_id)
                    phase = str(run.get("phase") or WHOLE_OUTPUT_REVIEW)
                    self._capability_token = bind_reviewer_capability(
                        self._store,
                        self._run_id,
                        self._provider,
                        session_id=session_id,
                        phase=phase,
                        loop_id=loop.id,
                    )
                decision = self._consume_reviewer_turn(session_id, loop.id)
                loop = self._reload_loop(loop.id)
                if decision is None:
                    raise ProviderRunError("reviewer turn completed without a decision")
                if loop.status == "pending":
                    run = self._store.load_run(self._run_id)
                    phase = str(run.get("phase") or WHOLE_OUTPUT_REVIEW)
                    self._capability_token = rotate_session_capability(
                        self._store,
                        self._run_id,
                        current_token=self._capability_token,
                        role="reviewer",
                        phase=phase,
                        session_id=session_id,
                        session_kind="reviewer",
                        loop_id=loop.id,
                    )
                    bind_provider_capability(self._provider, self._capability_token)
            else:
                decision = loop.status

            if decision == "approved":
                return self._complete_with_approval(loop)

            if decision == "blocked":
                revoke_capabilities_for_loop(self._store, self._run_id, loop.id)
                return self._terminate("blocked", "whole-output reviewer blocked the run")

            if decision != "changes_requested":
                raise ProviderRunError(f"unexpected review decision: {decision}")

            revision_cycles = loop.revision_cycles + 1
            loop = self._persist_loop(
                ReviewLoop(
                    id=loop.id,
                    type=loop.type,
                    reviewer_session_id=loop.reviewer_session_id,
                    target_revision=loop.target_revision,
                    scope=loop.scope,
                    status="pending",
                    findings=loop.findings,
                    revision_cycles=revision_cycles,
                )
            )

            if revision_cycles >= max_revision_cycles:
                return self._terminate(
                    "rejected",
                    (
                        "whole-output review exceeded max_revision_cycles "
                        f"({max_revision_cycles})"
                    ),
                )

            self._resume_producer_with_findings(loop)
            loop = self._prepare_recheck(loop)

    def _complete_with_approval(self, loop: ReviewLoop) -> WholeOutputReviewResult:
        plan = self._store.load_plan_model(self._run_id)
        production = self._store.load_production(self._run_id)
        run = self._store.load_run(self._run_id)
        config = self._store.load_resolved_config(self._run_id)
        limits = planning_limits_from_config(config)
        reviews = self._store.list_reviews(self._run_id)

        plan_approval, output_approval = load_approvals_for_acceptance(
            reviews,
            plan_revision=plan.revision,
            output_revision=int(production["output_revision"]),
        )
        if output_approval is None:
            return self._terminate(
                "blocked",
                "whole-output approval record missing for current output revision",
            )

        invariant, plan_validation, output_validation = evaluate_acceptance_invariant(
            plan=plan,
            production=production,
            reviews=reviews,
            limits=limits,
            plan_approval=plan_approval,
            output_approval=output_approval,
            actual_plan_digest=compute_plan_digest(plan),
            actual_config_digest=compute_config_digest(config),
            actual_output_digest=compute_output_digest(production),
            actual_input_digest=compute_input_digest(
                config,
                base_dir=run_workspace(run),
            ),
            actual_output_goal_digest=compute_output_goal_digest(
                config,
                base_dir=run_workspace(run),
            ),
            actual_context_digest=(run.get("digests") or {}).get("context"),
        )

        if not plan_validation.ok:
            return self._terminate(
                "blocked",
                "deterministic plan validation failed after whole-output approval",
            )

        if not output_validation.ok:
            return self._terminate(
                "blocked",
                "deterministic output validation failed after whole-output approval",
            )

        outcome = resolve_quality_outcome(invariant)
        if outcome != "accepted":
            return self._terminate(
                outcome,
                "acceptance invariant was not satisfied after whole-output approval",
            )

        expected_revision = int(run["revision"])
        revoke_capabilities_for_loop(self._store, self._run_id, loop.id)
        revoke_capabilities_for_phase(self._store, self._run_id, WHOLE_OUTPUT_REVIEW)
        run = dict(run)
        run["revision"] = expected_revision + 1
        run["phase"] = OUTPUT_VALIDATED
        run["status"] = "completed"
        run["outcome"] = outcome
        self._store.save_run(self._run_id, run, expected_revision)
        self._append_event(
            "whole_output_review_approved",
            loop_id=loop.id,
            target_revision=int(production["output_revision"]),
            reviewer_session_id=loop.reviewer_session_id,
            outcome=outcome,
        )
        self._append_event(
            "outcome_resolved",
            outcome=outcome,
            acceptance_invariant=invariant.to_dict(),
        )
        run = self._store.load_run(self._run_id)
        return self._result_from_run(run, ok=True, loop=loop)

    def _terminate(
        self,
        outcome: str,
        message: str,
    ) -> WholeOutputReviewResult:
        revoke_capabilities_for_phase(self._store, self._run_id, WHOLE_OUTPUT_REVIEW)
        run = self._store.load_run(self._run_id)
        expected_revision = int(run["revision"])
        run = dict(run)
        run["revision"] = expected_revision + 1
        run["status"] = "completed"
        run["outcome"] = outcome
        self._store.save_run(self._run_id, run, expected_revision)
        self._append_event(
            "whole_output_review_failed",
            outcome=outcome,
            message=message,
        )
        run = self._store.load_run(self._run_id)
        return self._result_from_run(run, ok=False, reason=message)

    def _normalize_loop_for_resume(self, loop: ReviewLoop) -> ReviewLoop:
        if loop.status != "changes_requested":
            return loop

        output_revision = int(self._store.load_production(self._run_id)["output_revision"])
        if output_revision <= loop.target_revision:
            return loop

        return self._prepare_recheck(loop)

    def _get_or_create_active_loop(self) -> ReviewLoop:
        for payload in reversed(self._store.list_reviews(self._run_id)):
            if payload.get("type") != "whole_output":
                continue
            loop = ReviewLoop.from_dict(payload)
            if loop.status in {"approved", "blocked"}:
                continue
            return loop
        return self._create_loop()

    def _create_loop(self) -> ReviewLoop:
        output_revision = int(self._store.load_production(self._run_id)["output_revision"])
        loop_id = self._next_loop_id()
        loop = ReviewLoop(
            id=loop_id,
            type="whole_output",
            reviewer_session_id=None,
            target_revision=output_revision,
            scope={"kind": "whole_output"},
            status="pending",
        )
        self._store.save_review(self._run_id, loop.to_dict())
        self._append_event(
            "whole_output_review_started",
            loop_id=loop_id,
            target_revision=output_revision,
        )
        return loop

    def _next_loop_id(self) -> str:
        existing = [
            payload.get("id")
            for payload in self._store.list_reviews(self._run_id)
            if payload.get("type") == "whole_output" and payload.get("id")
        ]
        index = len(existing) + 1
        return f"review-whole-output-{index:02d}"

    def _start_reviewer_session(self, loop: ReviewLoop) -> str:
        run = self._store.load_run(self._run_id)
        config = self._store.load_resolved_config(self._run_id)
        package = build_whole_output_review_package(
            self._run_id,
            run,
            config,
            self._store.load_plan_model(self._run_id),
            self._store.load_production(self._run_id),
            loop,
        )
        role_context = resolve_role_session_context(config, run, "reviewer")
        session_id = self._provider.start_reviewer_session(
            package,
            model=role_context.model,
        )
        updated = ReviewLoop(
            id=loop.id,
            type=loop.type,
            reviewer_session_id=session_id,
            target_revision=loop.target_revision,
            scope=loop.scope,
            status=loop.status,
            findings=loop.findings,
            revision_cycles=loop.revision_cycles,
            approved_digests=loop.approved_digests,
        )
        self._persist_loop(updated)
        run = self._store.load_run(self._run_id)
        phase = str(run.get("phase") or WHOLE_OUTPUT_REVIEW)
        self._capability_token = issue_session_capability(
            self._store,
            self._run_id,
            role="reviewer",
            phase=phase,
            session_id=session_id,
            session_kind="reviewer",
            loop_id=loop.id,
        )
        bind_provider_capability(self._provider, self._capability_token)
        self._append_event(
            "reviewer_session_started",
            loop_id=loop.id,
            session_id=session_id,
            role="reviewer",
            phase=phase,
        )
        return session_id

    def _consume_reviewer_turn(self, session_id: str, loop_id: str) -> str | None:
        decision: str | None = None
        for event in self._provider.stream_events(session_id):
            event_type = str(event.get("type") or "")
            if event_type == "error":
                text = event.get("text") or "provider error"
                raise ProviderRunError(str(text))
            if event_type == "tool_call":
                self._handle_review_tool_call(event, loop_id)
                loop = self._reload_loop(loop_id)
                if loop.status != "pending":
                    decision = loop.status
                continue
            if event_type == "done":
                if event.get("is_error"):
                    text = event.get("text") or "reviewer turn failed"
                    raise ProviderRunError(str(text))
        return decision

    def _handle_review_tool_call(self, event: dict[str, Any], loop_id: str) -> None:
        tool = str(event.get("tool") or "")
        if tool != "review_respond":
            return

        request = event.get("request")
        if not isinstance(request, dict):
            raise ProviderRunError("review_respond tool_call requires a request object")

        request = dict(request)
        request.setdefault("loop_id", loop_id)
        self._review_service.respond(
            request,
            capability_token=self._capability_token,
        )

    def _resume_producer_with_findings(self, loop: ReviewLoop) -> None:
        run = self._store.load_run(self._run_id)
        session_id = _primary_producer_session_id(run)
        if session_id is None:
            raise ProviderRunError("primary producer session is missing for revision")

        run = self._store.load_run(self._run_id)
        phase = str(run.get("phase") or WHOLE_OUTPUT_REVIEW)
        self._capability_token = issue_session_capability(
            self._store,
            self._run_id,
            role="producer",
            phase=phase,
            session_id=session_id,
            session_kind="primary",
        )
        bind_provider_capability(self._provider, self._capability_token)

        self._provider.resume_primary_session(
            session_id,
            {
                "action": "address_review_findings",
                "phase": WHOLE_OUTPUT_REVIEW,
                "loop_id": loop.id,
                "target_revision": loop.target_revision,
                "findings": [finding.to_dict() for finding in loop.findings],
                "revision_instructions": {
                    "apply_mode": "evidence_revision",
                    "evidence_revision": True,
                    "tool": "production_apply",
                    "notes": (
                        "Set evidence_revision: true on production apply for terminal "
                        "plan_items targeted by unresolved blocking findings. Keep "
                        "existing dispositions unchanged; attach new outputs or "
                        "contributions. Then submit-completion with goal_met: true."
                    ),
                },
            },
        )
        self._consume_producer_turn(session_id)
        self._sync_output_digest()

    def _sync_output_digest(self) -> None:
        run = self._store.load_run(self._run_id)
        production = self._store.load_production(self._run_id)
        expected_revision = int(run["revision"])
        run = dict(run)
        run["revision"] = expected_revision + 1
        digests = dict(run.get("digests") or {})
        digests["output"] = compute_output_digest(production)
        run["digests"] = digests
        self._store.save_run(self._run_id, run, expected_revision)

    def _consume_producer_turn(self, session_id: str) -> None:
        for event in self._provider.stream_events(session_id):
            event_type = str(event.get("type") or "")
            if event_type == "error":
                text = event.get("text") or "provider error"
                raise ProviderRunError(str(text))
            if event_type == "tool_call":
                self._handle_production_tool_call(event)
                continue
            if event_type == "done":
                if event.get("is_error"):
                    text = event.get("text") or "producer revision turn failed"
                    raise ProviderRunError(str(text))
                return

    def _handle_production_tool_call(self, event: dict[str, Any]) -> None:
        tool = str(event.get("tool") or "")
        if tool == "plan_apply":
            raise ProviderRunError(
                "plan mutations are not allowed during whole-output review; "
                "address reviewer findings with production apply (evidence_revision: true) "
                "or report blocked"
            )

        if tool == "production_request_amendment":
            raise ProviderRunError(
                "plan amendment is not allowed during whole-output review; "
                "address reviewer findings with production apply (evidence_revision: true) "
                "or report blocked"
            )

        handler_name = _PRODUCTION_TOOL_HANDLERS.get(tool)
        if handler_name is None:
            return

        request = event.get("request")
        if not isinstance(request, dict):
            raise ProviderRunError(f"{tool} tool_call requires a request object")

        handler = getattr(self._production_service, handler_name)
        try:
            handler(request, capability_token=self._capability_token)
        except AgentToolError as exc:
            raise ProviderRunError(str(exc)) from exc

    def _prepare_recheck(self, loop: ReviewLoop) -> ReviewLoop:
        output_revision = int(self._store.load_production(self._run_id)["output_revision"])
        session_id = loop.reviewer_session_id
        if session_id is None:
            raise ProviderRunError("reviewer session is missing for recheck")

        updated = ReviewLoop(
            id=loop.id,
            type=loop.type,
            reviewer_session_id=session_id,
            target_revision=output_revision,
            scope=loop.scope,
            status="pending",
            findings=loop.findings,
            revision_cycles=loop.revision_cycles,
            approved_digests=None,
        )
        self._persist_loop(updated)
        self._provider.send(
            session_id,
            {
                "action": "recheck_revision",
                "phase": WHOLE_OUTPUT_REVIEW,
                "loop_id": loop.id,
                "target_revision": output_revision,
            },
        )
        return updated

    def _persist_loop(self, loop: ReviewLoop) -> ReviewLoop:
        self._store.save_review(self._run_id, loop.to_dict())
        return loop

    def _reload_loop(self, loop_id: str) -> ReviewLoop:
        return ReviewLoop.from_dict(self._store.load_review(self._run_id, loop_id))

    def _result_from_run(
        self,
        run: dict[str, Any],
        *,
        ok: bool,
        loop: ReviewLoop | None = None,
        reason: str | None = None,
    ) -> WholeOutputReviewResult:
        return WholeOutputReviewResult(
            ok=ok,
            phase=str(run.get("phase") or WHOLE_OUTPUT_REVIEW),
            status=str(run.get("status") or "running"),
            outcome=run.get("outcome"),
            loop_id=loop.id if loop is not None else None,
            reviewer_session_id=loop.reviewer_session_id if loop is not None else None,
            revision_cycles=loop.revision_cycles if loop is not None else 0,
            reason=reason,
        )

    def _append_event(self, event_type: str, **fields: Any) -> None:
        payload = {"type": event_type, "run_id": self._run_id, **fields}
        self._store.append_event(self._run_id, payload)

    def _require_completion_claim(self) -> None:
        production = self._store.load_production(self._run_id)
        claim = production.get("completion_claim")
        if not isinstance(claim, dict):
            raise ProviderRunError(
                "whole-output review requires a production completion claim"
            )

    def _require_plan_approval(self) -> None:
        plan = self._store.load_plan_model(self._run_id)
        approval = find_whole_plan_approval(
            self._store.list_reviews(self._run_id),
            plan.revision,
        )
        if approval is None:
            raise ProviderRunError(
                "whole-output review requires an approved whole-plan review "
                "for the current plan revision"
            )


def build_whole_output_review_package(
    run_id: str,
    run: dict[str, Any],
    config: dict[str, Any],
    plan: Any,
    production: dict[str, Any],
    loop: ReviewLoop,
) -> dict[str, Any]:
    """Package a bounded whole-output review for a fresh reviewer session."""

    run_section = config.get("run") or {}
    digests = dict(run.get("digests") or {})
    return attach_role_context_to_manifest(
        {
        "run_id": run_id,
        "phase": WHOLE_OUTPUT_REVIEW,
        "type": "whole_output",
        "loop_id": loop.id,
        "purpose": "Mandatory whole-output review before final outcome",
        "scope": dict(loop.scope),
        "target_revision": loop.target_revision,
        "output_revision": int(production["output_revision"]),
        "production": build_production_review_snapshot(production),
        "input_refs": list(run_section.get("input_refs") or []),
        "output_goal": plan.output_goal,
        "boundaries": run_section.get("boundaries"),
        "acceptance": run_section.get("acceptance"),
        "digests": digests,
        "tool_instructions": {
            "authorization": (
                "Mutating commands require the session capability token exported "
                "as TDP_CAPABILITY_TOKEN."
            ),
            "respond": (
                f"tdp agent review respond --run {run_id} --request <file>"
            ),
        },
        },
        config=config,
        run=run,
        role="reviewer",
    )


def _whole_output_revision_limit(config: dict[str, Any]) -> int:
    review_limits = (config.get("limits") or {}).get("whole_output_review") or {}
    return int(
        review_limits.get(
            "max_revision_cycles",
            _WHOLE_OUTPUT_LIMIT_DEFAULTS["max_revision_cycles"],
        )
    )


def _primary_producer_session_id(run: dict[str, Any]) -> str | None:
    sessions = run.get("sessions") or {}
    session_id = sessions.get("primary_producer_session_id")
    if session_id is None:
        return None
    return str(session_id)
