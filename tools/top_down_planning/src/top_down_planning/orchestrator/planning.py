"""Planning-phase orchestration (proposal §3, §4.1, §13)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from top_down_planning.agent_tool.config import planning_limits_from_config
from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.domain.reviews import blocking_focused_findings_for_items
from top_down_planning.domain.validators import ValidationResult, plan_advisory_warning_messages, validate_plan
from top_down_planning.orchestrator.capability import (
    adopt_replacement_capability,
    bind_provider_capability,
    issue_session_capability,
    rotate_session_capability,
)
from top_down_planning.orchestrator.errors import ProviderRunError, SessionRecoveryExhausted, SessionRecoveryPaused
from top_down_planning.orchestrator.agent_context import (
    attach_activity_context_to_manifest,
    resolve_activity_session_context,
)
from top_down_planning.orchestrator.phases import PLANNING, WHOLE_PLAN_REVIEW
from top_down_planning.orchestrator.run_transitions import (
    pause_for_limit_exhausted,
    reconcile_pending_capability_revocation,
)
from top_down_planning.orchestrator.planner_session import (
    PLANNER_CANDIDATE_READY_SIGNAL,
    build_planner_protocol_instructions,
    build_planner_tool_instructions,
    primary_planner_provider_session_id,
)
from top_down_planning.orchestrator.provider_turns import (
    build_planner_turn_recovery,
    consume_provider_turn_with_session_recovery,
    restore_primary_capability_after_focused_review,
    sync_planning_items_added,
)
from top_down_planning.orchestrator.session_context import ensure_primary_session
from top_down_planning.orchestrator.session_events import (
    resume_primary_session_with_audit,
)
from top_down_planning.persistence.commit import CommitSpec
from top_down_planning.persistence.digests import compute_plan_digest
from top_down_planning.persistence.interface import RunStore
from top_down_planning.persistence.session_bindings import primary_provider_session_id
from core_tools.provider import Provider

_PLANNING_LIMIT_DEFAULTS = DEFAULT_CONFIG["limits"]["planning"]
_COMPLETION_SIGNALS = frozenset({PLANNER_CANDIDATE_READY_SIGNAL})


@dataclass(frozen=True)
class PlanningPhaseResult:
    ok: bool
    phase: str
    status: str
    outcome: str | None
    session_id: str | None
    agent_turns: int
    items_added: int
    reason: str | None = None


class PlanningPhaseOrchestrator:
    """Drive the primary planner session until candidate plan ready or a limit."""

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

    def run(self) -> PlanningPhaseResult:
        run = self._store.load_run(self._run_id)
        phase = str(run.get("phase") or PLANNING)
        if phase == WHOLE_PLAN_REVIEW:
            return self._result_from_run(run, ok=True)
        if phase != PLANNING:
            raise ProviderRunError(f"run is not in planning phase: {phase}")

        config = self._store.load_resolved_config(self._run_id)
        loop_limits = _planning_loop_limits(config)
        run = self._store.load_run(self._run_id)
        activity_context = resolve_activity_session_context(
            config,
            run,
            "planner",
            "initial_plan",
        )

        manifest = build_planner_context_manifest(
            self._run_id,
            run,
            config,
            self._store.load_plan_model(self._run_id),
            activity="initial_plan",
        )
        session_id = ensure_primary_session(
            self._store,
            self._run_id,
            self._provider,
            role="planner",
            phase=PLANNING,
            requested=activity_context,
            manifest=manifest,
            append_event=self._append_event,
            resume_request={"action": "continue", "phase": PLANNING},
        )
        role_context = activity_context

        run = self._store.load_run(self._run_id)
        phase = str(run.get("phase") or PLANNING)
        self._capability_token = issue_session_capability(
            self._store,
            self._run_id,
            role="planner",
            phase=phase,
            session_id=session_id,
            session_kind="primary",
        )
        bind_provider_capability(self._provider, self._capability_token, store=self._store, run_id=self._run_id)

        while True:
            self._capability_token = restore_primary_capability_after_focused_review(
                self._store,
                self._run_id,
                self._provider,
                review_type="focused_plan",
                role="planner",
                current_token=self._capability_token,
            )

            plan_item_ids_before = set(
                self._store.load_plan_model(self._run_id).items.keys()
            )
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
                        phase=PLANNING,
                        expected_next_action="continue planning turn",
                        append_event=self._append_event,
                        model=role_context.model,
                    ),
                )
            except SessionRecoveryPaused as exc:
                return self._result_from_run(
                    self._store.load_run(self._run_id),
                    ok=False,
                    reason=str(exc),
                )
            except SessionRecoveryExhausted as exc:
                return self._result_from_run(
                    self._store.load_run(self._run_id),
                    ok=False,
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
                review_type="focused_plan",
                role="planner",
                current_token=self._capability_token,
            )
            sync_planning_items_added(
                self._store,
                self._run_id,
                before_item_ids=plan_item_ids_before,
                persist_metrics=lambda run_id, metrics: _persist_planning_metrics(
                    self._store,
                    run_id,
                    metrics,
                ),
                append_event=self._append_event,
            )
            run = self._store.load_run(self._run_id)
            metrics = _planning_metrics(run)
            if turn_outcome.domain_budget_committed:
                metrics["agent_turns"] += 1
                run = _persist_planning_metrics(
                    self._store,
                    self._run_id,
                    metrics,
                )

            if turn_signal == PLANNER_CANDIDATE_READY_SIGNAL:
                if self._has_blocking_focused_plan_findings():
                    resume_primary_session_with_audit(
                        self._append_event,
                        self._provider,
                        role="planner",
                        phase=PLANNING,
                        session_id=session_id,
                        request={
                            "action": "continue",
                            "phase": PLANNING,
                            "blocked_reason": (
                                "candidate_plan_ready ignored: unresolved blocking "
                                "focused plan review findings remain in scope"
                            ),
                        },
                        model=role_context.model,
                    )
                    continue
                preflight = self._candidate_preflight()
                warnings = [
                    issue.message
                    for issue in preflight.issues
                    if issue.severity == "warning"
                ]
                if not preflight.ok:
                    resume_primary_session_with_audit(
                        self._append_event,
                        self._provider,
                        role="planner",
                        phase=PLANNING,
                        session_id=session_id,
                        request={
                            "action": "continue",
                            "phase": PLANNING,
                            "blocked_reason": (
                                "candidate_plan_ready ignored: plan failed "
                                "deterministic draft preflight"
                            ),
                            "validation_issues": [
                                issue.to_dict()
                                for issue in preflight.issues
                                if issue.severity == "error"
                            ],
                            "warnings": warnings,
                        },
                        model=role_context.model,
                    )
                    continue
                if metrics["items_added"] > loop_limits["max_items_added"]:
                    return self._terminate_for_limit(
                        session_id,
                        limit="max_items_added",
                        message=(
                            "planning exceeded max_items_added "
                            f"({loop_limits['max_items_added']})"
                        ),
                    )
                plan = self._store.load_plan_model(self._run_id)
                return self._complete_planning(
                    session_id,
                    metrics,
                    advisory_warnings=plan_advisory_warning_messages(plan),
                )

            if metrics["agent_turns"] >= loop_limits["max_agent_turns"]:
                return self._terminate_for_limit(
                    session_id,
                    limit="max_agent_turns",
                    message=(
                        f"planning exceeded max_agent_turns "
                        f"({loop_limits['max_agent_turns']})"
                    ),
                )

            if metrics["items_added"] > loop_limits["max_items_added"]:
                return self._terminate_for_limit(
                    session_id,
                    limit="max_items_added",
                    message=(
                        "planning exceeded max_items_added "
                        f"({loop_limits['max_items_added']})"
                    ),
                )

            run = self._store.load_run(self._run_id)
            phase = str(run.get("phase") or PLANNING)
            self._capability_token = rotate_session_capability(
                self._store,
                self._run_id,
                current_token=self._capability_token,
                role="planner",
                phase=phase,
                session_id=session_id,
                session_kind="primary",
            )
            bind_provider_capability(self._provider, self._capability_token, store=self._store, run_id=self._run_id)

            resume_primary_session_with_audit(
                self._append_event,
                self._provider,
                role="planner",
                phase=phase,
                session_id=session_id,
                request={"action": "continue", "phase": PLANNING},
                model=role_context.model,
            )

    def _has_blocking_focused_plan_findings(self) -> bool:
        plan = self._store.load_plan_model(self._run_id)
        item_ids = list(plan.items.keys())
        blocked = blocking_focused_findings_for_items(
            self._store.list_reviews(self._run_id),
            "focused_plan",
            item_ids,
        )
        return bool(blocked)

    def _candidate_preflight(self) -> ValidationResult:
        plan = self._store.load_plan_model(self._run_id)
        config = self._store.load_resolved_config(self._run_id)
        limits = planning_limits_from_config(config)
        return validate_plan(plan, limits=limits, mode="draft")

    def _complete_planning(
        self,
        session_id: str,
        metrics: dict[str, int],
        *,
        advisory_warnings: list[str] | None = None,
    ) -> PlanningPhaseResult:
        run = self._store.load_run(self._run_id)
        expected_revision = int(run["revision"])
        plan_revision = int(self._store.load_plan(self._run_id)["revision"])
        event_fields: dict[str, Any] = {
            "session_id": session_id,
            "agent_turns": metrics["agent_turns"],
            "items_added": metrics["items_added"],
            "plan_revision": plan_revision,
        }
        if advisory_warnings:
            event_fields["warnings"] = list(advisory_warnings)
        run_payload = dict(run)
        run_payload["revision"] = expected_revision + 1
        run_payload["phase"] = WHOLE_PLAN_REVIEW
        run_payload["pending_capability_revoke_phase"] = PLANNING
        self._store.commit(
            self._run_id,
            CommitSpec(
                run=run_payload,
                run_expected_revision=expected_revision,
                events=[
                    {
                        "type": "planning_candidate_ready",
                        "run_id": self._run_id,
                        **event_fields,
                    }
                ],
            ),
        )
        reconcile_pending_capability_revocation(self._store, self._run_id)
        run = self._store.load_run(self._run_id)
        return self._result_from_run(run, ok=True, session_id=session_id)

    def _terminate_for_limit(
        self,
        session_id: str,
        *,
        limit: str,
        message: str,
    ) -> PlanningPhaseResult:
        run = self._store.load_run(self._run_id)
        metrics = _planning_metrics(run)
        config = self._store.load_resolved_config(self._run_id)
        loop_limits = _planning_loop_limits(config)
        if limit == "max_agent_turns":
            consumed = int(metrics["agent_turns"])
            configured = int(loop_limits["max_agent_turns"])
        else:
            consumed = int(metrics["items_added"])
            configured = int(loop_limits["max_items_added"])
        pause_for_limit_exhausted(
            self._store,
            self._run_id,
            phase=PLANNING,
            message=message,
            limit=f"limits.planning.{limit}",
            consumed=consumed,
            configured=configured,
            role="planner",
            revoke_phase=PLANNING,
            session_id=session_id,
            additional_events=[
                {
                    "type": "planning_limit_exceeded",
                    "session_id": session_id,
                    "limit": limit,
                    "message": message,
                }
            ],
        )
        run = self._store.load_run(self._run_id)
        return self._result_from_run(
            run,
            ok=False,
            session_id=session_id,
            reason=message,
        )

    def _result_from_run(
        self,
        run: dict[str, Any],
        *,
        ok: bool,
        session_id: str | None = None,
        reason: str | None = None,
    ) -> PlanningPhaseResult:
        metrics = _planning_metrics(run)
        sessions = run.get("sessions") or {}
        return PlanningPhaseResult(
            ok=ok,
            phase=str(run.get("phase") or PLANNING),
            status=str(run.get("status") or "running"),
            outcome=run.get("outcome"),
            session_id=session_id or primary_provider_session_id(run, "planner"),
            agent_turns=metrics["agent_turns"],
            items_added=metrics["items_added"],
            reason=reason,
        )

    def _append_event(self, event_type: str, **fields: Any) -> None:
        payload = {"type": event_type, "run_id": self._run_id, **fields}
        self._store.append_event(self._run_id, payload)


def build_planner_context_manifest(
    run_id: str,
    run: dict[str, Any],
    config: dict[str, Any],
    plan: Any,
    *,
    activity: str = "initial_plan",
) -> dict[str, Any]:
    """Package planner prompt context and tool usage instructions."""

    planning = config.get("planning") or {}
    limits = planning_limits_from_config(config)
    loop_limits = _planning_loop_limits(config)
    digests = dict(run.get("digests") or {})

    return attach_activity_context_to_manifest(
        {
        "run_id": run_id,
        "phase": PLANNING,
        "stop_hint": planning.get("stop_hint", DEFAULT_CONFIG["planning"]["stop_hint"]),
        "planning_limits": {
            "max_depth": limits.max_depth,
            "max_expansion_per_item": limits.max_expansion_per_item,
        },
        "loop_limits": loop_limits,
        "digests": digests,
        "protocol_instructions": build_planner_protocol_instructions(),
        "tool_instructions": build_planner_tool_instructions(run_id),
        },
        config=config,
        run=run,
        role="planner",
        activity=activity,  # type: ignore[arg-type]
        output_goal=plan.output_goal,
    )


def _planning_loop_limits(config: dict[str, Any]) -> dict[str, int]:
    planning_limits = (config.get("limits") or {}).get("planning") or {}
    return {
        "max_items_added": int(
            planning_limits.get(
                "max_items_added",
                _PLANNING_LIMIT_DEFAULTS["max_items_added"],
            )
        ),
        "max_agent_turns": int(
            planning_limits.get(
                "max_agent_turns",
                _PLANNING_LIMIT_DEFAULTS["max_agent_turns"],
            )
        ),
    }


def _planning_metrics(run: dict[str, Any]) -> dict[str, int]:
    planning = run.get("planning") or {}
    return {
        "agent_turns": int(planning.get("agent_turns") or 0),
        "items_added": int(planning.get("items_added") or 0),
    }
def _persist_planning_metrics(
    store: RunStore,
    run_id: str,
    metrics: dict[str, int],
) -> dict[str, Any]:
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["planning"] = {
        "agent_turns": metrics["agent_turns"],
        "items_added": metrics["items_added"],
    }
    plan = store.load_plan(run_id)
    run.setdefault("digests", {})
    run["digests"]["plan"] = compute_plan_digest(plan)
    store.save_run(run_id, run, expected_revision)
    return store.load_run(run_id)
