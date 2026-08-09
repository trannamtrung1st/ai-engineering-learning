"""Production-phase orchestration (proposal §4.2, §10, §13)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from top_down_planning.agent_tool.production_service import ProductionAgentService
from top_down_planning.config.context_digests import (
    recompute_context_snapshot_binding_with_diagnostics,
    short_path_for_observability,
    validate_production_snapshot_rebase,
)
from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.domain.models import Plan
from top_down_planning.domain.production import (
    all_applicable_items_processed,
    build_compact_approved_plan,
    completion_claim_asserts_goal_met,
    completion_claim_is_current,
    has_pending_amendment,
    latest_reconciliation_report,
)
from top_down_planning.domain.readiness import detect_deadlock
from top_down_planning.domain.reviews import find_whole_plan_approval
from top_down_planning.domain.run_kind import (
    RUN_KIND_PARENT_EXECUTION,
    RUN_KIND_SUB_TDP_EXECUTION,
    resolve_run_kind,
)
from top_down_planning.package.lineage import unwrap_upstream_accepted_result
from top_down_planning.domain.run_lifecycle import StopRecord
from top_down_planning.orchestrator.producer_session import (
    PRODUCER_BATCH_COMPLETE_SIGNAL,
    build_producer_protocol_instructions,
    build_producer_tool_instructions,
    primary_producer_provider_session_id,
)
from top_down_planning.orchestrator.agent_context import (
    attach_activity_context_to_manifest,
    resolve_activity_session_context,
)
from top_down_planning.orchestrator.capability import (
    adopt_replacement_capability,
    bind_provider_capability,
    issue_session_capability,
    revoke_capabilities_for_phase,
    rotate_session_capability,
)
from top_down_planning.orchestrator.errors import ProviderRunError, SessionRecoveryExhausted, SessionRecoveryPaused
from top_down_planning.orchestrator.resume import short_digest_for_observability
from top_down_planning.orchestrator.phases import (
    PLAN_VALIDATED,
    PRODUCTION,
    WHOLE_OUTPUT_REVIEW,
)
from top_down_planning.orchestrator.run_transitions import (
    complete_run_with_outcome,
    pause_for_limit_exhausted,
)
from top_down_planning.orchestrator.provider_turns import (
    build_producer_turn_recovery,
    consume_producer_provider_turn_with_session_recovery,
    restore_primary_capability_after_focused_review,
)
from top_down_planning.persistence.capabilities import (
    capability_token_file_path,
    read_capability_token_file,
)
from top_down_planning.workspace import run_workspace
from top_down_planning.orchestrator.session_context import ensure_primary_session
from top_down_planning.orchestrator.session_events import (
    resume_primary_session_with_audit,
)
from top_down_planning.persistence.digests import compute_output_digest
from top_down_planning.persistence.interface import RunStore
from top_down_planning.persistence.session_bindings import primary_provider_session_id
from core_tools.provider import Provider

_PRODUCTION_LIMIT_DEFAULTS = DEFAULT_CONFIG["limits"]["production"]


@dataclass(frozen=True)
class ProductionPhaseResult:
    ok: bool
    phase: str
    status: str
    outcome: str | None
    session_id: str | None
    batch_count: int
    reason: str | None = None


class ProductionPhaseOrchestrator:
    """Drive the primary producer session until all items are terminal or blocked."""

    def __init__(
        self,
        store: RunStore,
        run_id: str,
        provider: Provider,
    ) -> None:
        self._store = store
        self._run_id = run_id
        self._provider = provider
        self._production_service = ProductionAgentService(store, run_id)
        self._capability_token: str | None = None

    def run(self) -> ProductionPhaseResult:
        run = self._store.load_run(self._run_id)
        phase = str(run.get("phase") or "")
        if phase == WHOLE_OUTPUT_REVIEW:
            return self._result_from_run(run, ok=True)
        if phase == PLAN_VALIDATED:
            self._require_plan_approval()
            run = self._enter_production_phase()
            phase = PRODUCTION
        elif phase != PRODUCTION:
            raise ProviderRunError(f"run is not ready for production phase: {phase}")

        self._require_plan_approval()

        config = self._store.load_resolved_config(self._run_id)
        loop_limits = _production_loop_limits(config)
        run = self._store.load_run(self._run_id)
        activity_context = resolve_activity_session_context(
            config,
            run,
            "producer",
            "production",
        )
        manifest = build_producer_context_manifest(
            self._run_id,
            run,
            config,
            self._store.load_plan_model(self._run_id),
            production=self._store.load_production(self._run_id),
            activity="production",
            store=self._store,
        )
        session_id = ensure_primary_session(
            self._store,
            self._run_id,
            self._provider,
            role="producer",
            phase=PRODUCTION,
            requested=activity_context,
            manifest=manifest,
            append_event=self._append_event,
            resume_request={"action": "continue", "phase": PRODUCTION},
        )
        role_context = activity_context

        run = self._store.load_run(self._run_id)
        phase = str(run.get("phase") or PRODUCTION)
        self._capability_token = issue_session_capability(
            self._store,
            self._run_id,
            role="producer",
            phase=phase,
            session_id=session_id,
            session_kind="primary",
        )
        bind_provider_capability(self._provider, self._capability_token, store=self._store, run_id=self._run_id)

        batch_agent_turns = _load_batch_agent_turns(self._store, self._run_id)
        while True:
            if self._has_pending_amendment():
                from top_down_planning.orchestrator.plan_amendment import (
                    PlanAmendmentOrchestrator,
                )
                from top_down_planning.orchestrator.run_transitions import pause_run

                run = self._store.load_run(self._run_id)
                kind = resolve_run_kind(run)
                if kind in {RUN_KIND_PARENT_EXECUTION, RUN_KIND_SUB_TDP_EXECUTION}:
                    stop = StopRecord(
                        code="prepared_plan_amendment_required",
                        category="operational",
                        phase=str(run.get("phase") or ""),
                        message=(
                            "prepared execution cannot amend the approved plan in place; "
                            "re-run tdp prepare to materialize a new package"
                        ),
                    )
                    pause_run(
                        self._store,
                        self._run_id,
                        stop=stop,
                        revoke_phase=str(run.get("phase") or ""),
                        event_type="prepared_plan_amendment_required",
                    )
                    return self._result_from_run(
                        self._store.load_run(self._run_id),
                        ok=False,
                        session_id=session_id,
                        reason=stop.message,
                    )

                amendment_result = PlanAmendmentOrchestrator(
                    self._store,
                    self._run_id,
                    self._provider,
                ).run()
                if not amendment_result.ok:
                    return self._result_from_run(
                        self._store.load_run(self._run_id),
                        ok=False,
                        session_id=session_id,
                        reason=amendment_result.reason,
                    )
                producer_token = read_capability_token_file(
                    capability_token_file_path(self._store, self._run_id)
                )
                if producer_token:
                    self._capability_token = producer_token
                session_id = amendment_result.producer_session_id or session_id
                batch_agent_turns = 0
                _persist_batch_agent_turns(self._store, self._run_id, 0)
                continue

            if self._has_blocker_report():
                return self._terminate_from_blocker_report(session_id)

            if self._has_completion_claim():
                return self._complete_production(session_id)

            deadlock = self._detect_deadlock()
            if deadlock is not None:
                return self._terminate(
                    "blocked",
                    deadlock.explanation,
                    session_id=session_id,
                )

            batch_count = self._batch_count()
            if batch_count >= loop_limits["max_batches"]:
                return self._pause_for_limit(
                    limit="max_batches",
                    message=(
                        "production exceeded max_batches "
                        f"({loop_limits['max_batches']})"
                    ),
                    consumed=batch_count,
                    configured=int(loop_limits["max_batches"]),
                    session_id=session_id,
                )

            self._capability_token = restore_primary_capability_after_focused_review(
                self._store,
                self._run_id,
                self._provider,
                review_type="focused_output",
                role="producer",
                current_token=self._capability_token,
            )

            try:
                turn_outcome = consume_producer_provider_turn_with_session_recovery(
                    self._store,
                    self._run_id,
                    self._provider,
                    session_id,
                    recovery=build_producer_turn_recovery(
                        self._store,
                        self._run_id,
                        phase=PRODUCTION,
                        expected_next_action="continue production turn",
                        append_event=self._append_event,
                        model=role_context.model,
                    ),
                )
            except SessionRecoveryPaused as exc:
                return self._result_from_run(
                    self._store.load_run(self._run_id),
                    ok=False,
                    session_id=session_id,
                    reason=str(exc),
                )
            except SessionRecoveryExhausted as exc:
                return self._result_from_run(
                    self._store.load_run(self._run_id),
                    ok=False,
                    session_id=session_id,
                    reason=str(exc),
                )
            session_id = turn_outcome.session_id
            turn_signal = turn_outcome.signal
            if turn_outcome.replaced:
                self._capability_token = adopt_replacement_capability(
                    self._store,
                    self._run_id,
                    current_token=self._capability_token,
                    replacement_token=turn_outcome.capability_token,
                    provider=self._provider,
                )
            self._capability_token = restore_primary_capability_after_focused_review(
                self._store,
                self._run_id,
                self._provider,
                review_type="focused_output",
                role="producer",
                current_token=self._capability_token,
            )
            agent_turns = 1 if turn_outcome.domain_budget_committed else 0
            batch_agent_turns += agent_turns
            _persist_batch_agent_turns(self._store, self._run_id, batch_agent_turns)

            if turn_signal == PRODUCER_BATCH_COMPLETE_SIGNAL:
                batch_agent_turns = 0
                _persist_batch_agent_turns(self._store, self._run_id, 0)
                if (
                    not self._has_completion_claim()
                    and self._batch_count() < loop_limits["max_batches"]
                ):
                    self._resume_producer_turn(session_id, role_context)
                continue

            if self._has_completion_claim():
                continue

            if batch_agent_turns > loop_limits["max_agent_turns_per_batch"]:
                return self._pause_for_limit(
                    limit="max_agent_turns_per_batch",
                    message=(
                        "production exceeded max_agent_turns_per_batch "
                        f"({loop_limits['max_agent_turns_per_batch']})"
                    ),
                    consumed=batch_agent_turns,
                    configured=int(loop_limits["max_agent_turns_per_batch"]),
                    session_id=session_id,
                )

            self._resume_producer_turn(session_id, role_context)

    def _resume_producer_turn(self, session_id: str, role_context: Any) -> None:
        session_id = self._provider.canonical_session_id(session_id)
        run = self._store.load_run(self._run_id)
        phase = str(run.get("phase") or PRODUCTION)
        resume_primary_session_with_audit(
            self._append_event,
            self._provider,
            role="producer",
            phase=phase,
            session_id=session_id,
            request=self._producer_resume_request(),
            model=role_context.model,
        )

        run = self._store.load_run(self._run_id)
        phase = str(run.get("phase") or PRODUCTION)
        self._capability_token = rotate_session_capability(
            self._store,
            self._run_id,
            current_token=self._capability_token,
            role="producer",
            phase=phase,
            session_id=session_id,
            session_kind="primary",
        )
        bind_provider_capability(
            self._provider,
            self._capability_token,
            store=self._store,
            run_id=self._run_id,
        )

    def _has_completion_claim(self) -> bool:
        production = self._store.load_production(self._run_id)
        claim = production.get("completion_claim")
        plan = self._store.load_plan_model(self._run_id)
        return completion_claim_is_current(
            claim if isinstance(claim, dict) else None,
            production=production,
            plan=plan,
        )

    def _has_pending_amendment(self) -> bool:
        production = self._store.load_production(self._run_id)
        return has_pending_amendment(production)

    def _producer_resume_request(self) -> dict[str, Any]:
        production = self._store.load_production(self._run_id)
        plan = self._store.load_plan(self._run_id)
        request: dict[str, Any] = {
            "action": "continue",
            "phase": PRODUCTION,
            "ready_item_ids": self._ready_item_ids(),
            "approved_plan_revision": int(plan["revision"]),
        }
        reconciliation = latest_reconciliation_report(production)
        if reconciliation is not None:
            request["action"] = "continue_after_amendment"
            request["reconciliation"] = reconciliation
        return request

    def _has_blocker_report(self) -> bool:
        production = self._store.load_production(self._run_id)
        report = production.get("blocker_report")
        return isinstance(report, dict)

    def _terminate_from_blocker_report(self, session_id: str) -> ProductionPhaseResult:
        production = self._store.load_production(self._run_id)
        report = production.get("blocker_report") or {}
        evidence = str(report.get("evidence") or "producer reported blocked")
        return self._terminate("blocked", evidence, session_id=session_id)

    def _enter_production_phase(self) -> dict[str, Any]:
        run = self._store.load_run(self._run_id)
        expected_revision = int(run["revision"])
        run = dict(run)
        run["revision"] = expected_revision + 1
        run["phase"] = PRODUCTION
        self._store.save_run(self._run_id, run, expected_revision)
        self._append_event("production_phase_started")
        return self._store.load_run(self._run_id)

    def _complete_production(self, session_id: str) -> ProductionPhaseResult:
        run = self._store.load_run(self._run_id)
        production = self._store.load_production(self._run_id)
        config = self._store.load_resolved_config(self._run_id)
        workspace = run_workspace(run)
        expected_revision = int(run["revision"])
        revoke_capabilities_for_phase(self._store, self._run_id, PRODUCTION)

        digests = dict(run.get("digests") or {})
        old_binding = dict(run.get("context_snapshot_binding") or {})
        old_snapshot_digest = str(digests.get("context_snapshot") or "")

        try:
            from top_down_planning.persistence.evidence_integrity import (
                verify_persisted_production_evidence_snapshots,
            )

            verify_persisted_production_evidence_snapshots(
                self._store,
                self._run_id,
                production,
            )
            new_binding, new_snapshot_digest, diagnostics = (
                recompute_context_snapshot_binding_with_diagnostics(
                    config,
                    workspace=workspace,
                )
            )
            changed_paths: list[str] = []
            if new_snapshot_digest != old_snapshot_digest:
                extra_authorized = None
                if isinstance(production.get("sub_tdps"), dict):
                    from top_down_planning.orchestrator.prepare_resume import (
                        verify_parent_sub_tdp_workspace_matches_accepted,
                    )

                    try:
                        extra_authorized = (
                            verify_parent_sub_tdp_workspace_matches_accepted(
                                self._store,
                                production=production,
                                workspace=workspace,
                            )
                        )
                    except ValueError as exc:
                        return self._terminate(
                            "blocked",
                            str(exc),
                            session_id=session_id,
                        )
                changed_paths = validate_production_snapshot_rebase(
                    old_binding,
                    new_binding,
                    production,
                    workspace=workspace,
                    extra_authorized_paths=extra_authorized or None,
                )
            if isinstance(production.get("sub_tdps"), dict):
                from top_down_planning.orchestrator.prepare_resume import (
                    verify_parent_sub_tdp_workspace_matches_accepted,
                )

                try:
                    verify_parent_sub_tdp_workspace_matches_accepted(
                        self._store,
                        production=production,
                        workspace=workspace,
                    )
                except ValueError as exc:
                    return self._terminate(
                        "blocked",
                        str(exc),
                        session_id=session_id,
                    )

        except ValueError as exc:
            return self._terminate(
                "blocked",
                str(exc),
                session_id=session_id,
            )

        snapshot_rebased = new_snapshot_digest != old_snapshot_digest
        run = dict(run)
        run["revision"] = expected_revision + 1
        run["phase"] = WHOLE_OUTPUT_REVIEW
        digests["output"] = compute_output_digest(production)
        if snapshot_rebased:
            digests["context_snapshot"] = new_snapshot_digest
            run["context_snapshot_binding"] = new_binding
        run["digests"] = digests
        self._store.save_run(self._run_id, run, expected_revision)
        self._append_event(
            "context_snapshot_collected",
            session_id=session_id,
            **diagnostics.to_event_fields(),
        )
        if snapshot_rebased:
            self._append_event(
                "context_snapshot_rebased",
                session_id=session_id,
                phase_transition=f"{PRODUCTION}->{WHOLE_OUTPUT_REVIEW}",
                prior_snapshot_digest=short_digest_for_observability(old_snapshot_digest),
                new_snapshot_digest=short_digest_for_observability(new_snapshot_digest),
                changed_path_count=len(changed_paths),
                changed_paths=[
                    short_path_for_observability(path) for path in changed_paths[:10]
                ],
                **diagnostics.to_event_fields(),
            )
        self._append_event(
            "production_completed",
            session_id=session_id,
            batch_count=self._batch_count(),
        )
        run = self._store.load_run(self._run_id)
        return self._result_from_run(run, ok=True, session_id=session_id)

    def _pause_for_limit(
        self,
        *,
        limit: str,
        message: str,
        consumed: int,
        configured: int,
        session_id: str | None,
    ) -> ProductionPhaseResult:
        pause_for_limit_exhausted(
            self._store,
            self._run_id,
            phase=PRODUCTION,
            message=message,
            limit=f"limits.production.{limit}",
            consumed=consumed,
            configured=configured,
            role="producer",
            revoke_phase=PRODUCTION,
            session_id=session_id,
        )
        self._append_event(
            "production_limit_exceeded",
            limit=limit,
            message=message,
            session_id=session_id,
        )
        run = self._store.load_run(self._run_id)
        return self._result_from_run(run, ok=False, session_id=session_id, reason=message)

    def _terminate(
        self,
        outcome: str,
        message: str,
        *,
        session_id: str | None,
    ) -> ProductionPhaseResult:
        complete_run_with_outcome(
            self._store,
            self._run_id,
            outcome,
            revoke_phase=PRODUCTION,
            event_type="production_failed",
            message=message,
            session_id=session_id,
        )
        run = self._store.load_run(self._run_id)
        return self._result_from_run(run, ok=False, session_id=session_id, reason=message)

    def _all_items_processed(self) -> bool:
        plan = self._store.load_plan_model(self._run_id)
        production = self._store.load_production(self._run_id)
        dispositions = dict(production.get("dispositions") or {})
        return all_applicable_items_processed(plan, dispositions)

    def _detect_deadlock(self):
        plan = self._store.load_plan_model(self._run_id)
        production = self._store.load_production(self._run_id)
        dispositions = dict(production.get("dispositions") or {})
        return detect_deadlock(plan, dispositions)

    def _ready_item_ids(self) -> list[str]:
        snapshot = self._production_service.snapshot(view="ready")
        return list(snapshot.get("ready_item_ids") or [])

    def _batch_count(self) -> int:
        production = self._store.load_production(self._run_id)
        return len(production.get("batches") or [])

    def _result_from_run(
        self,
        run: dict[str, Any],
        *,
        ok: bool,
        session_id: str | None = None,
        reason: str | None = None,
    ) -> ProductionPhaseResult:
        sessions = run.get("sessions") or {}
        return ProductionPhaseResult(
            ok=ok,
            phase=str(run.get("phase") or PRODUCTION),
            status=str(run.get("status") or "running"),
            outcome=run.get("outcome"),
            session_id=session_id or primary_provider_session_id(run, "producer"),
            batch_count=self._batch_count(),
            reason=reason,
        )

    def _append_event(self, event_type: str, **fields: Any) -> None:
        payload = {"type": event_type, "run_id": self._run_id, **fields}
        self._store.append_event(self._run_id, payload)

    def _require_plan_approval(self) -> None:
        plan = self._store.load_plan_model(self._run_id)
        approval = find_whole_plan_approval(
            self._store.list_reviews(self._run_id),
            plan.revision,
        )
        if approval is None:
            raise ProviderRunError(
                "production requires an approved whole-plan review "
                "for the current plan revision"
            )


def build_producer_context_manifest(
    run_id: str,
    run: dict[str, Any],
    config: dict[str, Any],
    plan: Plan,
    *,
    production: dict[str, Any] | None = None,
    activity: str = "production",
    store: RunStore | None = None,
) -> dict[str, Any]:
    """Package producer prompt context and tool usage instructions."""

    limits = _production_loop_limits(config)
    digests = dict(run.get("digests") or {})
    approved_plan = build_compact_approved_plan(plan)

    manifest: dict[str, Any] = attach_activity_context_to_manifest(
        {
        "run_id": run_id,
        "phase": PRODUCTION,
        "approved_plan": approved_plan,
        "loop_limits": limits,
        "digests": digests,
        "protocol_instructions": build_producer_protocol_instructions(),
        "tool_instructions": build_producer_tool_instructions(run_id),
        },
        config=config,
        run=run,
        role="producer",
        activity=activity,  # type: ignore[arg-type]
        output_goal=plan.output_goal,
    )
    if production is not None:
        reconciliation = latest_reconciliation_report(production)
        if reconciliation is not None:
            manifest["reconciliation"] = reconciliation
    prepared = _prepared_execution_section(
        run, production=production, plan=plan, store=store
    )
    if prepared is not None:
        manifest["prepared_execution"] = prepared
    return manifest


def _prepared_execution_section(
    run: dict[str, Any],
    *,
    production: dict[str, Any] | None = None,
    plan: Plan | None = None,
    store: RunStore | None = None,
) -> dict[str, Any] | None:
    """Expose package/unit binding and upstream accepted results to producers."""

    try:
        kind = resolve_run_kind(run)
    except ValueError:
        return None
    binding = run.get("package_binding")
    if not isinstance(binding, dict):
        return None

    if kind == RUN_KIND_SUB_TDP_EXECUTION:
        upstream = binding.get("upstream_accepted_results")
        if upstream is None:
            raise ProviderRunError(
                "prepared child package_binding missing upstream_accepted_results"
            )
        if not isinstance(upstream, list):
            raise ProviderRunError(
                "prepared child upstream_accepted_results must be a list"
            )
        baseline = binding.get("workspace_baseline_accepted_results")
        if baseline is None:
            raise ProviderRunError(
                "prepared child package_binding missing workspace_baseline_accepted_results"
            )
        if not isinstance(baseline, list):
            raise ProviderRunError(
                "prepared child workspace_baseline_accepted_results must be a list"
            )
        external = binding.get("external_prerequisites")
        if not isinstance(external, list):
            raise ProviderRunError(
                "prepared child package_binding missing external_prerequisites"
            )
        normalized_upstream = []
        for wrapper in upstream:
            if not isinstance(wrapper, dict):
                raise ProviderRunError(
                    "upstream_accepted_results entries must be objects"
                )
            try:
                entry = unwrap_upstream_accepted_result(wrapper)
            except ValueError as exc:
                raise ProviderRunError(str(exc)) from exc
            normalized_upstream.append(entry)
        return {
            "package_id": binding.get("package_id"),
            "unit_id": binding.get("selected_unit_id") or binding.get("unit_id"),
            "external_prerequisites": list(external),
            "upstream_accepted_results": normalized_upstream,
        }

    if kind == RUN_KIND_PARENT_EXECUTION and production is not None:
        claim = production.get("completion_claim")
        if isinstance(claim, dict) and claim.get("status") == "integration_pending":
            state = production.get("sub_tdps") or {}
            units = state.get("units") if isinstance(state, dict) else []
            child_results = []
            for unit in units or []:
                if not isinstance(unit, dict):
                    continue
                accepted = unit.get("accepted_result")
                if not isinstance(accepted, dict):
                    if str(unit.get("status") or "") == "completed":
                        raise ProviderRunError(
                            "completed Sub-TDP unit missing accepted_result"
                        )
                    continue
                from top_down_planning.package.lineage import (
                    validate_accepted_child_delivery,
                    verify_accepted_result_attestation,
                    verify_accepted_result_matches_live_delivery,
                )

                try:
                    verify_accepted_result_attestation(unit)
                except ValueError as exc:
                    raise ProviderRunError(
                        f"child accepted_result attestation invalid: {exc}"
                    ) from exc
                if "output_refs" not in accepted or not isinstance(
                    accepted.get("output_refs"), list
                ):
                    raise ProviderRunError(
                        "child accepted_result missing output_refs"
                    )
                if "contributions" not in accepted or not isinstance(
                    accepted.get("contributions"), list
                ):
                    raise ProviderRunError(
                        "child accepted_result missing contributions"
                    )
                if "completion_assessment" not in accepted:
                    raise ProviderRunError(
                        "child accepted_result missing completion_assessment"
                    )
                if not str(accepted.get("output_digest") or "").strip():
                    raise ProviderRunError(
                        "child accepted_result missing output_digest"
                    )
                if not str(accepted.get("package_id") or "").strip():
                    raise ProviderRunError(
                        "child accepted_result missing package_id"
                    )
                child_run_id = str(
                    accepted.get("child_run_id") or unit.get("child_run_id") or ""
                ).strip()
                if not child_run_id:
                    raise ProviderRunError(
                        "child accepted_result missing child_run_id"
                    )
                if store is None:
                    raise ProviderRunError(
                        "integration producer requires store to validate child delivery"
                    )
                try:
                    child_run = store.load_run(child_run_id)
                    child_production = store.load_production(child_run_id)
                    validate_accepted_child_delivery(
                        store=store,
                        child_run_id=child_run_id,
                        child_run=child_run,
                        child_production=child_production,
                        verify_evidence=True,
                    )
                    live_accepted = verify_accepted_result_matches_live_delivery(
                        unit,
                        child_run=child_run,
                        child_production=child_production,
                    )
                except (OSError, ValueError, KeyError) as exc:
                    raise ProviderRunError(
                        f"child delivery invalid for integration: {exc}"
                    ) from exc
                child_results.append(dict(live_accepted))
            return {
                "package_id": binding.get("package_id"),
                "unit_id": None,
                "integration": True,
                "external_prerequisites": [],
                "upstream_accepted_results": child_results,
                "parent_output_goal": plan.output_goal if plan is not None else "",
                "parent_acceptance_criteria": (
                    list(plan.acceptance) if plan is not None else []
                ),
                "synthesis_assessment": claim.get("goal_assessment"),
            }
    return None


def _production_loop_limits(config: dict[str, Any]) -> dict[str, int]:
    production_limits = (config.get("limits") or {}).get("production") or {}
    return {
        "max_batches": int(
            production_limits.get(
                "max_batches",
                _PRODUCTION_LIMIT_DEFAULTS["max_batches"],
            )
        ),
        "max_agent_turns_per_batch": int(
            production_limits.get(
                "max_agent_turns_per_batch",
                _PRODUCTION_LIMIT_DEFAULTS["max_agent_turns_per_batch"],
            )
        ),
    }

def _persist_session_id(
    store: RunStore,
    run_id: str,
    session_id: str,
) -> dict[str, Any]:
    return commit_primary_provider_session_binding(
        store,
        run_id,
        role="producer",
        provider_session_id=session_id,
        provider="cursor",
    )


def _load_batch_agent_turns(store: RunStore, run_id: str) -> int:
    run = store.load_run(run_id)
    production_loop = run["production_loop"]
    if not isinstance(production_loop, dict):
        raise ProviderRunError("run is missing production_loop state")
    return int(production_loop["current_batch_agent_turns"])


def _persist_batch_agent_turns(store: RunStore, run_id: str, turns: int) -> None:
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["production_loop"] = {
        "current_batch_agent_turns": turns,
    }
    store.save_run(run_id, run, expected_revision)
