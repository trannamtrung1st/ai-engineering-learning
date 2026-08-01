"""Whole-plan review orchestration (proposal §4.3, §5.2, §11, §12.1)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from top_down_planning.agent_tool.config import planning_limits_from_config
from top_down_planning.agent_tool.views import build_plan_review_snapshot
from top_down_planning.config import compute_input_digest, compute_output_goal_digest
from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.domain.review_policy import resolved_revise_at
from top_down_planning.domain.reviews import (
    ReviewLoop,
    allocate_discovery_finding_set_id,
    advisory_handoff_allowed,
    budgets_snapshot,
    is_revision_requested_status,
    is_terminal_review_loop,
    loop_revise_at,
    mandatory_review_limits_from_config,
    mandatory_approval_allowed,
    mark_advisory_handoff_completed,
    needs_advisory_handoff,
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
from top_down_planning.domain.validators import (
    build_plan_approval_validation_context,
    plan_advisory_warning_messages,
    validate_plan,
)
from top_down_planning.orchestrator.agent_context import (
    attach_role_context_to_manifest,
    plan_execution_contract_fields,
    resolve_role_session_context,
)
from top_down_planning.orchestrator.capability import (
    bind_provider_capability,
    issue_session_capability,
    revoke_capabilities_for_loop,
    revoke_capabilities_for_phase,
    rotate_session_capability,
)
from top_down_planning.orchestrator.planner_session import primary_planner_provider_session_id
from top_down_planning.orchestrator.reviewer_session import (
    allocate_reviewer_session,
    build_reviewer_protocol_instructions,
    build_reviewer_tool_instructions,
    deliver_reviewer_turn,
    resume_reviewer_session_with_package,
    reviewer_decision_missing_error,
    reviewer_loop_provider_session_id,
)
from top_down_planning.orchestrator.errors import ProviderRunError, SessionRecoveryPaused
from top_down_planning.orchestrator.failure import apply_review_incomplete_run_transition
from top_down_planning.orchestrator.phases import PLAN_VALIDATED, WHOLE_PLAN_REVIEW
from top_down_planning.orchestrator.run_transitions import (
    complete_run_with_outcome,
    pause_for_limit_exhausted,
)
from top_down_planning.orchestrator.provider_turns import (
    build_planner_turn_recovery,
    build_reviewer_turn_recovery,
    consume_provider_turn_with_session_recovery,
    review_decision_from_store,
)
from top_down_planning.orchestrator.session_events import (
    commit_reviewer_loop_provider_session,
    emit_reviewer_session_resumed,
    emit_reviewer_session_started,
    resume_primary_session_with_audit,
    sync_persisted_session_id,
    sync_reviewer_loop_session_id,
)
from top_down_planning.workspace import run_workspace
from top_down_planning.persistence.digests import compute_config_contract_digest, compute_plan_digest
from top_down_planning.persistence.interface import RunStore
from core_tools.provider import Provider

_NO_COMPLETION_SIGNALS = frozenset[str]()


@dataclass(frozen=True)
class WholePlanReviewResult:
    ok: bool
    phase: str
    status: str
    outcome: str | None
    loop_id: str | None
    reviewer_session_id: str | None
    revision_cycles: int
    reason: str | None = None


class WholePlanReviewOrchestrator:
    """Drive the mandatory whole-plan review loop until approval or terminal failure."""

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

    def run(self) -> WholePlanReviewResult:
        run = self._store.load_run(self._run_id)
        phase = str(run.get("phase") or "")
        if phase == PLAN_VALIDATED:
            return self._result_from_run(run, ok=True)
        if phase != WHOLE_PLAN_REVIEW:
            raise ProviderRunError(f"run is not in whole-plan review phase: {phase}")

        config = self._store.load_resolved_config(self._run_id)
        limits = mandatory_review_limits_from_config(config, "whole_plan")
        plan_revision = int(self._store.load_plan(self._run_id)["revision"])
        loop, deliver_on_existing_session = bootstrap_whole_review_loop(
            self._get_or_create_active_loop(),
            current_revision=plan_revision,
            resume_interrupted_revision=self._resume_interrupted_planner_revision,
            normalize_loop_for_resume=self._normalize_loop_for_resume,
        )
        loop = self._persist_loop(seed_mandatory_loop_fields(loop))

        while True:
            if loop.status == "pending":
                session_id = reviewer_loop_provider_session_id(loop)
                run = self._store.load_run(self._run_id)
                phase = str(run.get("phase") or WHOLE_PLAN_REVIEW)
                if session_id is None:
                    session_id, self._capability_token = self._start_reviewer_session(loop)
                    loop = self._reload_loop(loop.id)
                    deliver_on_existing_session = False
                elif deliver_on_existing_session:
                    config = self._store.load_resolved_config(self._run_id)
                    role_context = resolve_role_session_context(config, run, "reviewer")
                    package = build_whole_plan_review_package(
                        self._run_id,
                        run,
                        config,
                        self._store.load_plan_model(self._run_id),
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
                        loop_id=loop.id,
                    )
                    deliver_on_existing_session = False
                decision = self._consume_reviewer_turn(session_id, loop.id)
                loop = self._reload_loop(loop.id)
                if decision is None:
                    raise reviewer_decision_missing_error()
                if loop.status == "pending":
                    run = self._store.load_run(self._run_id)
                    phase = str(run.get("phase") or WHOLE_PLAN_REVIEW)
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

            if stage_decision in {"approved", "verified", "approved"}:
                loop = self._reload_loop(loop.id)
                if approved_means_final_approval(loop):
                    return self._complete_with_approval(loop)
                if approved_means_start_scope_review(loop):
                    transition = self._begin_scope_review(loop, limits)
                    if isinstance(transition, WholePlanReviewResult):
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
                            review_label="whole-plan review",
                        ),
                        loop=loop,
                        exhausted=exhausted,
                        limits=limits,
                    )
                return self._terminate(
                    "blocked",
                    "whole-plan reviewer blocked the run",
                    loop=loop,
                )

            if stage_decision == "review_incomplete":
                budgets = budgets_snapshot(loop)
                marker = loop.review_incomplete or {}
                reason = str(
                    marker.get("reason")
                    or "whole-plan review could not be completed"
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
                return WholePlanReviewResult(
                    ok=False,
                    phase=WHOLE_PLAN_REVIEW,
                    status=str(run.get("status") or "paused"),
                    outcome=None,
                    loop_id=loop.id,
                    reviewer_session_id=reviewer_loop_provider_session_id(loop),
                    revision_cycles=budgets["revision_cycles"],
                    reason=reason,
                )

            if stage_decision == "advisory_pending":
                loop = self._handle_advisory_handoff(loop)
                if loop.status in {"approved", "approved"}:
                    if approved_means_final_approval(loop):
                        return self._complete_with_approval(loop)
                    if approved_means_start_scope_review(loop):
                        transition = self._begin_scope_review(loop, limits)
                        if isinstance(transition, WholePlanReviewResult):
                            return transition
                        loop = transition
                        deliver_on_existing_session = False
                        continue
                if required_open_findings(loop.findings, loop_revise_at(loop)):
                    stage_decision = "changes_requested"
                elif verification_required_for_loop(loop):
                    active = [
                        action
                        for action in loop.finding_actions
                        if action.finding_set_id == loop.finding_set_id
                    ]
                    if owner_actions_require_revision(active or loop.finding_actions):
                        stage_decision = "changes_requested"
                    else:
                        # Challenge-only: verification without revision-cycle spend.
                        loop = self._persist_loop(mark_findings_open(loop))
                        loop = self._persist_loop(enter_planner_revision_cycle(loop))
                        loop = self._prepare_recheck(loop)
                        continue
                else:
                    raise ProviderRunError(
                        "advisory handoff completed without qualifying owner actions"
                    )

            if stage_decision not in {
                "needs_revision",
                "changes_requested",
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
                    "whole_plan_scope_review_changes_requested",
                    loop_id=loop.id,
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
                        review_label="whole-plan review",
                    ),
                    loop=loop,
                    exhausted="verification_revision",
                    limits=limits,
                )

            self._resume_planner_with_findings(loop)
            loop = self._prepare_recheck(loop)

    def _begin_scope_review(
        self,
        loop: ReviewLoop,
        limits: Any,
    ) -> ReviewLoop | WholePlanReviewResult:
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
                    review_label="whole-plan review",
                ),
                loop=loop,
                exhausted="scope_review",
                limits=limits,
            )
        if reviewer_loop_provider_session_id(loop) is not None:
            revoke_capabilities_for_loop(self._store, self._run_id, loop.id)
        updated = self._persist_loop(prepare_scope_review_loop(loop))
        self._append_event(
            "whole_plan_scope_review_started",
            loop_id=updated.id,
            scope_review_rounds=updated.scope_review_rounds,
            target_revision=updated.target_revision,
        )
        return updated

    def _complete_with_approval(self, loop: ReviewLoop) -> WholePlanReviewResult:
        plan = self._store.load_plan_model(self._run_id)
        run = self._store.load_run(self._run_id)
        config = self._store.load_resolved_config(self._run_id)
        limits = planning_limits_from_config(config)
        review_limits = mandatory_review_limits_from_config(config, "whole_plan")
        current_digest = compute_plan_digest(plan)

        loop = self._reload_loop(loop.id)
        if not mandatory_approval_allowed(
            loop,
            current_artifact_digest=current_digest,
            limits=review_limits,
        ):
            return self._terminate(
                "blocked",
                "mandatory whole-plan approval invariant not satisfied",
                loop=loop,
            )

        loop = self._persist_loop(mark_mandatory_approved(loop))

        review_state, digest_bundle = build_plan_approval_validation_context(
            plan=plan,
            approval=loop.to_dict(),
            actual_plan_digest=compute_plan_digest(plan),
            actual_config_digest=compute_config_contract_digest(config),
            actual_input_digest=compute_input_digest(
                config,
                base_dir=run_workspace(run),
            ),
            actual_output_goal_digest=compute_output_goal_digest(
                config,
                base_dir=run_workspace(run),
            ),
            actual_context_spec_digest=(run.get("digests") or {}).get("context_spec"),
        )
        validation = validate_plan(
            plan,
            limits=limits,
            review_state=review_state,
            digests=digest_bundle,
            mode="approval",
            reviews=self._store.list_reviews(self._run_id),
        )
        if not validation.ok:
            return self._terminate(
                "blocked",
                "deterministic plan validation failed after whole-plan approval",
            )

        expected_revision = int(run["revision"])
        revoke_capabilities_for_loop(self._store, self._run_id, loop.id)
        revoke_capabilities_for_phase(self._store, self._run_id, WHOLE_PLAN_REVIEW)
        run = dict(run)
        run["revision"] = expected_revision + 1
        run["phase"] = PLAN_VALIDATED
        self._store.save_run(self._run_id, run, expected_revision)
        self._append_event(
            "whole_plan_review_approved",
            loop_id=loop.id,
            target_revision=plan.revision,
            reviewer_session_id=reviewer_loop_provider_session_id(loop),
        )
        run = self._store.load_run(self._run_id)
        return self._result_from_run(run, ok=True, loop=loop)

    def _pause_for_limit(
        self,
        message: str,
        *,
        loop: ReviewLoop | None,
        exhausted: str,
        limits: Any,
    ) -> WholePlanReviewResult:
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
            phase=WHOLE_PLAN_REVIEW,
            message=message,
            limit=limit,
            consumed=consumed,
            configured=configured,
            role="reviewer",
            revoke_phase=WHOLE_PLAN_REVIEW,
            loop_id=loop.id if loop is not None else None,
            exhausted_budget=exhausted,
        )
        self._append_event(
            "whole_plan_review_limit_exceeded",
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
    ) -> WholePlanReviewResult:
        complete_run_with_outcome(
            self._store,
            self._run_id,
            outcome,
            revoke_phase=WHOLE_PLAN_REVIEW,
            event_type="whole_plan_review_failed",
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

        plan_revision = int(self._store.load_plan(self._run_id)["revision"])
        if plan_revision <= loop.target_revision:
            return loop, False

        return self._prepare_recheck(loop), True

    def _get_or_create_active_loop(self) -> ReviewLoop:
        plan_revision = int(self._store.load_plan(self._run_id)["revision"])
        for payload in reversed(self._store.list_reviews(self._run_id)):
            if payload.get("type") != "whole_plan":
                continue
            loop = ReviewLoop.from_dict(payload)
            if loop.target_revision != plan_revision:
                continue
            if is_terminal_review_loop(loop):
                continue
            return loop
        return self._create_loop()

    def _create_loop(self) -> ReviewLoop:
        plan_revision = int(self._store.load_plan(self._run_id)["revision"])
        loop_id = self._next_loop_id()
        config = self._store.load_resolved_config(self._run_id)
        loop = ReviewLoop(
            id=loop_id,
            type="whole_plan",
            reviewer_session_id=None,
            target_revision=plan_revision,
            scope={"kind": "whole_plan"},
            status="pending",
            lifecycle_status="review_pending",
            active_stage=None,
            scope_review_rounds=0,
            revise_at=resolved_revise_at(config, "whole_plan"),
        )
        self._store.save_review(self._run_id, loop.to_dict())
        self._append_event(
            "whole_plan_review_started",
            loop_id=loop_id,
            target_revision=plan_revision,
        )
        return loop

    def _next_loop_id(self) -> str:
        existing = [
            payload.get("id")
            for payload in self._store.list_reviews(self._run_id)
            if payload.get("type") == "whole_plan" and payload.get("id")
        ]
        index = len(existing) + 1
        return f"review-whole-plan-{index:02d}"

    def _start_reviewer_session(self, loop: ReviewLoop) -> tuple[str, str]:
        run = self._store.load_run(self._run_id)
        config = self._store.load_resolved_config(self._run_id)
        stage = loop.active_stage or "initial_review"
        if stage in {None, "initial_review", "scope_review"}:
            loop, _finding_set_id = allocate_discovery_finding_set_id(loop)
            loop = self._persist_loop(loop)
        package = build_whole_plan_review_package(
            self._run_id,
            run,
            config,
            self._store.load_plan_model(self._run_id),
            loop,
        )
        role_context = resolve_role_session_context(config, run, "reviewer")
        run = self._store.load_run(self._run_id)
        phase = str(run.get("phase") or WHOLE_PLAN_REVIEW)
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
        )
        updated = loop.with_reviewer_provider_session_id(session_id)
        commit_reviewer_loop_provider_session(self._store, self._run_id, updated)
        self._capability_token = deliver_reviewer_turn(
            self._provider,
            self._store,
            self._run_id,
            session_id=session_id,
            loop_id=loop.id,
            phase=phase,
            request=package,
        )
        return session_id, self._capability_token

    def _consume_reviewer_turn(self, session_id: str, loop_id: str) -> str | None:
        run = self._store.load_run(self._run_id)
        config = self._store.load_resolved_config(self._run_id)
        loop = ReviewLoop.from_dict(self._store.load_review(self._run_id, loop_id))
        package = build_whole_plan_review_package(
            self._run_id,
            run,
            config,
            self._store.load_plan_model(self._run_id),
            loop,
        )
        role_context = resolve_role_session_context(config, run, "reviewer")
        phase = str(run.get("phase") or WHOLE_PLAN_REVIEW)
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
                    expected_next_action="continue whole-plan reviewer turn",
                    append_event=self._append_event,
                    model=role_context.model,
                    review_package=package,
                ),
            )
        except SessionRecoveryPaused as exc:
            raise ProviderRunError(str(exc)) from exc
        session_id = turn_outcome.session_id
        sync_reviewer_loop_session_id(
            self._provider,
            self._store,
            self._run_id,
            loop_id,
            session_id,
        )
        return review_decision_from_store(self._store, self._run_id, loop_id)

    def _resume_interrupted_planner_revision(self, loop: ReviewLoop) -> ReviewLoop:
        self._resume_planner_with_findings(loop)
        return self._prepare_recheck(loop)

    def _resume_planner_with_findings(self, loop: ReviewLoop) -> None:
        run = self._store.load_run(self._run_id)
        session_id = primary_planner_provider_session_id(run)
        if session_id is None:
            raise ProviderRunError("primary planner session is missing for revision")

        run = self._store.load_run(self._run_id)
        phase = str(run.get("phase") or WHOLE_PLAN_REVIEW)
        self._capability_token = issue_session_capability(
            self._store,
            self._run_id,
            role="planner",
            phase=phase,
            session_id=session_id,
            session_kind="primary",
        )
        bind_provider_capability(self._provider, self._capability_token)

        config = self._store.load_resolved_config(self._run_id)
        role_context = resolve_role_session_context(config, run, "planner")
        resume_primary_session_with_audit(
            self._append_event,
            self._provider,
            role="planner",
            phase=phase,
            session_id=session_id,
            request={
                "action": "address_review_findings",
                "phase": WHOLE_PLAN_REVIEW,
                "loop_id": loop.id,
                "target_revision": loop.target_revision,
                **primary_review_resume_fields(loop),
                "tool_instructions": {
                    "record_actions": (
                        f"tdp agent review record-actions --run {self._run_id} "
                        "--request <file>"
                    ),
                    "notes": (
                        "Revise the plan for open required findings. Optional findings "
                        "may be fixed, deferred, accepted as-is, or challenged via "
                        "record-actions. Required findings cannot defer or accept_as_is."
                    ),
                },
            },
            model=role_context.model,
            loop_id=loop.id,
        )
        self._consume_planner_turn(session_id)

    def _handle_advisory_handoff(self, loop: ReviewLoop) -> ReviewLoop:
        if not needs_advisory_handoff(loop):
            return loop
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
        self._resume_planner_advisory_handoff(loop)
        loop = self._reload_loop(loop.id)
        if needs_advisory_handoff(loop):
            raise ProviderRunError(
                "advisory handoff completed without qualifying owner actions"
            )
        after = budgets_snapshot(loop)
        if after != before and not owner_actions_require_revision(loop.finding_actions):
            raise ProviderRunError(
                "advisory handoff must not consume revision budget without a fix"
            )
        return self._persist_loop(mark_advisory_handoff_completed(loop))

    def _resume_planner_advisory_handoff(self, loop: ReviewLoop) -> None:
        run = self._store.load_run(self._run_id)
        session_id = primary_planner_provider_session_id(run)
        if session_id is None:
            raise ProviderRunError("primary planner session is missing for advisory handoff")

        phase = str(run.get("phase") or WHOLE_PLAN_REVIEW)
        self._capability_token = issue_session_capability(
            self._store,
            self._run_id,
            role="planner",
            phase=phase,
            session_id=session_id,
            session_kind="primary",
        )
        bind_provider_capability(self._provider, self._capability_token)
        config = self._store.load_resolved_config(self._run_id)
        role_context = resolve_role_session_context(config, run, "planner")
        resume_primary_session_with_audit(
            self._append_event,
            self._provider,
            role="planner",
            phase=phase,
            session_id=session_id,
            request={
                "action": "address_optional_findings",
                "phase": WHOLE_PLAN_REVIEW,
                "loop_id": loop.id,
                "target_revision": loop.target_revision,
                **primary_review_resume_fields(loop),
                "tool_instructions": {
                    "record_actions": (
                        f"tdp agent review record-actions --run {self._run_id} "
                        "--request <file>"
                    ),
                    "notes": (
                        "Record fix|defer|accept_as_is|challenge for optional findings. "
                        "defer/accept_as_is consume no revision cycle."
                    ),
                },
            },
            model=role_context.model,
            loop_id=loop.id,
        )
        self._consume_planner_turn(session_id)

    def _consume_planner_turn(self, session_id: str) -> None:
        run = self._store.load_run(self._run_id)
        config = self._store.load_resolved_config(self._run_id)
        role_context = resolve_role_session_context(config, run, "planner")
        phase = str(run.get("phase") or WHOLE_PLAN_REVIEW)
        try:
            consume_provider_turn_with_session_recovery(
                self._store,
                self._run_id,
                self._provider,
                session_id,
                allowed_signals=_NO_COMPLETION_SIGNALS,
                recovery=build_planner_turn_recovery(
                    self._store,
                    self._run_id,
                    phase=phase,
                    expected_next_action="revise plan after whole-plan review",
                    append_event=self._append_event,
                    model=role_context.model,
                ),
            )
        except SessionRecoveryPaused as exc:
            raise ProviderRunError(str(exc)) from exc
        sync_persisted_session_id(
            self._provider,
            self._store,
            self._run_id,
            session_id,
            field="primary_planner_session_id",
        )

    def _prepare_recheck(self, loop: ReviewLoop) -> ReviewLoop:
        plan_revision = int(self._store.load_plan(self._run_id)["revision"])
        session_id = reviewer_loop_provider_session_id(loop)
        if session_id is None:
            raise ProviderRunError("reviewer session is missing for recheck")

        updated = self._persist_loop(
            mark_verification_pending(loop, target_revision=plan_revision)
        )
        run = self._store.load_run(self._run_id)
        phase = str(run.get("phase") or WHOLE_PLAN_REVIEW)
        config = self._store.load_resolved_config(self._run_id)
        role_context = resolve_role_session_context(config, run, "reviewer")
        self._capability_token = deliver_reviewer_turn(
            self._provider,
            self._store,
            self._run_id,
            session_id=session_id,
            loop_id=loop.id,
            phase=phase,
            request=verification_recheck_request(
                phase=WHOLE_PLAN_REVIEW,
                loop=updated,
                target_revision=plan_revision,
            ),
            model=role_context.model,
        )
        emit_reviewer_session_resumed(
            self._append_event,
            self._provider,
            phase=phase,
            session_id=session_id,
            loop_id=loop.id,
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
    ) -> WholePlanReviewResult:
        return WholePlanReviewResult(
            ok=ok,
            phase=str(run.get("phase") or WHOLE_PLAN_REVIEW),
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


def build_whole_plan_review_package(
    run_id: str,
    run: dict[str, Any],
    config: dict[str, Any],
    plan: Any,
    loop: ReviewLoop,
) -> dict[str, Any]:
    """Package a bounded whole-plan review for a fresh reviewer session."""

    digests = dict(run.get("digests") or {})
    limits = planning_limits_from_config(config)
    review_cfg = (config.get("review") or {}).get("whole_plan") or {}
    rubric = list(
        review_cfg.get("rubric")
        or DEFAULT_CONFIG["review"]["whole_plan"]["rubric"]
    )
    quality_warnings = plan_advisory_warning_messages(plan)
    package: dict[str, Any] = {
        "run_id": run_id,
        "phase": WHOLE_PLAN_REVIEW,
        "type": "whole_plan",
        "loop_id": loop.id,
        "purpose": (
            "Mandatory whole-plan fresh scope review before production"
            if loop.active_stage == "scope_review"
            else "Mandatory whole-plan review before production"
        ),
        "scope": dict(loop.scope),
        "target_revision": loop.target_revision,
        "plan_revision": plan.revision,
        "plan": build_plan_review_snapshot(plan, limits=limits),
        "warnings": quality_warnings,
        **plan_execution_contract_fields(plan),
        "digests": digests,
        **stage_package_fields(loop),
        "protocol_instructions": build_reviewer_protocol_instructions(
            stage=loop.active_stage or "initial_review"
        ),
        "tool_instructions": {
            **build_reviewer_tool_instructions(
                run_id,
                plan_snapshot=(
                    f"tdp agent plan snapshot --run {run_id} --view active"
                ),
            ),
        },
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

