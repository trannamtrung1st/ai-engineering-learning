"""Planning-phase orchestration (proposal §3, §4.1, §13)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from top_down_planning.agent_tool.config import planning_limits_from_config
from top_down_planning.agent_tool.plan_service import PlanAgentService
from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.orchestrator.phases import PLANNING, WHOLE_PLAN_REVIEW
from top_down_planning.persistence.digests import compute_plan_digest
from top_down_planning.persistence.interface import RunStore
from top_down_planning.provider.interface import Provider

_PLANNING_LIMIT_DEFAULTS = DEFAULT_CONFIG["limits"]["planning"]
_CANDIDATE_READY_SIGNAL = "candidate_plan_ready"


@dataclass(frozen=True)
class PlanningPhaseResult:
    ok: bool
    phase: str
    status: str
    outcome: str | None
    session_id: str | None
    agent_turns: int
    expansion_iterations: int
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
        self._plan_service = PlanAgentService(store, run_id)

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
            )
            session_id = self._provider.start_primary_session("planner", manifest)
            run = _persist_session_id(self._store, self._run_id, session_id)
            self._append_event(
                "planner_session_started",
                session_id=session_id,
            )
        else:
            self._provider.resume_primary_session(
                session_id,
                {"action": "continue", "phase": PLANNING},
            )

        while True:
            turn_signal = self._consume_provider_turn(session_id)
            run = self._store.load_run(self._run_id)
            metrics = _planning_metrics(run)
            metrics["agent_turns"] += 1
            run = _persist_planning_metrics(
                self._store,
                self._run_id,
                metrics,
            )

            if turn_signal == _CANDIDATE_READY_SIGNAL:
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

            if metrics["expansion_iterations"] >= loop_limits["max_expansion_iterations"]:
                return self._terminate_for_limit(
                    session_id,
                    limit="max_expansion_iterations",
                    message=(
                        "planning exceeded max_expansion_iterations "
                        f"({loop_limits['max_expansion_iterations']})"
                    ),
                )

            self._provider.resume_primary_session(
                session_id,
                {"action": "continue", "phase": PLANNING},
            )

    def _consume_provider_turn(self, session_id: str) -> str | None:
        signal: str | None = None
        for event in self._provider.stream_events(session_id):
            event_type = str(event.get("type") or "")
            if event_type == "error":
                text = event.get("text") or "provider error"
                raise ProviderRunError(str(text))
            if event_type == "tool_call":
                self._handle_tool_call(event)
                continue
            if event_type == "done":
                if event.get("is_error"):
                    text = event.get("text") or "provider turn failed"
                    raise ProviderRunError(str(text))
                signal = event.get("signal")
                if signal is not None:
                    signal = str(signal)
        return signal

    def _handle_tool_call(self, event: dict[str, Any]) -> None:
        tool = str(event.get("tool") or "")
        if tool != "plan_apply":
            return

        request = event.get("request")
        if not isinstance(request, dict):
            raise ProviderRunError("plan_apply tool_call requires a request object")

        role = event.get("role")
        if role is None or str(role).strip() != "planner":
            raise ProviderRunError("plan_apply tool_call requires role=planner")

        operations = request.get("operations") or []
        before_revision = self._store.load_plan(self._run_id)["revision"]
        self._plan_service.apply(request, role=role)
        after_revision = self._store.load_plan(self._run_id)["revision"]
        if after_revision != before_revision:
            expansion_added = _count_add_item_operations(operations)
            if expansion_added:
                run = self._store.load_run(self._run_id)
                metrics = _planning_metrics(run)
                metrics["expansion_iterations"] += expansion_added
                _persist_planning_metrics(
                    self._store,
                    self._run_id,
                    metrics,
                )
                self._append_event(
                    "planning_expansion_recorded",
                    expansion_iterations=metrics["expansion_iterations"],
                    added_items=expansion_added,
                )

    def _complete_planning(
        self,
        session_id: str,
        metrics: dict[str, int],
    ) -> PlanningPhaseResult:
        run = self._store.load_run(self._run_id)
        expected_revision = int(run["revision"])
        run = dict(run)
        run["revision"] = expected_revision + 1
        run["phase"] = WHOLE_PLAN_REVIEW
        self._store.save_run(self._run_id, run, expected_revision)
        self._append_event(
            "planning_candidate_ready",
            session_id=session_id,
            agent_turns=metrics["agent_turns"],
            expansion_iterations=metrics["expansion_iterations"],
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
            expansion_iterations=metrics["expansion_iterations"],
            reason=reason,
        )

    def _append_event(self, event_type: str, **fields: Any) -> None:
        payload = {"type": event_type, "run_id": self._run_id, **fields}
        self._store.append_event(self._run_id, payload)


def build_planner_context_manifest(
    run_id: str,
    run: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Package planner prompt context and tool usage instructions."""

    run_section = config.get("run") or {}
    planning = config.get("planning") or {}
    limits = planning_limits_from_config(config)
    loop_limits = _planning_loop_limits(config)
    digests = dict(run.get("digests") or {})

    return {
        "run_id": run_id,
        "phase": PLANNING,
        "input_refs": list(run_section.get("input_refs") or []),
        "output_goal": str(run_section.get("output_goal") or ""),
        "stop_hint": planning.get("stop_hint", DEFAULT_CONFIG["planning"]["stop_hint"]),
        "planning_limits": {
            "max_depth": limits.max_depth,
            "max_expansion_per_item": limits.max_expansion_per_item,
        },
        "loop_limits": loop_limits,
        "digests": digests,
        "tool_instructions": {
            "role": "Only the planner role may mutate the plan during planning.",
            "snapshot": f"tdp agent plan snapshot --run {run_id} --view tree",
            "apply": (
                f"tdp agent plan apply --run {run_id} --role planner --request <file>"
            ),
            "check": f"tdp agent plan check --run {run_id}",
            "completion_signal": _CANDIDATE_READY_SIGNAL,
        },
    }


def _planning_loop_limits(config: dict[str, Any]) -> dict[str, int]:
    planning_limits = (config.get("limits") or {}).get("planning") or {}
    return {
        "max_expansion_iterations": int(
            planning_limits.get(
                "max_expansion_iterations",
                _PLANNING_LIMIT_DEFAULTS["max_expansion_iterations"],
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
        "expansion_iterations": int(planning.get("expansion_iterations") or 0),
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
        "expansion_iterations": metrics["expansion_iterations"],
    }
    plan = store.load_plan(run_id)
    run.setdefault("digests", {})
    run["digests"]["plan"] = compute_plan_digest(plan)
    store.save_run(run_id, run, expected_revision)
    return store.load_run(run_id)


def _count_add_item_operations(operations: list[Any]) -> int:
    count = 0
    for operation in operations:
        if not isinstance(operation, dict):
            continue
        if str(operation.get("op") or "") == "add_item":
            count += 1
    return count
