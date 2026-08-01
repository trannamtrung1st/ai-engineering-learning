"""Optional focused plan/output review loops (proposal §4.3, §5.1, §11)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from top_down_planning.agent_tool.config import planning_limits_from_config
from top_down_planning.agent_tool.views import build_plan_review_snapshot
from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.domain.production import (
    build_output_traceability,
    build_production_review_snapshot,
)
from top_down_planning.domain.reviews import (
    ReviewLoop,
    allocate_discovery_finding_set_id,
    advisory_handoff_allowed,
    budgets_snapshot,
    complete_advisory_handoff_if_owner_responses_recorded,
    finding_actions_for_active_set,
    loop_revise_at,
    mark_advisory_handoff_completed,
    needs_advisory_handoff,
    optional_open_findings,
    owner_actions_require_revision,
    policy_observability_fields,
    prepare_review_incomplete_retry,
    primary_review_resume_fields,
    required_open_findings,
    reviewer_package_policy_guidance,
    verification_required_for_loop,
)
from top_down_planning.orchestrator.agent_context import (
    attach_role_context_to_manifest,
    plan_execution_contract_fields,
    resolve_role_session_context,
)
from top_down_planning.orchestrator.capability import (
    adopt_replacement_capability,
    bind_provider_capability,
    issue_session_capability,
    revoke_capabilities_for_loop,
    rotate_session_capability,
)
from top_down_planning.orchestrator.planner_session import primary_planner_provider_session_id
from top_down_planning.orchestrator.producer_session import primary_producer_provider_session_id
from top_down_planning.orchestrator.reviewer_session import (
    allocate_reviewer_session,
    build_reviewer_protocol_instructions,
    build_reviewer_tool_instructions,
    deliver_reviewer_turn,
    resume_reviewer_session_with_package,
    reviewer_decision_missing_error,
    reviewer_loop_provider_session_id,
    resolve_reviewer_session_for_recheck,
)
from top_down_planning.orchestrator.mandatory_review_stages import (
    prepare_focused_verification_recheck,
    verification_recheck_request,
)
from top_down_planning.orchestrator.errors import (
    OrchestratorInvariantError,
    ProviderRunError,
    SessionRecoveryPaused,
)
from top_down_planning.orchestrator.review_incomplete_handoff import (
    pause_advisory_handoff_incomplete,
)
from top_down_planning.orchestrator.phases import PLANNING, PRODUCTION
from top_down_planning.orchestrator.run_transitions import pause_for_limit_exhausted
from top_down_planning.orchestrator.provider_turns import (
    build_planner_turn_recovery,
    build_producer_turn_recovery,
    build_reviewer_turn_recovery,
    consume_provider_turn_with_session_recovery,
)
from top_down_planning.orchestrator.session_events import (
    commit_reviewer_loop_provider_session,
    emit_reviewer_session_resumed,
    emit_reviewer_session_started,
    release_reviewer_session_after_decision,
    resume_primary_session_with_audit,
    sync_reviewer_loop_session_id,
)
from top_down_planning.persistence.digests import compute_output_digest
from top_down_planning.persistence.interface import RunStore
from core_tools.provider import Provider

_FOCUSED_PLAN_LIMIT_DEFAULTS = DEFAULT_CONFIG["limits"]["focused_plan_review"]
_FOCUSED_OUTPUT_LIMIT_DEFAULTS = DEFAULT_CONFIG["limits"]["focused_output_review"]

_NO_COMPLETION_SIGNALS = frozenset[str]()

@dataclass(frozen=True)
class FocusedReviewResult:
    ok: bool
    loop_id: str
    status: str
    reviewer_session_id: str | None
    revision_cycles: int
    reason: str | None = None


class FocusedReviewOrchestrator:
    """Drive one optional focused review loop without advancing mandatory gates."""

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

    def run(self, loop_id: str) -> FocusedReviewResult:
        loop = ReviewLoop.from_dict(self._store.load_review(self._run_id, loop_id))
        if loop.type not in {"focused_plan", "focused_output"}:
            raise ProviderRunError(f"review loop {loop_id} is not a focused review loop")

        config = self._store.load_resolved_config(self._run_id)
        max_revision_cycles = _focused_revision_limit(config, loop.type)
        loop, reviewer_turn_delivered = self._normalize_loop_for_resume(loop)
        deliver_on_existing_session = (
            reviewer_loop_provider_session_id(loop) is not None
            and not reviewer_turn_delivered
        )

        while True:
            if loop.status == "pending":
                session_id = reviewer_loop_provider_session_id(loop)
                phase = PLANNING if loop.type == "focused_plan" else PRODUCTION
                if session_id is None:
                    session_id, self._capability_token = self._start_reviewer_session(loop)
                    loop = self._reload_loop(loop.id)
                    deliver_on_existing_session = False
                elif deliver_on_existing_session:
                    run = self._store.load_run(self._run_id)
                    config = self._store.load_resolved_config(self._run_id)
                    role_context = resolve_role_session_context(config, run, "reviewer")
                    package = build_focused_review_package(
                        self._run_id,
                        run,
                        config,
                        loop,
                        plan=self._store.load_plan_model(self._run_id),
                        production=(
                            self._store.load_production(self._run_id)
                            if loop.type == "focused_output"
                            else None
                        ),
                    )
                    self._capability_token = resume_reviewer_session_with_package(
                        self._provider,
                        self._store,
                        self._run_id,
                        session_id=session_id,
                        loop_id=loop.id,
                        phase=phase,
                        review_package=package,
                        model=role_context.model,
                    )
                    emit_reviewer_session_resumed(
                        self._append_event,
                        self._provider,
                        phase=phase,
                        session_id=session_id,
                        loop_id=loop.id,
                        review_type=loop.type,
                    )
                    deliver_on_existing_session = False
                decision = self._consume_reviewer_turn(session_id, loop.id)
                loop = self._reload_loop(loop.id)
                if decision is None:
                    raise reviewer_decision_missing_error()
                if loop.status == "pending":
                    phase = PLANNING if loop.type == "focused_plan" else PRODUCTION
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

            if decision in {"approved", "verified"}:
                return self._result_from_loop(loop, ok=True)

            if decision == "needs_revision":
                decision = "changes_requested"

            if decision == "blocked":
                return self._result_from_loop(
                    loop,
                    ok=False,
                    reason="focused reviewer blocked the scoped review",
                )

            if decision == "review_incomplete" or loop.status == "review_incomplete":
                marker = loop.review_incomplete or {}
                return self._result_from_loop(
                    loop,
                    ok=False,
                    reason=str(
                        marker.get("reason")
                        or "focused review could not be completed"
                    ),
                )

            if decision in {"advisory_pending", "pending"}:
                loop = self._handle_advisory_handoff(loop)
                if loop.status == "review_incomplete":
                    return self._result_review_incomplete(loop)
                if loop.status == "approved":
                    return self._result_from_loop(loop, ok=True)
                if required_open_findings(loop.findings, loop_revise_at(loop)):
                    decision = "changes_requested"
                elif verification_required_for_loop(loop):
                    active = finding_actions_for_active_set(loop)
                    if owner_actions_require_revision(active):
                        decision = "changes_requested"
                    else:
                        # Challenge-only: verification/recheck without revision budget.
                        loop = self._prepare_recheck(loop)
                        continue
                elif needs_advisory_handoff(loop):
                    loop = self._pause_advisory_handoff_incomplete(loop)
                    return self._result_review_incomplete(loop)
                else:
                    raise OrchestratorInvariantError(
                        "advisory handoff completed without resolving optional "
                        "finding policy"
                    )

            if decision != "changes_requested":
                raise ProviderRunError(f"unexpected review decision: {decision}")

            revision_cycles = loop.revision_cycles + 1
            loop = self._persist_loop(
                replace(
                    loop,
                    status="pending",
                    revision_cycles=revision_cycles,
                )
            )

            if revision_cycles >= max_revision_cycles:
                loop = self._persist_loop(
                    replace(
                        loop,
                        status="blocked",
                        revision_cycles=revision_cycles,
                    )
                )
                phase = PLANNING if loop.type == "focused_plan" else PRODUCTION
                limit_name = "max_revision_cycles_per_loop"
                message = (
                    "focused review exceeded max_revision_cycles_per_loop "
                    f"({max_revision_cycles})"
                )
                pause_for_limit_exhausted(
                    self._store,
                    self._run_id,
                    phase=phase,
                    message=message,
                    limit=limit_name,
                    consumed=revision_cycles,
                    configured=max_revision_cycles,
                    role="reviewer",
                    revoke_phase=phase,
                    loop_id=loop.id,
                    review_type=loop.type,
                )
                self._append_event(
                    "focused_review_limit_exceeded",
                    loop_id=loop.id,
                    review_type=loop.type,
                    reason=message,
                )
                run = self._store.load_run(self._run_id)
                revoke_capabilities_for_loop(self._store, self._run_id, loop.id)
                return FocusedReviewResult(
                    ok=False,
                    loop_id=loop.id,
                    status=str(run.get("status") or "paused"),
                    reviewer_session_id=reviewer_loop_provider_session_id(loop),
                    revision_cycles=loop.revision_cycles,
                    reason=message,
                )

            self._resume_primary_with_findings(loop)
            loop = self._prepare_recheck(loop)

    def _normalize_loop_for_resume(self, loop: ReviewLoop) -> tuple[ReviewLoop, bool]:
        if loop.status == "review_incomplete":
            retried = prepare_review_incomplete_retry(loop)
            retried, _finding_set_id = allocate_discovery_finding_set_id(retried)
            return self._persist_loop(retried), False

        if loop.status != "changes_requested":
            return loop, False

        current_revision = _current_target_revision(self._store, self._run_id, loop.type)
        if current_revision <= loop.target_revision:
            return loop, False

        return self._prepare_recheck(loop), True

    def _handle_advisory_handoff(self, loop: ReviewLoop) -> ReviewLoop:
        if not needs_advisory_handoff(loop):
            return self._persist_loop(
                complete_advisory_handoff_if_owner_responses_recorded(loop)
            )
        if not advisory_handoff_allowed(loop):
            raise ProviderRunError(
                f"advisory handoff already completed for finding_set_id "
                f"{loop.finding_set_id!r}"
            )
        before_budgets = budgets_snapshot(loop)
        self._append_event(
            "review_advisory_handoff_started",
            loop_id=loop.id,
            review_type=loop.type,
            finding_set_id=loop.finding_set_id,
            **policy_observability_fields(
                loop.findings,
                loop.finding_actions,
                loop_revise_at(loop),
                finding_set_id=loop.finding_set_id,
            ),
        )
        self._resume_primary_advisory_handoff(loop)
        loop = self._reload_loop(loop.id)
        if needs_advisory_handoff(loop):
            return self._pause_advisory_handoff_incomplete(loop)
        after_budgets = budgets_snapshot(loop)
        if after_budgets != before_budgets and not owner_actions_require_revision(
            finding_actions_for_active_set(loop)
        ):
            # Defensive: defer/accept/challenge must not consume revision budget.
            raise OrchestratorInvariantError(
                "advisory handoff must not consume revision budget without a fix"
            )
        return self._persist_loop(mark_advisory_handoff_completed(loop))

    def _resume_primary_advisory_handoff(self, loop: ReviewLoop) -> None:
        run = self._store.load_run(self._run_id)
        if loop.type == "focused_plan":
            session_id = primary_planner_provider_session_id(run)
            phase = PLANNING
            role = "planner"
        else:
            session_id = primary_producer_provider_session_id(run)
            phase = PRODUCTION
            role = "producer"

        if session_id is None:
            raise ProviderRunError(
                f"primary {role} session is missing for advisory handoff"
            )

        self._capability_token = issue_session_capability(
            self._store,
            self._run_id,
            role=role,
            phase=phase,
            session_id=session_id,
            session_kind="primary",
        )
        bind_provider_capability(self._provider, self._capability_token)

        config = self._store.load_resolved_config(self._run_id)
        role_context = resolve_role_session_context(config, run, role)
        resume_primary_session_with_audit(
            self._append_event,
            self._provider,
            role=role,
            phase=phase,
            session_id=session_id,
            request={
                "action": "address_optional_findings",
                "phase": phase,
                "loop_id": loop.id,
                "review_type": loop.type,
                "target_revision": loop.target_revision,
                "scope": dict(loop.scope),
                **primary_review_resume_fields(loop),
                "tool_instructions": {
                    "record_actions": (
                        f"tdp agent review record-actions --run {self._run_id} "
                        "--request <file>"
                    ),
                    "notes": (
                        "Record fix|challenge|defer|accept_as_is via finding_actions. "
                        "Required findings may only use fix or challenge. "
                        "fix and challenge require reviewer verification; "
                        "defer and accept_as_is do not."
                    ),
                },
            },
            model=role_context.model,
            loop_id=loop.id,
            review_type=loop.type,
        )
        self._consume_primary_turn(session_id, loop.type)
        if loop.type == "focused_output":
            self._sync_output_digest()

    def _start_reviewer_session(self, loop: ReviewLoop) -> tuple[str, str]:
        run = self._store.load_run(self._run_id)
        config = self._store.load_resolved_config(self._run_id)
        loop, _finding_set_id = allocate_discovery_finding_set_id(loop)
        loop = self._persist_loop(loop)
        package = build_focused_review_package(
            self._run_id,
            run,
            config,
            loop,
            plan=self._store.load_plan_model(self._run_id),
            production=(
                self._store.load_production(self._run_id)
                if loop.type == "focused_output"
                else None
            ),
        )
        role_context = resolve_role_session_context(config, run, "reviewer")
        phase = PLANNING if loop.type == "focused_plan" else PRODUCTION
        session_id = allocate_reviewer_session(
            self._provider,
            run_id=self._run_id,
            loop_id=loop.id,
            model=role_context.model,
        )
        emit_reviewer_session_started(
            self._append_event,
            self._provider,
            phase=phase,
            session_id=session_id,
            loop_id=loop.id,
            review_type=loop.type,
            scope=loop.scope,
        )
        updated = loop.with_reviewer_provider_session_id(session_id)
        commit_reviewer_loop_provider_session(self._store, self._run_id, updated)
        capability_token = deliver_reviewer_turn(
            self._provider,
            self._store,
            self._run_id,
            session_id=session_id,
            loop_id=loop.id,
            phase=phase,
            request=package,
        )
        return session_id, capability_token

    def _consume_reviewer_turn(self, session_id: str, loop_id: str) -> str | None:
        run = self._store.load_run(self._run_id)
        config = self._store.load_resolved_config(self._run_id)
        loop = ReviewLoop.from_dict(self._store.load_review(self._run_id, loop_id))
        phase = PLANNING if loop.type == "focused_plan" else PRODUCTION
        package = build_focused_review_package(
            self._run_id,
            run,
            config,
            loop,
            plan=self._store.load_plan_model(self._run_id),
            production=(
                self._store.load_production(self._run_id)
                if loop.type == "focused_output"
                else None
            ),
        )
        role_context = resolve_role_session_context(config, run, "reviewer")
        try:
            turn_outcome = consume_provider_turn_with_session_recovery(
                self._store,
                self._run_id,
                self._provider,
                session_id,
                allowed_signals=_NO_COMPLETION_SIGNALS,
                recovery=build_reviewer_turn_recovery(
                    self._store,
                    self._run_id,
                    loop_id=loop_id,
                    phase=phase,
                    expected_next_action="continue reviewer turn",
                    append_event=self._append_event,
                    model=role_context.model,
                    review_package=package,
                ),
            )
        except SessionRecoveryPaused as exc:
            raise ProviderRunError(str(exc)) from exc
        session_id = turn_outcome.session_id
        if turn_outcome.replaced:
            self._capability_token = adopt_replacement_capability(
                self._store,
                self._run_id,
                current_token=self._capability_token,
                replacement_token=turn_outcome.capability_token,
                provider=self._provider,
            )
        sync_reviewer_loop_session_id(
            self._provider,
            self._store,
            self._run_id,
            loop_id,
            session_id,
        )
        return release_reviewer_session_after_decision(
            self._append_event,
            self._provider,
            self._store,
            self._run_id,
            phase=phase,
            loop_id=loop_id,
            review_type=loop.type,
            session_id=session_id,
        )

    def _resume_primary_with_findings(self, loop: ReviewLoop) -> None:
        run = self._store.load_run(self._run_id)
        if loop.type == "focused_plan":
            session_id = primary_planner_provider_session_id(run)
            phase = PLANNING
            role = "planner"
        else:
            session_id = primary_producer_provider_session_id(run)
            phase = PRODUCTION
            role = "producer"

        if session_id is None:
            raise ProviderRunError(f"primary {role} session is missing for focused revision")

        self._capability_token = issue_session_capability(
            self._store,
            self._run_id,
            role=role,
            phase=phase,
            session_id=session_id,
            session_kind="primary",
        )
        bind_provider_capability(self._provider, self._capability_token)

        config = self._store.load_resolved_config(self._run_id)
        role_context = resolve_role_session_context(config, run, role)
        resume_primary_session_with_audit(
            self._append_event,
            self._provider,
            role=role,
            phase=phase,
            session_id=session_id,
            request={
                "action": "address_review_findings",
                "phase": phase,
                "loop_id": loop.id,
                "review_type": loop.type,
                "target_revision": loop.target_revision,
                "scope": dict(loop.scope),
                **primary_review_resume_fields(loop),
                **(
                    {
                        "revision_instructions": {
                            "apply_mode": "evidence_revision",
                            "evidence_revision": True,
                            "focused_review_loop_id": loop.id,
                            "tool": "production_apply",
                            "notes": (
                                "Set evidence_revision: true on production apply for "
                                "terminal plan_items targeted by open required findings "
                                "within this focused_output scope. Keep existing "
                                "dispositions unchanged; attach new output evidence IDs. "
                                "Voluntary optional fixes are allowed; deferred optionals "
                                "need record-actions. Output revision advances for "
                                "reviewer recheck."
                            ),
                        }
                    }
                    if loop.type == "focused_output"
                    else {}
                ),
            },
            model=role_context.model,
            loop_id=loop.id,
            review_type=loop.type,
        )
        self._consume_primary_turn(session_id, loop.type)
        if loop.type == "focused_output":
            self._sync_output_digest()

    def _consume_primary_turn(self, session_id: str, review_type: str) -> None:
        run = self._store.load_run(self._run_id)
        config = self._store.load_resolved_config(self._run_id)
        if review_type == "focused_plan":
            role_context = resolve_role_session_context(config, run, "planner")
            recovery = build_planner_turn_recovery(
                self._store,
                self._run_id,
                phase=PLANNING,
                expected_next_action="address focused plan findings",
                append_event=self._append_event,
                model=role_context.model,
            )
        else:
            role_context = resolve_role_session_context(config, run, "producer")
            recovery = build_producer_turn_recovery(
                self._store,
                self._run_id,
                phase=PRODUCTION,
                expected_next_action="address focused output findings",
                append_event=self._append_event,
                model=role_context.model,
            )
        try:
            consume_provider_turn_with_session_recovery(
                self._store,
                self._run_id,
                self._provider,
                session_id,
                allowed_signals=_NO_COMPLETION_SIGNALS,
                recovery=recovery,
            )
        except SessionRecoveryPaused as exc:
            raise ProviderRunError(str(exc)) from exc

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

    def _prepare_recheck(self, loop: ReviewLoop) -> ReviewLoop:
        current_revision = _current_target_revision(self._store, self._run_id, loop.type)
        phase = PLANNING if loop.type == "focused_plan" else PRODUCTION
        run = self._store.load_run(self._run_id)
        config = self._store.load_resolved_config(self._run_id)
        role_context = resolve_role_session_context(config, run, "reviewer")
        session_id = resolve_reviewer_session_for_recheck(
            self._provider,
            self._store,
            self._run_id,
            loop,
            target_revision=loop.target_revision,
            current_revision=current_revision,
            phase=phase,
            append_event=self._append_event,
            model=role_context.model,
            review_type=loop.type,
            scope=loop.scope,
        )

        updated = prepare_focused_verification_recheck(
            loop,
            target_revision=current_revision,
        )
        updated = updated.with_reviewer_provider_session_id(session_id)
        self._persist_loop(updated)
        self._capability_token = deliver_reviewer_turn(
            self._provider,
            self._store,
            self._run_id,
            session_id=session_id,
            loop_id=loop.id,
            phase=phase,
            request=verification_recheck_request(
                phase=phase,
                loop=updated,
                target_revision=current_revision,
            ),
            model=role_context.model,
        )
        emit_reviewer_session_resumed(
            self._append_event,
            self._provider,
            phase=phase,
            session_id=session_id,
            loop_id=loop.id,
            review_type=loop.type,
        )
        return updated

    def _persist_loop(self, loop: ReviewLoop) -> ReviewLoop:
        self._store.save_review(self._run_id, loop.to_dict())
        return loop

    def _reload_loop(self, loop_id: str) -> ReviewLoop:
        return ReviewLoop.from_dict(self._store.load_review(self._run_id, loop_id))

    def _pause_advisory_handoff_incomplete(self, loop: ReviewLoop) -> ReviewLoop:
        loop, _reason = pause_advisory_handoff_incomplete(
            self._store,
            self._run_id,
            loop,
            pause_run=False,
        )
        return self._persist_loop(loop)

    def _result_review_incomplete(self, loop: ReviewLoop) -> FocusedReviewResult:
        marker = loop.review_incomplete or {}
        reason = str(
            marker.get("reason") or "focused review could not be completed"
        )
        revoke_capabilities_for_loop(self._store, self._run_id, loop.id)
        run = self._store.load_run(self._run_id)
        return FocusedReviewResult(
            ok=False,
            loop_id=loop.id,
            status=str(run.get("status") or loop.status),
            reviewer_session_id=reviewer_loop_provider_session_id(loop),
            revision_cycles=loop.revision_cycles,
            reason=reason,
        )

    def _result_from_loop(
        self,
        loop: ReviewLoop,
        *,
        ok: bool,
        reason: str | None = None,
    ) -> FocusedReviewResult:
        revoke_capabilities_for_loop(self._store, self._run_id, loop.id)
        if ok:
            self._append_event(
                "focused_review_approved",
                loop_id=loop.id,
                review_type=loop.type,
                target_revision=loop.target_revision,
            )
        return FocusedReviewResult(
            ok=ok,
            loop_id=loop.id,
            status=loop.status,
            reviewer_session_id=reviewer_loop_provider_session_id(loop),
            revision_cycles=loop.revision_cycles,
            reason=reason,
        )

    def _append_event(self, event_type: str, **fields: Any) -> None:
        payload = {"type": event_type, "run_id": self._run_id, **fields}
        self._store.append_event(self._run_id, payload)


def build_focused_review_package(
    run_id: str,
    run: dict[str, Any],
    config: dict[str, Any],
    loop: ReviewLoop,
    *,
    plan: Any,
    production: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Package a bounded focused review for a fresh reviewer session."""

    digests = dict(run.get("digests") or {})
    phase = PLANNING if loop.type == "focused_plan" else PRODUCTION
    revision_label = "plan" if loop.type == "focused_plan" else "output"

    extra_instructions: dict[str, str] = {
        "scope_rule": (
            "Findings must reference only item ids declared in scope.item_ids."
        ),
    }
    if loop.type == "focused_plan":
        extra_instructions["plan_snapshot"] = (
            f"tdp agent plan snapshot --run {run_id} --view active"
        )
    tool_instructions = build_reviewer_tool_instructions(run_id, **extra_instructions)

    package: dict[str, Any] = attach_role_context_to_manifest(
        {
        "run_id": run_id,
        "phase": phase,
        "type": loop.type,
        "loop_id": loop.id,
        "finding_set_id": loop.finding_set_id,
        "purpose": f"Optional focused {revision_label} review within declared scope",
        "scope": dict(loop.scope),
        "target_revision": loop.target_revision,
        **plan_execution_contract_fields(plan),
        "digests": digests,
        "review_policy": reviewer_package_policy_guidance(),
        "protocol_instructions": build_reviewer_protocol_instructions(),
        "tool_instructions": tool_instructions,
        },
        config=config,
        run=run,
        role="reviewer",
        output_goal=plan.output_goal,
    )
    if loop.type == "focused_plan":
        limits = planning_limits_from_config(config)
        package["plan_revision"] = plan.revision
        package["plan"] = build_plan_review_snapshot(plan, limits=limits)
    if production is not None:
        package["output_revision"] = int(production["output_revision"])
        package["production"] = build_production_review_snapshot(production)
        if loop.type == "focused_output":
            scope_item_ids = [
                str(item_id)
                for item_id in (loop.scope.get("item_ids") or [])
            ]
            traceability = build_output_traceability(
                plan,
                production,
                item_ids=scope_item_ids,
            )
            package["plan_contracts"] = traceability["plan_contracts"]
            package["evidence_by_item"] = traceability["evidence_by_item"]
    return package


def _focused_revision_limit(config: dict[str, Any], review_type: str) -> int:
    if review_type == "focused_plan":
        review_limits = (config.get("limits") or {}).get("focused_plan_review") or {}
        return int(
            review_limits.get(
                "max_revision_cycles_per_loop",
                _FOCUSED_PLAN_LIMIT_DEFAULTS["max_revision_cycles_per_loop"],
            )
        )
    review_limits = (config.get("limits") or {}).get("focused_output_review") or {}
    return int(
        review_limits.get(
            "max_revision_cycles_per_loop",
            _FOCUSED_OUTPUT_LIMIT_DEFAULTS["max_revision_cycles_per_loop"],
        )
    )


def _current_target_revision(store: RunStore, run_id: str, review_type: str) -> int:
    if review_type == "focused_output":
        return int(store.load_production(run_id)["output_revision"])
    return int(store.load_plan(run_id)["revision"])

