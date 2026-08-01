"""Whole-output review orchestration and outcome resolution (proposal §5.3, §11–§12.2, §15, §21)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from top_down_planning.agent_tool.config import planning_limits_from_config
from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.config import compute_input_digest, compute_output_goal_digest
from top_down_planning.domain.outcome import (
    evaluate_acceptance_invariant,
    load_approvals_for_acceptance,
    resolve_quality_outcome,
)
from top_down_planning.domain.production import (
    build_output_traceability,
    build_production_review_snapshot,
)
from top_down_planning.domain.review_policy import resolved_revise_at
from top_down_planning.domain.reviews import (
    ReviewLoop,
    allocate_discovery_finding_set_id,
    advisory_handoff_allowed,
    budgets_snapshot,
    complete_advisory_handoff_if_owner_responses_recorded,
    finding_actions_for_active_set,
    find_whole_plan_approval,
    is_revision_requested_status,
    is_terminal_review_loop,
    loop_revise_at,
    mandatory_review_limits_from_config,
    mandatory_approval_allowed,
    mark_advisory_handoff_completed,
    needs_advisory_handoff,
    build_primary_owner_finding_guidance,
    owner_actions_require_revision,
    policy_observability_fields,
    primary_review_resume_fields,
    required_open_findings,
    verification_required_for_loop,
)
from top_down_planning.orchestrator.mandatory_review_stages import (
    approved_means_final_approval,
    approved_means_start_scope_review,
    is_scope_review_stage,
    limit_message,
    mark_findings_open,
    mark_limit_reached_loop,
    mark_mandatory_approved,
    enter_planner_revision_cycle,
    mark_verification_pending,
    mandatory_orchestration_decision,
    prepare_scope_review_loop,
    seed_mandatory_loop_fields,
    stage_package_fields,
    verification_recheck_request,
)
from top_down_planning.orchestrator.review_loop_bootstrap import bootstrap_whole_review_loop
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
    revoke_capabilities_for_phase,
    rotate_session_capability,
)
from top_down_planning.orchestrator.producer_session import primary_producer_provider_session_id
from top_down_planning.orchestrator.reviewer_session import (
    ReviewerRecheckRequiresNewSession,
    begin_reviewer_review,
    build_reviewer_protocol_instructions,
    build_reviewer_tool_instructions,
    deliver_reviewer_turn,
    resume_reviewer_session_with_package,
    reviewer_decision_missing_error,
    reviewer_loop_provider_session_id,
    resolve_reviewer_session_for_recheck,
)
from top_down_planning.orchestrator.errors import (
    OrchestratorInvariantError,
    ProviderRunError,
    SessionRecoveryPaused,
)
from top_down_planning.orchestrator.failure import apply_review_incomplete_run_transition
from top_down_planning.orchestrator.review_incomplete_handoff import (
    pause_advisory_handoff_incomplete,
)
from top_down_planning.orchestrator.phases import OUTPUT_VALIDATED, WHOLE_OUTPUT_REVIEW
from top_down_planning.orchestrator.run_transitions import (
    complete_run_with_outcome,
    pause_for_limit_exhausted,
)
from top_down_planning.orchestrator.provider_turns import (
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
    sync_persisted_session_id,
    sync_reviewer_loop_session_id,
)
from top_down_planning.workspace import run_workspace
from top_down_planning.persistence.digests import (
    compute_config_contract_digest,
    compute_output_digest,
    compute_plan_digest,
)
from top_down_planning.persistence.interface import RunStore
from core_tools.provider import Provider

_NO_COMPLETION_SIGNALS = frozenset[str]()

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
        limits = mandatory_review_limits_from_config(config, "whole_output")
        output_revision = int(self._store.load_production(self._run_id)["output_revision"])
        loop, deliver_on_existing_session = bootstrap_whole_review_loop(
            self._get_or_create_active_loop(),
            current_revision=output_revision,
            resume_interrupted_revision=self._resume_interrupted_producer_revision,
            normalize_loop_for_resume=self._normalize_loop_for_resume,
        )
        loop = self._persist_loop(seed_mandatory_loop_fields(loop))

        while True:
            if loop.status == "pending":
                session_id = reviewer_loop_provider_session_id(loop)
                run = self._store.load_run(self._run_id)
                phase = str(run.get("phase") or WHOLE_OUTPUT_REVIEW)
                if session_id is None:
                    session_id, self._capability_token = self._start_reviewer_session(loop)
                    loop = self._reload_loop(loop.id)
                    deliver_on_existing_session = False
                elif deliver_on_existing_session:
                    config = self._store.load_resolved_config(self._run_id)
                    role_context = resolve_role_session_context(config, run, "reviewer")
                    package = build_whole_output_review_package(
                        self._run_id,
                        run,
                        config,
                        self._store.load_plan_model(self._run_id),
                        self._store.load_production(self._run_id),
                        loop,
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
                        loop=self._reload_loop(loop.id),
                    )
                    deliver_on_existing_session = False
                decision = self._consume_reviewer_turn(session_id, loop.id)
                loop = self._reload_loop(loop.id)
                if decision is None:
                    raise reviewer_decision_missing_error()
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
                    continue
            stage_decision = mandatory_orchestration_decision(loop)

            if stage_decision in {"approved", "verified"}:
                loop = self._reload_loop(loop.id)
                if approved_means_final_approval(loop):
                    return self._complete_with_approval(loop)
                if approved_means_start_scope_review(loop):
                    transition = self._begin_scope_review(loop, limits)
                    if isinstance(transition, WholeOutputReviewResult):
                        return transition
                    loop = transition
                    deliver_on_existing_session = False
                    continue
                raise ProviderRunError(
                    "approved decision left required findings unresolved"
                )

            if stage_decision == "blocked":
                revoke_capabilities_for_loop(self._store, self._run_id, loop.id)
                if loop.lifecycle_status == "limit_reached":
                    exhausted = loop.exhausted_budget or "verification_revision"
                    return self._pause_for_limit(
                        limit_message(
                            limits,
                            exhausted=exhausted,
                            review_label="whole-output review",
                        ),
                        loop=loop,
                        exhausted=exhausted,
                        limits=limits,
                    )
                return self._terminate(
                    "blocked",
                    "whole-output reviewer blocked the run",
                    loop=loop,
                )

            if stage_decision == "review_incomplete":
                budgets = budgets_snapshot(loop)
                marker = loop.review_incomplete or {}
                reason = str(
                    marker.get("reason")
                    or "whole-output review could not be completed"
                )
                apply_review_incomplete_run_transition(
                    self._store,
                    self._run_id,
                    loop_id=loop.id,
                    reason=reason,
                    finding_set_id=marker.get("finding_set_id"),
                    stage=marker.get("stage"),
                )
                run = self._store.load_run(self._run_id)
                return WholeOutputReviewResult(
                    ok=False,
                    phase=WHOLE_OUTPUT_REVIEW,
                    status=str(run.get("status") or "paused"),
                    outcome=None,
                    loop_id=loop.id,
                    reviewer_session_id=reviewer_loop_provider_session_id(loop),
                    revision_cycles=budgets["revision_cycles"],
                    reason=reason,
                )

            if stage_decision == "advisory_pending":
                loop = self._handle_advisory_handoff(loop)
                if loop.status == "review_incomplete":
                    return self._result_review_incomplete(loop)
                if loop.status == "approved":
                    if approved_means_final_approval(loop):
                        return self._complete_with_approval(loop)
                    if approved_means_start_scope_review(loop):
                        transition = self._begin_scope_review(loop, limits)
                        if isinstance(transition, WholeOutputReviewResult):
                            return transition
                        loop = transition
                        deliver_on_existing_session = False
                        continue
                if required_open_findings(loop.findings, loop_revise_at(loop)):
                    stage_decision = "changes_requested"
                elif verification_required_for_loop(loop):
                    active = finding_actions_for_active_set(loop)
                    if owner_actions_require_revision(active):
                        stage_decision = "changes_requested"
                    else:
                        loop = self._persist_loop(mark_findings_open(loop))
                        loop = self._persist_loop(enter_planner_revision_cycle(loop))
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

            if stage_decision not in {
                "needs_revision",
                "changes_requested",
            }:
                raise ProviderRunError(
                    f"unexpected mandatory review decision: {stage_decision}"
                )

            loop = self._reload_loop(loop.id)
            prior_finding_set_id = loop.finding_set_id
            was_scope_review_stage = is_scope_review_stage(loop)
            loop = self._persist_loop(mark_findings_open(loop))
            if was_scope_review_stage:
                self._append_event(
                    "whole_output_scope_review_changes_requested",
                    loop_id=loop.id,
                    review_type=loop.type,
                    stage="scope_review",
                    finding_set_id=loop.finding_set_id,
                    prior_finding_set_id=prior_finding_set_id,
                    finding_count=len(loop.findings),
                )

            revision_cycles = loop.revision_cycles + 1
            loop = self._persist_loop(
                enter_planner_revision_cycle(
                    replace(loop, revision_cycles=revision_cycles)
                )
            )

            if revision_cycles >= limits.max_revision_cycles:
                loop = self._persist_loop(
                    mark_limit_reached_loop(
                        loop,
                        limits=limits,
                        exhausted="verification_revision",
                    )
                )
                return self._pause_for_limit(
                    limit_message(
                        limits,
                        exhausted="verification_revision",
                        review_label="whole-output review",
                    ),
                    loop=loop,
                    exhausted="verification_revision",
                    limits=limits,
                )

            self._resume_producer_with_findings(loop)
            loop = self._prepare_recheck(loop)

    def _begin_scope_review(
        self,
        loop: ReviewLoop,
        limits: Any,
    ) -> ReviewLoop | WholeOutputReviewResult:
        if loop.scope_review_rounds >= limits.max_scope_review_rounds:
            loop = self._persist_loop(
                mark_limit_reached_loop(
                    loop,
                    limits=limits,
                    exhausted="scope_review",
                )
            )
            return self._pause_for_limit(
                limit_message(
                    limits,
                    exhausted="scope_review",
                    review_label="whole-output review",
                ),
                loop=loop,
                exhausted="scope_review",
                limits=limits,
            )
        if reviewer_loop_provider_session_id(loop) is not None:
            revoke_capabilities_for_loop(self._store, self._run_id, loop.id)
        updated = self._persist_loop(prepare_scope_review_loop(loop))
        self._append_event(
            "whole_output_scope_review_started",
            loop_id=updated.id,
            review_type=updated.type,
            stage="scope_review",
            scope_review_rounds=updated.scope_review_rounds,
            target_revision=updated.target_revision,
        )
        return updated

    def _complete_with_approval(self, loop: ReviewLoop) -> WholeOutputReviewResult:
        plan = self._store.load_plan_model(self._run_id)
        production = self._store.load_production(self._run_id)
        run = self._store.load_run(self._run_id)
        config = self._store.load_resolved_config(self._run_id)
        limits = planning_limits_from_config(config)
        review_limits = mandatory_review_limits_from_config(config, "whole_output")
        current_digest = compute_output_digest(production)

        loop = self._reload_loop(loop.id)
        if not mandatory_approval_allowed(
            loop,
            current_artifact_digest=current_digest,
            limits=review_limits,
        ):
            return self._terminate(
                "blocked",
                "mandatory whole-output approval invariant not satisfied",
                loop=loop,
            )

        loop = self._persist_loop(mark_mandatory_approved(loop))

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
            actual_config_contract_digest=compute_config_contract_digest(config),
            actual_output_digest=compute_output_digest(production),
            actual_input_digest=compute_input_digest(
                config,
                base_dir=run_workspace(run),
            ),
            actual_output_goal_digest=compute_output_goal_digest(
                config,
                base_dir=run_workspace(run),
            ),
            actual_context_spec_digest=(run.get("digests") or {}).get("context_spec"),
            actual_context_snapshot_digest=(run.get("digests") or {}).get("context_snapshot"),
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
            reviewer_session_id=reviewer_loop_provider_session_id(loop),
            outcome=outcome,
        )
        self._append_event(
            "outcome_resolved",
            outcome=outcome,
            acceptance_invariant=invariant.to_dict(),
        )
        run = self._store.load_run(self._run_id)
        return self._result_from_run(run, ok=True, loop=loop)

    def _pause_advisory_handoff_incomplete(self, loop: ReviewLoop) -> ReviewLoop:
        loop, _reason = pause_advisory_handoff_incomplete(
            self._store,
            self._run_id,
            loop,
        )
        return self._persist_loop(loop)

    def _result_review_incomplete(self, loop: ReviewLoop) -> WholeOutputReviewResult:
        budgets = budgets_snapshot(loop)
        marker = loop.review_incomplete or {}
        reason = str(
            marker.get("reason") or "whole-output review could not be completed"
        )
        run = self._store.load_run(self._run_id)
        return WholeOutputReviewResult(
            ok=False,
            phase=WHOLE_OUTPUT_REVIEW,
            status=str(run.get("status") or "paused"),
            outcome=None,
            loop_id=loop.id,
            reviewer_session_id=reviewer_loop_provider_session_id(loop),
            revision_cycles=budgets["revision_cycles"],
            reason=reason,
        )

    def _pause_for_limit(
        self,
        message: str,
        *,
        loop: ReviewLoop | None,
        exhausted: str,
        limits: Any,
    ) -> WholeOutputReviewResult:
        if exhausted == "verification_revision":
            limit = "max_revision_cycles"
            consumed = int(loop.revision_cycles if loop is not None else limits.max_revision_cycles)
            configured = int(limits.max_revision_cycles)
        else:
            limit = "max_scope_review_rounds"
            consumed = int(
                loop.scope_review_rounds if loop is not None else limits.max_scope_review_rounds
            )
            configured = int(limits.max_scope_review_rounds)
        pause_for_limit_exhausted(
            self._store,
            self._run_id,
            phase=WHOLE_OUTPUT_REVIEW,
            message=message,
            limit=limit,
            consumed=consumed,
            configured=configured,
            role="reviewer",
            revoke_phase=WHOLE_OUTPUT_REVIEW,
            loop_id=loop.id if loop is not None else None,
            exhausted_budget=exhausted,
        )
        self._append_event(
            "whole_output_review_limit_exceeded",
            message=message,
            loop_id=loop.id if loop is not None else None,
            exhausted_budget=exhausted,
        )
        run = self._store.load_run(self._run_id)
        return self._result_from_run(run, ok=False, reason=message)

    def _terminate(
        self,
        outcome: str,
        message: str,
        *,
        loop: ReviewLoop | None = None,
    ) -> WholeOutputReviewResult:
        complete_run_with_outcome(
            self._store,
            self._run_id,
            outcome,
            revoke_phase=WHOLE_OUTPUT_REVIEW,
            event_type="whole_output_review_failed",
            message=message,
            loop_id=loop.id if loop is not None else None,
            lifecycle_status=loop.lifecycle_status if loop is not None else None,
        )
        run = self._store.load_run(self._run_id)
        return self._result_from_run(run, ok=False, reason=message)

    def _normalize_loop_for_resume(self, loop: ReviewLoop) -> tuple[ReviewLoop, bool]:
        if loop.status == "review_incomplete":
            from top_down_planning.domain.reviews import (
                allocate_discovery_finding_set_id,
                prepare_review_incomplete_retry,
            )

            retried = prepare_review_incomplete_retry(loop)
            retried, _finding_set_id = allocate_discovery_finding_set_id(retried)
            return self._persist_loop(retried), False

        if not is_revision_requested_status(loop.status):
            return loop, False

        output_revision = int(self._store.load_production(self._run_id)["output_revision"])
        if output_revision <= loop.target_revision:
            return loop, False

        return self._prepare_recheck(loop), True

    def _get_or_create_active_loop(self) -> ReviewLoop:
        output_revision = int(self._store.load_production(self._run_id)["output_revision"])
        for payload in reversed(self._store.list_reviews(self._run_id)):
            if payload.get("type") != "whole_output":
                continue
            loop = ReviewLoop.from_dict(payload)
            if loop.target_revision != output_revision:
                continue
            if is_terminal_review_loop(loop):
                continue
            return loop
        return self._create_loop()

    def _create_loop(self) -> ReviewLoop:
        output_revision = int(self._store.load_production(self._run_id)["output_revision"])
        loop_id = self._next_loop_id()
        config = self._store.load_resolved_config(self._run_id)
        loop = ReviewLoop(
            id=loop_id,
            type="whole_output",
            target_revision=output_revision,
            scope={"kind": "whole_output"},
            status="pending",
            lifecycle_status="review_pending",
            active_stage=None,
            scope_review_rounds=0,
            revise_at=resolved_revise_at(config, "whole_output"),
        )
        self._store.save_review(self._run_id, loop.to_dict())
        self._append_event(
            "whole_output_review_started",
            loop_id=loop_id,
            review_type=loop.type,
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

    def _start_reviewer_session(self, loop: ReviewLoop) -> tuple[str, str]:
        run = self._store.load_run(self._run_id)
        config = self._store.load_resolved_config(self._run_id)
        stage = loop.active_stage or "initial_review"
        if stage in {None, "initial_review", "scope_review"}:
            loop, _finding_set_id = allocate_discovery_finding_set_id(loop)
            loop = self._persist_loop(loop)
        package = build_whole_output_review_package(
            self._run_id,
            run,
            config,
            self._store.load_plan_model(self._run_id),
            self._store.load_production(self._run_id),
            loop,
        )
        role_context = resolve_role_session_context(config, run, "reviewer")
        run = self._store.load_run(self._run_id)
        phase = str(run.get("phase") or WHOLE_OUTPUT_REVIEW)
        session_id, self._capability_token = begin_reviewer_review(
            self._provider,
            self._store,
            self._run_id,
            loop_id=loop.id,
            review_package=package,
            phase=phase,
            model=role_context.model,
        )
        emit_reviewer_session_started(
            self._append_event,
            self._provider,
            phase=phase,
            session_id=session_id,
            loop=loop,
        )
        return session_id, self._capability_token

    def _consume_reviewer_turn(self, session_id: str, loop_id: str) -> str | None:
        run = self._store.load_run(self._run_id)
        config = self._store.load_resolved_config(self._run_id)
        loop = ReviewLoop.from_dict(self._store.load_review(self._run_id, loop_id))
        package = build_whole_output_review_package(
            self._run_id,
            run,
            config,
            self._store.load_plan_model(self._run_id),
            self._store.load_production(self._run_id),
            loop,
        )
        role_context = resolve_role_session_context(config, run, "reviewer")
        phase = str(run.get("phase") or WHOLE_OUTPUT_REVIEW)
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
                    expected_next_action="continue whole-output reviewer turn",
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
            session_id=session_id,
        )

    def _resume_interrupted_producer_revision(self, loop: ReviewLoop) -> ReviewLoop:
        self._resume_producer_with_findings(loop)
        return self._prepare_recheck(loop)

    def _resume_producer_with_findings(self, loop: ReviewLoop) -> None:
        run = self._store.load_run(self._run_id)
        session_id = primary_producer_provider_session_id(run)
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

        config = self._store.load_resolved_config(self._run_id)
        role_context = resolve_role_session_context(config, run, "producer")
        resume_primary_session_with_audit(
            self._append_event,
            self._provider,
            role="producer",
            phase=phase,
            session_id=session_id,
            request={
                "action": "address_review_findings",
                "phase": WHOLE_OUTPUT_REVIEW,
                "loop_id": loop.id,
                "target_revision": loop.target_revision,
                **primary_review_resume_fields(loop, config=config),
                "revision_instructions": {
                    "apply_mode": "evidence_revision",
                    "evidence_revision": True,
                    "tool": "production_apply",
                    "notes": (
                        "Set evidence_revision: true on production apply for terminal "
                        "plan_items targeted by open required findings. Keep existing "
                        "dispositions unchanged; attach new outputs or contributions. "
                        "Then submit-completion with goal_met: true."
                    ),
                },
                "tool_instructions": {
                    "record_actions": (
                        f"tdp agent review record-actions --run {self._run_id} "
                        "--request $TDP_AGENT_REQUESTS_DIR/review-record-actions-<loop>-a01.json"
                    ),
                    "notes": build_primary_owner_finding_guidance(
                        handoff="revision",
                        loop=loop,
                        config=config,
                    ),
                },
            },
            model=role_context.model,
            loop_id=loop.id,
        )
        self._consume_producer_turn(session_id)
        self._sync_output_digest()

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
        before = budgets_snapshot(loop)
        self._append_event(
            "review_advisory_handoff_started",
            loop_id=loop.id,
            finding_set_id=loop.finding_set_id,
            **policy_observability_fields(
                loop.findings,
                loop.finding_actions,
                loop_revise_at(loop),
                finding_set_id=loop.finding_set_id,
            ),
        )
        self._resume_producer_advisory_handoff(loop)
        loop = self._reload_loop(loop.id)
        if needs_advisory_handoff(loop):
            return self._pause_advisory_handoff_incomplete(loop)
        after = budgets_snapshot(loop)
        if after != before and not owner_actions_require_revision(
            finding_actions_for_active_set(loop)
        ):
            raise OrchestratorInvariantError(
                "advisory handoff must not consume revision budget without a fix"
            )
        return self._persist_loop(mark_advisory_handoff_completed(loop))

    def _resume_producer_advisory_handoff(self, loop: ReviewLoop) -> None:
        run = self._store.load_run(self._run_id)
        session_id = primary_producer_provider_session_id(run)
        if session_id is None:
            raise ProviderRunError(
                "primary producer session is missing for advisory handoff"
            )
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
        config = self._store.load_resolved_config(self._run_id)
        role_context = resolve_role_session_context(config, run, "producer")
        resume_primary_session_with_audit(
            self._append_event,
            self._provider,
            role="producer",
            phase=phase,
            session_id=session_id,
            request={
                "action": "address_optional_findings",
                "phase": WHOLE_OUTPUT_REVIEW,
                "loop_id": loop.id,
                "target_revision": loop.target_revision,
                **primary_review_resume_fields(loop, config=config),
                "tool_instructions": {
                    "record_actions": (
                        f"tdp agent review record-actions --run {self._run_id} "
                        "--request $TDP_AGENT_REQUESTS_DIR/review-record-actions-<loop>-a01.json"
                    ),
                    "notes": build_primary_owner_finding_guidance(
                        handoff="advisory",
                        loop=loop,
                        config=config,
                    ),
                },
            },
            model=role_context.model,
            loop_id=loop.id,
        )
        self._consume_producer_turn(session_id)

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
        run = self._store.load_run(self._run_id)
        config = self._store.load_resolved_config(self._run_id)
        role_context = resolve_role_session_context(config, run, "producer")
        phase = str(run.get("phase") or WHOLE_OUTPUT_REVIEW)
        try:
            turn_outcome = consume_provider_turn_with_session_recovery(
                self._store,
                self._run_id,
                self._provider,
                session_id,
                allowed_signals=_NO_COMPLETION_SIGNALS,
                recovery=build_producer_turn_recovery(
                    self._store,
                    self._run_id,
                    phase=phase,
                    expected_next_action="revise output after whole-output review",
                    append_event=self._append_event,
                    model=role_context.model,
                ),
            )
        except SessionRecoveryPaused as exc:
            raise ProviderRunError(str(exc)) from exc
        session_id = turn_outcome.session_id
        sync_persisted_session_id(
            self._provider,
            self._store,
            self._run_id,
            session_id,
            role="producer",
        )

    def _prepare_recheck(self, loop: ReviewLoop) -> ReviewLoop:
        output_revision = int(self._store.load_production(self._run_id)["output_revision"])
        run = self._store.load_run(self._run_id)
        phase = str(run.get("phase") or WHOLE_OUTPUT_REVIEW)
        config = self._store.load_resolved_config(self._run_id)
        role_context = resolve_role_session_context(config, run, "reviewer")
        updated = self._persist_loop(
            mark_verification_pending(loop, target_revision=output_revision)
        )
        verification_request = verification_recheck_request(
            phase=WHOLE_OUTPUT_REVIEW,
            loop=updated,
            target_revision=output_revision,
        )
        try:
            session_id = resolve_reviewer_session_for_recheck(
                loop,
                target_revision=loop.target_revision,
                current_revision=output_revision,
            )
        except ReviewerRecheckRequiresNewSession:
            loop = self._persist_loop(loop.with_reviewer_session_released())
            updated = self._persist_loop(
                mark_verification_pending(loop, target_revision=output_revision)
            )
            session_id, self._capability_token = begin_reviewer_review(
                self._provider,
                self._store,
                self._run_id,
                loop_id=loop.id,
                review_package=verification_request,
                phase=phase,
                model=role_context.model,
            )
            emit_reviewer_session_started(
                self._append_event,
                self._provider,
                phase=phase,
                session_id=session_id,
                loop=updated,
                replacement=True,
            )
            return updated

        self._capability_token = deliver_reviewer_turn(
            self._provider,
            self._store,
            self._run_id,
            session_id=session_id,
            loop_id=loop.id,
            phase=phase,
            request=verification_request,
            model=role_context.model,
        )
        emit_reviewer_session_resumed(
            self._append_event,
            self._provider,
            phase=phase,
            session_id=session_id,
            loop=updated,
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
            reviewer_session_id=reviewer_loop_provider_session_id(loop) if loop is not None else None,
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

    digests = dict(run.get("digests") or {})
    review_cfg = (config.get("review") or {}).get("whole_output") or {}
    rubric = list(
        review_cfg.get("rubric")
        or DEFAULT_CONFIG["review"]["whole_output"]["rubric"]
    )
    traceability = build_output_traceability(plan, production)
    package: dict[str, Any] = {
        "run_id": run_id,
        "phase": WHOLE_OUTPUT_REVIEW,
        "type": "whole_output",
        "loop_id": loop.id,
        "purpose": (
            "Mandatory whole-output fresh scope review before final outcome"
            if loop.active_stage == "scope_review"
            else "Mandatory whole-output review before final outcome"
        ),
        "scope": dict(loop.scope),
        "target_revision": loop.target_revision,
        "output_revision": int(production["output_revision"]),
        "production": build_production_review_snapshot(production),
        "plan_contracts": traceability["plan_contracts"],
        "evidence_by_item": traceability["evidence_by_item"],
        **plan_execution_contract_fields(plan),
        "digests": digests,
        **stage_package_fields(loop),
        "protocol_instructions": build_reviewer_protocol_instructions(
            stage=loop.active_stage or "initial_review",
            review_type=loop.type,
        ),
        "tool_instructions": build_reviewer_tool_instructions(run_id),
    }
    if loop.active_stage != "scope_review":
        package["rubric"] = rubric
    return attach_role_context_to_manifest(
        package,
        config=config,
        run=run,
        role="reviewer",
        output_goal=plan.output_goal,
    )

