"""Planning-phase orchestration (proposal §3, §4.1, §13)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from top_down_planning.agent_tool.config import planning_limits_from_config
from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.domain.reviews import blocking_focused_findings_for_items
from top_down_planning.orchestrator.capability import (
    bind_provider_capability,
    issue_session_capability,
    revoke_capabilities_for_phase,
    rotate_session_capability,
)
from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.orchestrator.agent_context import (
    attach_role_context_to_manifest,
    resolve_role_session_context,
)
from top_down_planning.orchestrator.phases import PLANNING, WHOLE_PLAN_REVIEW
from top_down_planning.orchestrator.provider_turns import (
    consume_provider_turn,
    run_pending_focused_review,
    sync_planning_items_added,
)
from top_down_planning.persistence.digests import compute_plan_digest
from top_down_planning.persistence.interface import RunStore
from core_tools.provider import Provider

_PLANNING_LIMIT_DEFAULTS = DEFAULT_CONFIG["limits"]["planning"]
_CANDIDATE_READY_SIGNAL = "candidate_plan_ready"
_COMPLETION_SIGNALS = frozenset({_CANDIDATE_READY_SIGNAL})


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

        session_id = _primary_planner_session_id(run)
        if session_id is None:
            manifest = build_planner_context_manifest(
                self._run_id,
                run,
                config,
                self._store.load_plan_model(self._run_id),
            )
            role_context = resolve_role_session_context(config, run, "planner")
            session_id = self._provider.start_primary_session(
                "planner",
                manifest,
                model=role_context.model,
            )
            run = _persist_session_id(self._store, self._run_id, session_id)
            self._append_event(
                "planner_session_started",
                session_id=session_id,
                role="planner",
                phase=PLANNING,
            )
        else:
            self._provider.resume_primary_session(
                session_id,
                {"action": "continue", "phase": PLANNING},
            )

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
        bind_provider_capability(self._provider, self._capability_token)

        while True:
            run_pending_focused_review(
                self._store,
                self._run_id,
                self._provider,
                review_type="focused_plan",
            )

            plan_item_ids_before = set(
                self._store.load_plan_model(self._run_id).items.keys()
            )
            turn_signal = consume_provider_turn(
                self._provider,
                session_id,
                allowed_signals=_COMPLETION_SIGNALS,
            )
            run_pending_focused_review(
                self._store,
                self._run_id,
                self._provider,
                review_type="focused_plan",
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
            metrics["agent_turns"] += 1
            run = _persist_planning_metrics(
                self._store,
                self._run_id,
                metrics,
            )

            if turn_signal == _CANDIDATE_READY_SIGNAL:
                if self._has_blocking_focused_plan_findings():
                    self._provider.resume_primary_session(
                        session_id,
                        {
                            "action": "continue",
                            "phase": PLANNING,
                            "blocked_reason": (
                                "candidate_plan_ready ignored: unresolved blocking "
                                "focused plan review findings remain in scope"
                            ),
                        },
                    )
                    continue
                return self._complete_planning(session_id, metrics)

            if metrics["agent_turns"] >= loop_limits["max_agent_turns"]:
                return self._terminate_for_limit(
                    session_id,
                    limit="max_agent_turns",
                    message=(
                        f"planning exceeded max_agent_turns "
                        f"({loop_limits['max_agent_turns']})"
                    ),
                )

            if metrics["items_added"] >= loop_limits["max_items_added"]:
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
            bind_provider_capability(self._provider, self._capability_token)

            self._provider.resume_primary_session(
                session_id,
                {"action": "continue", "phase": PLANNING},
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

    def _complete_planning(
        self,
        session_id: str,
        metrics: dict[str, int],
    ) -> PlanningPhaseResult:
        run = self._store.load_run(self._run_id)
        expected_revision = int(run["revision"])
        revoke_capabilities_for_phase(self._store, self._run_id, PLANNING)
        run = dict(run)
        run["revision"] = expected_revision + 1
        run["phase"] = WHOLE_PLAN_REVIEW
        self._store.save_run(self._run_id, run, expected_revision)
        self._append_event(
            "planning_candidate_ready",
            session_id=session_id,
            agent_turns=metrics["agent_turns"],
            items_added=metrics["items_added"],
            plan_revision=self._store.load_plan(self._run_id)["revision"],
        )
        run = self._store.load_run(self._run_id)
        return self._result_from_run(run, ok=True, session_id=session_id)

    def _terminate_for_limit(
        self,
        session_id: str,
        *,
        limit: str,
        message: str,
    ) -> PlanningPhaseResult:
        revoke_capabilities_for_phase(self._store, self._run_id, PLANNING)
        run = self._store.load_run(self._run_id)
        expected_revision = int(run["revision"])
        run = dict(run)
        run["revision"] = expected_revision + 1
        run["status"] = "completed"
        run["outcome"] = "blocked"
        self._store.save_run(self._run_id, run, expected_revision)
        self._append_event(
            "planning_limit_exceeded",
            session_id=session_id,
            limit=limit,
            message=message,
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
            session_id=session_id or sessions.get("primary_planner_session_id"),
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
) -> dict[str, Any]:
    """Package planner prompt context and tool usage instructions."""

    run_section = config.get("run") or {}
    planning = config.get("planning") or {}
    limits = planning_limits_from_config(config)
    loop_limits = _planning_loop_limits(config)
    digests = dict(run.get("digests") or {})

    return attach_role_context_to_manifest(
        {
        "run_id": run_id,
        "phase": PLANNING,
        "input_refs": list(run_section.get("input_refs") or []),
        "output_goal": plan.output_goal,
        "stop_hint": planning.get("stop_hint", DEFAULT_CONFIG["planning"]["stop_hint"]),
        "planning_limits": {
            "max_depth": limits.max_depth,
            "max_expansion_per_item": limits.max_expansion_per_item,
        },
        "loop_limits": loop_limits,
        "digests": digests,
        "tool_instructions": {
            "authorization": (
                "Mutating commands require the session capability token exported "
                "as TDP_CAPABILITY_TOKEN."
            ),
            "snapshot": f"tdp agent plan snapshot --run {run_id} --view tree",
            "apply": f"tdp agent plan apply --run {run_id} --request <file>",
            "check": f"tdp agent plan check --run {run_id}",
            "request_review": (
                f"tdp agent review request --run {run_id} --request <file>"
            ),
            "completion_signal": _CANDIDATE_READY_SIGNAL,
        },
        },
        config=config,
        run=run,
        role="planner",
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


def _primary_planner_session_id(run: dict[str, Any]) -> str | None:
    sessions = run.get("sessions") or {}
    session_id = sessions.get("primary_planner_session_id")
    if session_id is None:
        return None
    return str(session_id)


def _persist_session_id(
    store: RunStore,
    run_id: str,
    session_id: str,
) -> dict[str, Any]:
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    sessions = dict(run.get("sessions") or {})
    sessions["primary_planner_session_id"] = session_id
    run["sessions"] = sessions
    store.save_run(run_id, run, expected_revision)
    return store.load_run(run_id)


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
