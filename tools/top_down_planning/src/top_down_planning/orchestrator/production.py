"""Production-phase orchestration (proposal §4.2, §10, §13)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from top_down_planning.agent_tool.errors import AgentToolError
from top_down_planning.agent_tool.production_service import ProductionAgentService
from top_down_planning.agent_tool.review_service import ReviewAgentService
from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.domain.production import all_applicable_items_processed, has_pending_amendment, latest_reconciliation_report
from top_down_planning.domain.readiness import detect_deadlock
from top_down_planning.domain.reviews import blocking_focused_findings_for_items, find_whole_plan_approval
from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.orchestrator.focused_review import FocusedReviewOrchestrator
from top_down_planning.orchestrator.phases import (
    PLAN_VALIDATED,
    PRODUCTION,
    WHOLE_OUTPUT_REVIEW,
)
from top_down_planning.persistence.digests import compute_output_digest
from top_down_planning.persistence.interface import RunStore
from core_tools.provider import Provider

_PRODUCTION_LIMIT_DEFAULTS = DEFAULT_CONFIG["limits"]["production"]
_BATCH_COMPLETE_SIGNAL = "batch_complete"

_PRODUCTION_TOOL_HANDLERS: dict[str, str] = {
    "production_apply": "apply",
    "production_request_amendment": "request_amendment",
    "production_submit_completion": "submit_completion",
    "production_report_blocked": "report_blocked",
}


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
        self._review_service = ReviewAgentService(store, run_id)
        self._pending_focused_loop_id: str | None = None

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

        session_id = _primary_producer_session_id(run)
        if session_id is None:
            manifest = build_producer_context_manifest(
                self._run_id,
                self._store.load_run(self._run_id),
                config,
                plan_revision=int(self._store.load_plan(self._run_id)["revision"]),
                production=self._store.load_production(self._run_id),
            )
            session_id = self._provider.start_primary_session("producer", manifest)
            run = _persist_session_id(self._store, self._run_id, session_id)
            self._append_event(
                "producer_session_started",
                session_id=session_id,
            )
        else:
            self._provider.resume_primary_session(
                session_id,
                {"action": "continue", "phase": PRODUCTION},
            )

        batch_agent_turns = _load_batch_agent_turns(self._store, self._run_id)
        while True:
            if self._has_pending_amendment():
                from top_down_planning.orchestrator.plan_amendment import (
                    PlanAmendmentOrchestrator,
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
                return self._terminate(
                    "blocked",
                    (
                        "production exceeded max_batches "
                        f"({loop_limits['max_batches']})"
                    ),
                    session_id=session_id,
                )

            turn_signal, agent_turns = self._consume_provider_turn(session_id)
            if self._pending_focused_loop_id is not None:
                self._run_pending_focused_review()
            batch_agent_turns += agent_turns
            _persist_batch_agent_turns(self._store, self._run_id, batch_agent_turns)

            if turn_signal == _BATCH_COMPLETE_SIGNAL:
                batch_agent_turns = 0
                _persist_batch_agent_turns(self._store, self._run_id, 0)
                continue

            if batch_agent_turns > loop_limits["max_agent_turns_per_batch"]:
                return self._terminate(
                    "blocked",
                    (
                        "production exceeded max_agent_turns_per_batch "
                        f"({loop_limits['max_agent_turns_per_batch']})"
                    ),
                    session_id=session_id,
                )

            self._provider.resume_primary_session(
                session_id,
                self._producer_resume_request(),
            )

    def _consume_provider_turn(self, session_id: str) -> tuple[str | None, int]:
        signal: str | None = None
        agent_turns = 0
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
                agent_turns += 1
        return signal, agent_turns

    def _handle_tool_call(self, event: dict[str, Any]) -> None:
        tool = str(event.get("tool") or "")
        if tool == "review_request":
            self._handle_review_request(event)
            return
        if tool == "plan_apply":
            raise ProviderRunError(
                "plan mutations are not allowed during production; "
                "use `tdp agent production request-amendment` when a material plan "
                "defect is found"
            )

        handler_name = _PRODUCTION_TOOL_HANDLERS.get(tool)
        if handler_name is None:
            return

        request = event.get("request")
        if not isinstance(request, dict):
            raise ProviderRunError(f"{tool} tool_call requires a request object")

        if tool == "production_apply":
            plan_items = request.get("plan_items") or []
            if isinstance(plan_items, list):
                self._assert_no_blocking_focused_output_findings(
                    [str(item_id) for item_id in plan_items]
                )

        if tool == "production_submit_completion":
            self._assert_no_blocking_focused_output_findings_for_plan()

        role = event.get("role")
        if role is None or str(role).strip() != "producer":
            raise ProviderRunError(f"{tool} tool_call requires role=producer")

        handler = getattr(self._production_service, handler_name)
        try:
            handler(request, role=str(role).strip())
        except AgentToolError as exc:
            raise ProviderRunError(str(exc)) from exc

    def _handle_review_request(self, event: dict[str, Any]) -> None:
        request = event.get("request")
        if not isinstance(request, dict):
            raise ProviderRunError("review_request tool_call requires a request object")

        role = event.get("role")
        if role is None or str(role).strip() != "producer":
            raise ProviderRunError("review_request tool_call requires role=producer")

        try:
            created = self._review_service.request(request, role=str(role).strip())
        except AgentToolError as exc:
            raise ProviderRunError(str(exc)) from exc

        self._pending_focused_loop_id = str(created["loop_id"])

    def _run_pending_focused_review(self) -> None:
        loop_id = self._pending_focused_loop_id
        if loop_id is None:
            return
        self._pending_focused_loop_id = None
        result = FocusedReviewOrchestrator(
            self._store,
            self._run_id,
            self._provider,
        ).run(loop_id)
        if not result.ok:
            raise ProviderRunError(
                result.reason or "focused output review did not complete successfully"
            )

    def _assert_no_blocking_focused_output_findings(self, item_ids: list[str]) -> None:
        blocked = blocking_focused_findings_for_items(
            self._store.list_reviews(self._run_id),
            "focused_output",
            item_ids,
        )
        if blocked:
            joined = ", ".join(blocked)
            raise ProviderRunError(
                f"production blocked by unresolved focused output findings: {joined}"
            )

    def _assert_no_blocking_focused_output_findings_for_plan(self) -> None:
        plan = self._store.load_plan_model(self._run_id)
        self._assert_no_blocking_focused_output_findings(list(plan.items.keys()))

    def _has_completion_claim(self) -> bool:
        production = self._store.load_production(self._run_id)
        claim = production.get("completion_claim")
        return isinstance(claim, dict)

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
        expected_revision = int(run["revision"])
        run = dict(run)
        run["revision"] = expected_revision + 1
        run["phase"] = WHOLE_OUTPUT_REVIEW
        digests = dict(run.get("digests") or {})
        digests["output"] = compute_output_digest(production)
        run["digests"] = digests
        self._store.save_run(self._run_id, run, expected_revision)
        self._append_event(
            "production_completed",
            session_id=session_id,
            batch_count=self._batch_count(),
        )
        run = self._store.load_run(self._run_id)
        return self._result_from_run(run, ok=True, session_id=session_id)

    def _terminate(
        self,
        outcome: str,
        message: str,
        *,
        session_id: str | None,
    ) -> ProductionPhaseResult:
        run = self._store.load_run(self._run_id)
        expected_revision = int(run["revision"])
        run = dict(run)
        run["revision"] = expected_revision + 1
        run["status"] = "completed"
        run["outcome"] = outcome
        self._store.save_run(self._run_id, run, expected_revision)
        self._append_event(
            "production_failed",
            outcome=outcome,
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
            session_id=session_id or sessions.get("primary_producer_session_id"),
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
    *,
    plan_revision: int,
    production: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Package producer prompt context and tool usage instructions."""

    run_section = config.get("run") or {}
    limits = _production_loop_limits(config)
    digests = dict(run.get("digests") or {})

    manifest: dict[str, Any] = {
        "run_id": run_id,
        "phase": PRODUCTION,
        "input_refs": list(run_section.get("input_refs") or []),
        "output_goal": str(run_section.get("output_goal") or ""),
        "boundaries": run_section.get("boundaries"),
        "acceptance": run_section.get("acceptance"),
        "approved_plan_revision": plan_revision,
        "loop_limits": limits,
        "digests": digests,
        "tool_instructions": {
            "role": "Only the producer role may record production batches.",
            "snapshot": f"tdp agent production snapshot --run {run_id} --view ready",
            "apply": (
                f"tdp agent production apply --run {run_id} --role producer "
                "--request <file>"
            ),
            "check": f"tdp agent production check --run {run_id}",
            "request_amendment": (
                f"tdp agent production request-amendment --run {run_id} --role producer "
                "--request <file>"
            ),
            "submit_completion": (
                f"tdp agent production submit-completion --run {run_id} --role producer "
                "--request <file>"
            ),
            "report_blocked": (
                f"tdp agent production report-blocked --run {run_id} --role producer "
                "--request <file>"
            ),
            "request_review": (
                f"tdp agent review request --run {run_id} --role producer --request <file>"
            ),
            "batch_complete_signal": _BATCH_COMPLETE_SIGNAL,
        },
    }
    if production is not None:
        reconciliation = latest_reconciliation_report(production)
        if reconciliation is not None:
            manifest["reconciliation"] = reconciliation
    return manifest


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


def _primary_producer_session_id(run: dict[str, Any]) -> str | None:
    sessions = run.get("sessions") or {}
    session_id = sessions.get("primary_producer_session_id")
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
    sessions["primary_producer_session_id"] = session_id
    run["sessions"] = sessions
    store.save_run(run_id, run, expected_revision)
    return store.load_run(run_id)


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
