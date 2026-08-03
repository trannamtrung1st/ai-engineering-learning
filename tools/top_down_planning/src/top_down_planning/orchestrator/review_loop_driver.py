"""Shared review-loop driver for mandatory whole-artifact and focused reviews."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Protocol, runtime_checkable

from top_down_planning.domain.reviews import (
    ReviewLoop,
    allocate_discovery_finding_set_id,
    advisory_handoff_allowed,
    budgets_snapshot,
    complete_advisory_handoff_if_owner_responses_recorded,
    finding_actions_for_active_set,
    focused_review_revision_limit_from_config,
    is_revision_requested_status,
    is_terminal_review_loop,
    loop_revise_at,
    mandatory_review_limits_from_config,
    mark_advisory_handoff_completed,
    needs_advisory_handoff,
    build_primary_owner_finding_guidance,
    owner_actions_require_revision,
    policy_observability_fields_for_loop,
    prepare_review_incomplete_retry,
    required_open_findings,
    verification_required_for_loop,
)
from top_down_planning.orchestrator.mandatory_review_stages import (
    approved_means_final_approval,
    approved_means_start_scope_review,
    enter_owner_revision_cycle,
    is_scope_review_stage,
    limit_message,
    mark_findings_open,
    mark_limit_reached_loop,
    mark_verification_pending,
    mandatory_orchestration_decision,
    needs_fresh_scope_review_clear,
    prepare_scope_review_loop,
    ready_for_mandatory_final_approval,
    seed_mandatory_loop_fields,
    verification_recheck_request,
)
from top_down_planning.orchestrator.review_loop_bootstrap import bootstrap_whole_review_loop
from top_down_planning.orchestrator.review_loop_profile import (
    FOCUSED_PROFILE,
    MANDATORY_WHOLE_PROFILE,
    ReviewLoopProfile,
)
from top_down_planning.orchestrator.agent_context import resolve_role_session_context
from top_down_planning.orchestrator.capability import (
    adopt_replacement_capability,
    bind_provider_capability,
    issue_session_capability,
    revoke_capabilities_for_loop,
    rotate_session_capability,
)
from top_down_planning.orchestrator.reviewer_session import (
    ReviewerRecheckRequiresNewSession,
    begin_reviewer_review,
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
from top_down_planning.orchestrator.run_transitions import (
    complete_run_with_outcome,
    pause_for_limit_exhausted,
)
from top_down_planning.orchestrator.provider_turns import (
    consume_provider_turn_with_session_recovery,
)
from top_down_planning.orchestrator.session_events import (
    emit_reviewer_session_resumed,
    emit_reviewer_session_started,
    release_reviewer_session_after_decision,
    resume_primary_session_with_audit,
)
from top_down_planning.orchestrator.review_loop_types import (
    MandatoryWholeReviewResult,
    MandatoryWholeReviewSpec,
    OwnerHandoff,
    reject_nonterminal_mandatory_contract_v1_loop,
)
from top_down_planning.persistence.interface import RunStore
from core_tools.provider import Provider

_NO_COMPLETION_SIGNALS = frozenset[str]()


class ReviewLoopAdapter(Protocol):
    @property
    def profile(self) -> ReviewLoopProfile: ...

    @property
    def spec(self) -> MandatoryWholeReviewSpec: ...

    def preflight(self, loop: ReviewLoop | None) -> None: ...

    def current_artifact_binding(self) -> tuple[int, str]: ...

    def new_loop(self, loop_id: str) -> ReviewLoop: ...

    def build_review_package(
        self,
        run: dict[str, Any],
        config: dict[str, Any],
        loop: ReviewLoop,
    ) -> dict[str, Any]: ...

    def primary_owner_session_id(self, run: dict[str, Any]) -> str | None: ...

    def build_owner_request(
        self,
        loop: ReviewLoop,
        config: dict[str, Any],
        handoff: OwnerHandoff,
    ) -> dict[str, Any]: ...

    def build_owner_turn_recovery(
        self,
        phase: str,
        append_event: Any,
        model: str | None,
    ) -> Any: ...

    def build_reviewer_turn_recovery(
        self,
        loop_id: str,
        phase: str,
        append_event: Any,
        model: str | None,
        review_package: dict[str, Any],
    ) -> Any: ...

    def after_owner_turn(self, session_id: str) -> None: ...

    def complete_approval(self, loop: ReviewLoop) -> MandatoryWholeReviewResult: ...

    def phase_for_session(self, loop: ReviewLoop, run: dict[str, Any]) -> str: ...

    def prepare_recheck_transition(
        self, loop: ReviewLoop, target_revision: int
    ) -> ReviewLoop: ...

    def enter_revision_cycle(
        self, loop: ReviewLoop, revision_cycles: int
    ) -> ReviewLoop: ...

    def complete_success(self, loop: ReviewLoop) -> Any: ...

    def reviewer_session_started_scope(self, loop: ReviewLoop) -> dict[str, Any] | None:
        ...


@runtime_checkable
class FocusedReviewLoopAdapter(ReviewLoopAdapter, Protocol):
    def handle_blocked(self, loop: ReviewLoop) -> Any: ...

    def handle_limit_exhausted(
        self, loop: ReviewLoop, revision_cycles: int
    ) -> Any: ...

    def handle_review_incomplete(self, loop: ReviewLoop) -> Any: ...


class ReviewLoopDriver:
    """Owns the shared review run loop for mandatory and focused profiles."""

    def __init__(
        self,
        store: RunStore,
        run_id: str,
        provider: Provider,
        adapter: ReviewLoopAdapter,
    ) -> None:
        self._store = store
        self._run_id = run_id
        self._provider = provider
        self._adapter = adapter
        self._capability_token: str | None = None
        if not adapter.profile.is_mandatory_gate and not isinstance(
            adapter, FocusedReviewLoopAdapter
        ):
            raise OrchestratorInvariantError(
                "focused review profile requires FocusedReviewLoopAdapter"
            )

    def _focused_adapter(self) -> FocusedReviewLoopAdapter:
        return self._adapter  # type: ignore[return-value]

    @property
    def spec(self) -> MandatoryWholeReviewSpec:
        return self._adapter.spec

    @property
    def profile(self) -> ReviewLoopProfile:
        return self._adapter.profile

    def run(self, loop_id: str | None = None) -> Any:
        if self.profile.is_mandatory_gate:
            return self._run_mandatory()
        if loop_id is None:
            raise ProviderRunError("focused review driver requires loop_id")
        return self._run_focused(loop_id)

    def _run_mandatory(self) -> MandatoryWholeReviewResult:
        spec = self.spec
        run = self._store.load_run(self._run_id)
        phase = str(run.get("phase") or "")
        if phase == spec.approved_phase:
            return self.result_from_run(run, ok=True)
        if phase != spec.phase:
            raise ProviderRunError(f"run is not in {spec.review_label} phase: {phase}")

        self._adapter.preflight(None)
        config = self._store.load_resolved_config(self._run_id)
        limits = mandatory_review_limits_from_config(config, spec.limits_key)
        loop, deliver_on_existing_session = bootstrap_whole_review_loop(
            self._get_or_create_active_loop(),
            current_revision=self._adapter.current_artifact_binding()[0],
            resume_interrupted_revision=self._resume_interrupted_owner_revision,
            normalize_loop_for_resume=self._normalize_loop_for_resume,
        )
        self._adapter.preflight(loop)
        reject_nonterminal_mandatory_contract_v1_loop(loop)
        loop = self._persist_loop(seed_mandatory_loop_fields(loop))
        return self._drive_loop(loop, deliver_on_existing_session, limits)

    def _run_focused(self, loop_id: str) -> Any:
        loop = ReviewLoop.from_dict(self._store.load_review(self._run_id, loop_id))
        if loop.type not in {"focused_plan", "focused_output"}:
            raise ProviderRunError(f"review loop {loop_id} is not a focused review loop")
        self._adapter.preflight(loop)
        config = self._store.load_resolved_config(self._run_id)
        max_revision_cycles = focused_review_revision_limit_from_config(
            config,
            loop.type,  # type: ignore[arg-type]
        )
        loop, reviewer_turn_delivered = self._normalize_loop_for_resume(loop)
        deliver_on_existing_session = (
            reviewer_loop_provider_session_id(loop) is not None
            and not reviewer_turn_delivered
        )
        return self._drive_loop(
            loop,
            deliver_on_existing_session,
            max_revision_cycles,
        )

    def _drive_loop(
        self,
        loop: ReviewLoop,
        deliver_on_existing_session: bool,
        limits: Any,
    ) -> Any:
        spec = self.spec
        reviewer_decision: str | None = None

        while True:
            if loop.status == "pending":
                session_id = reviewer_loop_provider_session_id(loop)
                run = self._store.load_run(self._run_id)
                phase = self._adapter.phase_for_session(loop, run)
                if session_id is None:
                    session_id, self._capability_token = self._start_reviewer_session(loop)
                    loop = self._reload_loop(loop.id)
                    deliver_on_existing_session = False
                elif deliver_on_existing_session:
                    config = self._store.load_resolved_config(self._run_id)
                    role_context = resolve_role_session_context(
                        config, run, "reviewer"
                    )
                    package = self._adapter.build_review_package(run, config, loop)
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
                reviewer_decision = self._consume_reviewer_turn(session_id, loop.id)
                loop = self._reload_loop(loop.id)
                if reviewer_decision is None:
                    raise reviewer_decision_missing_error()
                if loop.status == "pending":
                    run = self._store.load_run(self._run_id)
                    phase = self._adapter.phase_for_session(loop, run)
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

            stage_decision = self._resolve_stage_decision(loop, reviewer_decision)
            reviewer_decision = None

            if stage_decision in {"approved", "verified"}:
                loop = self._reload_loop(loop.id)
                if self.profile.is_mandatory_gate:
                    if approved_means_final_approval(loop):
                        if not ready_for_mandatory_final_approval(loop):
                            raise OrchestratorInvariantError(
                                "approved reviewer decision missing "
                                "scope_review_result approval record"
                            )
                        return self._adapter.complete_approval(loop)
                    if approved_means_start_scope_review(loop):
                        transition = self._begin_scope_review(loop, limits)
                        if isinstance(transition, MandatoryWholeReviewResult):
                            return transition
                        loop = transition
                        deliver_on_existing_session = False
                        continue
                    raise ProviderRunError(
                        "approved decision left required findings unresolved"
                    )
                return self._adapter.complete_success(loop)

            if stage_decision == "blocked":
                if self.profile.is_mandatory_gate:
                    revoke_capabilities_for_loop(self._store, self._run_id, loop.id)
                    if loop.lifecycle_status == "limit_reached":
                        exhausted = loop.exhausted_budget or "verification_revision"
                        return self._pause_for_limit(
                            limit_message(
                                limits,
                                exhausted=exhausted,
                                review_label=spec.review_label,
                            ),
                            loop=loop,
                            exhausted=exhausted,
                            limits=limits,
                        )
                    return self._terminate(
                        "blocked",
                        f"{spec.event_prefix.replace('_', '-')} reviewer blocked the run",
                        loop=loop,
                    )
                return self._focused_adapter().handle_blocked(loop)

            if stage_decision == "review_incomplete" or loop.status == "review_incomplete":
                if self.profile.is_mandatory_gate:
                    budgets = budgets_snapshot(loop)
                    marker = loop.review_incomplete or {}
                    reason = str(
                        marker.get("reason")
                        or f"{spec.review_label} could not be completed"
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
                    return MandatoryWholeReviewResult(
                        ok=False,
                        phase=spec.phase,
                        status=str(run.get("status") or "paused"),
                        outcome=None,
                        loop_id=loop.id,
                        reviewer_session_id=reviewer_loop_provider_session_id(loop),
                        revision_cycles=budgets["revision_cycles"],
                        reason=reason,
                    )
                return self._focused_adapter().handle_review_incomplete(loop)

            if stage_decision in {"advisory_pending", "pending"}:
                loop = self._handle_advisory_handoff(loop)
                if loop.status == "review_incomplete":
                    return self._focused_adapter().handle_review_incomplete(loop)
                if loop.status == "approved":
                    if self.profile.is_mandatory_gate:
                        if ready_for_mandatory_final_approval(loop):
                            return self._adapter.complete_approval(loop)
                        if approved_means_start_scope_review(loop) or needs_fresh_scope_review_clear(
                            loop
                        ):
                            transition = self._begin_scope_review(loop, limits)
                            if isinstance(transition, MandatoryWholeReviewResult):
                                return transition
                            loop = transition
                            deliver_on_existing_session = False
                            continue
                    else:
                        return self._adapter.complete_success(loop)
                if required_open_findings(loop.findings, loop_revise_at(loop)):
                    stage_decision = "changes_requested"
                elif verification_required_for_loop(loop):
                    active = finding_actions_for_active_set(loop)
                    if owner_actions_require_revision(active):
                        stage_decision = "changes_requested"
                    else:
                        if self.profile.is_mandatory_gate:
                            loop = self._persist_loop(mark_findings_open(loop))
                            loop = self._persist_loop(enter_owner_revision_cycle(loop))
                        loop = self._prepare_recheck(loop)
                        continue
                elif needs_advisory_handoff(loop):
                    loop = self._pause_advisory_handoff_incomplete(loop)
                    return self._focused_adapter().handle_review_incomplete(loop)
                else:
                    raise OrchestratorInvariantError(
                        "advisory handoff completed without resolving optional "
                        "finding policy"
                    )

            if stage_decision not in {"needs_revision", "changes_requested"}:
                label = "mandatory" if self.profile.is_mandatory_gate else "focused"
                raise ProviderRunError(f"unexpected {label} review decision: {stage_decision}")

            loop = self._reload_loop(loop.id)
            if self.profile.is_mandatory_gate:
                prior_finding_set_id = loop.finding_set_id
                was_scope_review_stage = is_scope_review_stage(loop)
                loop = self._persist_loop(mark_findings_open(loop))
                if was_scope_review_stage:
                    self._append_event(
                        f"{spec.event_prefix}_scope_review_changes_requested",
                        loop_id=loop.id,
                        review_type=loop.type,
                        stage="scope_review",
                        finding_set_id=loop.finding_set_id,
                        prior_finding_set_id=prior_finding_set_id,
                        finding_count=len(loop.findings),
                    )

            revision_cycles = loop.revision_cycles + 1
            loop = self._persist_loop(
                self._adapter.enter_revision_cycle(loop, revision_cycles)
            )

            max_cycles = (
                limits.max_revision_cycles
                if self.profile.is_mandatory_gate
                else int(limits)
            )
            if revision_cycles >= max_cycles:
                if self.profile.is_mandatory_gate:
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
                            review_label=spec.review_label,
                        ),
                        loop=loop,
                        exhausted="verification_revision",
                        limits=limits,
                    )
                return self._focused_adapter().handle_limit_exhausted(loop, revision_cycles)

            self._resume_owner_with_findings(loop)
            loop = self._prepare_recheck(loop)

    def _resolve_stage_decision(
        self,
        loop: ReviewLoop,
        reviewer_decision: str | None,
    ) -> str:
        if self.profile.is_mandatory_gate:
            return mandatory_orchestration_decision(loop)
        if reviewer_decision is not None:
            decision = reviewer_decision
        else:
            decision = loop.status
        if decision == "needs_revision":
            return "changes_requested"
        return decision

    def _begin_scope_review(
        self,
        loop: ReviewLoop,
        limits: Any,
    ) -> ReviewLoop | MandatoryWholeReviewResult:
        spec = self.spec
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
                    review_label=spec.review_label,
                ),
                loop=loop,
                exhausted="scope_review",
                limits=limits,
            )
        if reviewer_loop_provider_session_id(loop) is not None:
            revoke_capabilities_for_loop(self._store, self._run_id, loop.id)
        updated = self._persist_loop(prepare_scope_review_loop(loop))
        self._append_event(
            f"{spec.event_prefix}_scope_review_started",
            loop_id=updated.id,
            review_type=updated.type,
            stage="scope_review",
            scope_review_rounds=updated.scope_review_rounds,
            target_revision=updated.target_revision,
        )
        return updated

    def _pause_advisory_handoff_incomplete(self, loop: ReviewLoop) -> ReviewLoop:
        loop, _reason = pause_advisory_handoff_incomplete(
            self._store,
            self._run_id,
            loop,
            pause_run=self.profile.pause_run_on_review_incomplete,
        )
        return self._persist_loop(loop)

    def _pause_for_limit(
        self,
        message: str,
        *,
        loop: ReviewLoop | None,
        exhausted: str,
        limits: Any,
    ) -> MandatoryWholeReviewResult:
        spec = self.spec
        if exhausted == "verification_revision":
            limit = "max_revision_cycles"
            consumed = int(
                loop.revision_cycles if loop is not None else limits.max_revision_cycles
            )
            configured = int(limits.max_revision_cycles)
        else:
            limit = "max_scope_review_rounds"
            consumed = int(
                loop.scope_review_rounds
                if loop is not None
                else limits.max_scope_review_rounds
            )
            configured = int(limits.max_scope_review_rounds)
        pause_for_limit_exhausted(
            self._store,
            self._run_id,
            phase=spec.phase,
            message=message,
            limit=limit,
            consumed=consumed,
            configured=configured,
            role="reviewer",
            revoke_phase=spec.phase,
            loop_id=loop.id if loop is not None else None,
            exhausted_budget=exhausted,
        )
        self._append_event(
            f"{spec.event_prefix}_review_limit_exceeded",
            message=message,
            loop_id=loop.id if loop is not None else None,
            exhausted_budget=exhausted,
        )
        run = self._store.load_run(self._run_id)
        return self.result_from_run(run, ok=False, reason=message)

    def terminate(
        self,
        outcome: str,
        message: str,
        *,
        loop: ReviewLoop | None = None,
    ) -> MandatoryWholeReviewResult:
        return self._terminate(outcome, message, loop=loop)

    def _terminate(
        self,
        outcome: str,
        message: str,
        *,
        loop: ReviewLoop | None = None,
    ) -> MandatoryWholeReviewResult:
        spec = self.spec
        complete_run_with_outcome(
            self._store,
            self._run_id,
            outcome,
            revoke_phase=spec.phase,
            event_type=f"{spec.event_prefix}_review_failed",
            message=message,
            loop_id=loop.id if loop is not None else None,
            lifecycle_status=loop.lifecycle_status if loop is not None else None,
        )
        run = self._store.load_run(self._run_id)
        return self.result_from_run(run, ok=False, reason=message)

    def _normalize_loop_for_resume(self, loop: ReviewLoop) -> tuple[ReviewLoop, bool]:
        if loop.status == "review_incomplete":
            retried = prepare_review_incomplete_retry(loop)
            retried, _finding_set_id = allocate_discovery_finding_set_id(retried)
            return self._persist_loop(retried), False

        if not is_revision_requested_status(loop.status):
            return loop, False

        artifact_revision, _digest = self._adapter.current_artifact_binding()
        if artifact_revision <= loop.target_revision:
            return loop, False

        return self._prepare_recheck(loop), True

    def _get_or_create_active_loop(self) -> ReviewLoop:
        spec = self.spec
        artifact_revision, _digest = self._adapter.current_artifact_binding()
        for payload in reversed(self._store.list_reviews(self._run_id)):
            if payload.get("type") != spec.review_type:
                continue
            loop = ReviewLoop.from_dict(payload)
            if loop.target_revision != artifact_revision:
                continue
            if is_terminal_review_loop(loop):
                continue
            return loop
        return self._create_loop()

    def _create_loop(self) -> ReviewLoop:
        spec = self.spec
        artifact_revision, _digest = self._adapter.current_artifact_binding()
        loop_id = self._next_loop_id()
        loop = self._adapter.new_loop(loop_id)
        self._store.save_review(self._run_id, loop.to_dict())
        self._append_event(
            f"{spec.event_prefix}_review_started",
            loop_id=loop_id,
            review_type=loop.type,
            target_revision=artifact_revision,
        )
        return loop

    def _next_loop_id(self) -> str:
        spec = self.spec
        existing = [
            payload.get("id")
            for payload in self._store.list_reviews(self._run_id)
            if payload.get("type") == spec.review_type and payload.get("id")
        ]
        index = len(existing) + 1
        return f"{spec.loop_id_prefix}-{index:02d}"

    def _start_reviewer_session(self, loop: ReviewLoop) -> tuple[str, str]:
        spec = self.spec
        run = self._store.load_run(self._run_id)
        config = self._store.load_resolved_config(self._run_id)
        stage = loop.active_stage or "initial_review"
        should_allocate = self.profile.allocate_discovery_on_any_start or stage in {
            None,
            "initial_review",
            "scope_review",
        }
        if should_allocate:
            loop, _finding_set_id = allocate_discovery_finding_set_id(loop)
            loop = self._persist_loop(loop)
        package = self._adapter.build_review_package(run, config, loop)
        role_context = resolve_role_session_context(config, run, "reviewer")
        run = self._store.load_run(self._run_id)
        phase = self._adapter.phase_for_session(loop, run)
        session_id, self._capability_token = begin_reviewer_review(
            self._provider,
            self._store,
            self._run_id,
            loop_id=loop.id,
            review_package=package,
            phase=phase,
            model=role_context.model,
        )
        extra = self._adapter.reviewer_session_started_scope(loop) or {}
        emit_reviewer_session_started(
            self._append_event,
            self._provider,
            phase=phase,
            session_id=session_id,
            loop=loop,
            **extra,
        )
        return session_id, self._capability_token

    def _consume_reviewer_turn(self, session_id: str, loop_id: str) -> str | None:
        run = self._store.load_run(self._run_id)
        config = self._store.load_resolved_config(self._run_id)
        loop = ReviewLoop.from_dict(self._store.load_review(self._run_id, loop_id))
        package = self._adapter.build_review_package(run, config, loop)
        role_context = resolve_role_session_context(config, run, "reviewer")
        phase = self._adapter.phase_for_session(loop, run)
        try:
            turn_outcome = consume_provider_turn_with_session_recovery(
                self._store,
                self._run_id,
                self._provider,
                session_id,
                allowed_signals=_NO_COMPLETION_SIGNALS,
                recovery=self._adapter.build_reviewer_turn_recovery(
                    loop_id,
                    phase,
                    self._append_event,
                    role_context.model,
                    package,
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
        return release_reviewer_session_after_decision(
            self._append_event,
            self._provider,
            self._store,
            self._run_id,
            phase=phase,
            loop_id=loop_id,
            session_id=session_id,
        )

    def _resume_interrupted_owner_revision(self, loop: ReviewLoop) -> ReviewLoop:
        self._resume_owner_with_findings(loop)
        return self._prepare_recheck(loop)

    def _resume_owner_with_findings(self, loop: ReviewLoop) -> None:
        spec = self.spec
        run = self._store.load_run(self._run_id)
        session_id = self._adapter.primary_owner_session_id(run)
        if session_id is None:
            raise ProviderRunError(
                f"primary {spec.owner_role} session is missing for revision"
            )

        run = self._store.load_run(self._run_id)
        phase = self._adapter.phase_for_session(loop, run)
        self._capability_token = issue_session_capability(
            self._store,
            self._run_id,
            role=spec.owner_role,
            phase=phase,
            session_id=session_id,
            session_kind="primary",
        )
        bind_provider_capability(self._provider, self._capability_token)

        config = self._store.load_resolved_config(self._run_id)
        role_context = resolve_role_session_context(config, run, spec.owner_role)
        resume_primary_session_with_audit(
            self._append_event,
            self._provider,
            role=spec.owner_role,
            phase=phase,
            session_id=session_id,
            request=self._adapter.build_owner_request(loop, config, "revision"),
            model=role_context.model,
            loop_id=loop.id,
        )
        self._consume_owner_turn(session_id, phase)
        self._adapter.after_owner_turn(session_id)

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
            **policy_observability_fields_for_loop(loop),
        )
        self._resume_owner_advisory_handoff(loop)
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

    def _resume_owner_advisory_handoff(self, loop: ReviewLoop) -> None:
        spec = self.spec
        run = self._store.load_run(self._run_id)
        session_id = self._adapter.primary_owner_session_id(run)
        if session_id is None:
            raise ProviderRunError(
                f"primary {spec.owner_role} session is missing for advisory handoff"
            )
        phase = self._adapter.phase_for_session(loop, run)
        self._capability_token = issue_session_capability(
            self._store,
            self._run_id,
            role=spec.owner_role,
            phase=phase,
            session_id=session_id,
            session_kind="primary",
        )
        bind_provider_capability(self._provider, self._capability_token)
        config = self._store.load_resolved_config(self._run_id)
        role_context = resolve_role_session_context(config, run, spec.owner_role)
        resume_primary_session_with_audit(
            self._append_event,
            self._provider,
            role=spec.owner_role,
            phase=phase,
            session_id=session_id,
            request=self._adapter.build_owner_request(loop, config, "advisory"),
            model=role_context.model,
            loop_id=loop.id,
        )
        self._consume_owner_turn(session_id, phase)

    def _consume_owner_turn(self, session_id: str, phase: str) -> None:
        spec = self.spec
        run = self._store.load_run(self._run_id)
        config = self._store.load_resolved_config(self._run_id)
        role_context = resolve_role_session_context(config, run, spec.owner_role)
        try:
            consume_provider_turn_with_session_recovery(
                self._store,
                self._run_id,
                self._provider,
                session_id,
                allowed_signals=_NO_COMPLETION_SIGNALS,
                recovery=self._adapter.build_owner_turn_recovery(
                    phase,
                    self._append_event,
                    role_context.model,
                ),
            )
        except SessionRecoveryPaused as exc:
            raise ProviderRunError(str(exc)) from exc

    def _prepare_recheck(self, loop: ReviewLoop) -> ReviewLoop:
        artifact_revision, _digest = self._adapter.current_artifact_binding()
        run = self._store.load_run(self._run_id)
        phase = self._adapter.phase_for_session(loop, run)
        config = self._store.load_resolved_config(self._run_id)
        role_context = resolve_role_session_context(config, run, "reviewer")
        updated = self._persist_loop(
            self._adapter.prepare_recheck_transition(loop, artifact_revision)
        )
        artifact_revision, artifact_digest = self._adapter.current_artifact_binding()
        verification_request = verification_recheck_request(
            phase=phase,
            loop=updated,
            target_revision=artifact_revision,
            artifact_digest=artifact_digest,
        )
        try:
            session_id = resolve_reviewer_session_for_recheck(
                loop,
                target_revision=loop.target_revision,
                current_revision=artifact_revision,
            )
        except ReviewerRecheckRequiresNewSession:
            loop = self._persist_loop(loop.with_reviewer_session_released())
            updated = self._persist_loop(
                self._adapter.prepare_recheck_transition(loop, artifact_revision)
            )
            verification_request = verification_recheck_request(
                phase=phase,
                loop=updated,
                target_revision=artifact_revision,
                artifact_digest=artifact_digest,
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
            extra = self._adapter.reviewer_session_started_scope(loop) or {}
            emit_reviewer_session_started(
                self._append_event,
                self._provider,
                phase=phase,
                session_id=session_id,
                loop=updated,
                replacement=True,
                **extra,
            )
            return updated

        if not self.profile.is_mandatory_gate:
            updated = updated.with_reviewer_provider_session_id(session_id)
            self._persist_loop(updated)

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

    def persist_loop(self, loop: ReviewLoop) -> ReviewLoop:
        return self._persist_loop(loop)

    def reload_loop(self, loop_id: str) -> ReviewLoop:
        return self._reload_loop(loop_id)

    def append_event(self, event_type: str, **fields: Any) -> None:
        self._append_event(event_type, **fields)

    def _persist_loop(self, loop: ReviewLoop) -> ReviewLoop:
        self._store.save_review(self._run_id, loop.to_dict())
        return loop

    def _reload_loop(self, loop_id: str) -> ReviewLoop:
        return ReviewLoop.from_dict(self._store.load_review(self._run_id, loop_id))

    def result_from_run(
        self,
        run: dict[str, Any],
        *,
        ok: bool,
        loop: ReviewLoop | None = None,
        reason: str | None = None,
    ) -> MandatoryWholeReviewResult:
        spec = self.spec
        return MandatoryWholeReviewResult(
            ok=ok,
            phase=str(run.get("phase") or spec.phase),
            status=str(run.get("status") or "running"),
            outcome=run.get("outcome"),
            loop_id=loop.id if loop is not None else None,
            reviewer_session_id=(
                reviewer_loop_provider_session_id(loop) if loop is not None else None
            ),
            revision_cycles=loop.revision_cycles if loop is not None else 0,
            reason=reason,
        )

    def _append_event(self, event_type: str, **fields: Any) -> None:
        payload = {"type": event_type, "run_id": self._run_id, **fields}
        self._store.append_event(self._run_id, payload)
