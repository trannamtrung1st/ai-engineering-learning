"""Optional focused plan/output review loops (proposal §4.3, §5.1, §11)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from top_down_planning.agent_tool.errors import AgentToolError
from top_down_planning.agent_tool.plan_service import PlanAgentService
from top_down_planning.agent_tool.production_service import ProductionAgentService
from top_down_planning.agent_tool.review_service import ReviewAgentService
from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.domain.production import build_production_review_snapshot
from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.orchestrator.phases import PLANNING, PRODUCTION
from top_down_planning.persistence.digests import compute_output_digest
from top_down_planning.persistence.interface import RunStore
from core_tools.provider import Provider

_FOCUSED_PLAN_LIMIT_DEFAULTS = DEFAULT_CONFIG["limits"]["focused_plan_review"]
_FOCUSED_OUTPUT_LIMIT_DEFAULTS = DEFAULT_CONFIG["limits"]["focused_output_review"]

_PRODUCTION_TOOL_HANDLERS: dict[str, str] = {
    "production_apply": "apply",
    "production_request_amendment": "request_amendment",
    "production_submit_completion": "submit_completion",
    "production_report_blocked": "report_blocked",
}


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
        self._plan_service = PlanAgentService(store, run_id)
        self._production_service = ProductionAgentService(store, run_id)
        self._review_service = ReviewAgentService(store, run_id)

    def run(self, loop_id: str) -> FocusedReviewResult:
        loop = ReviewLoop.from_dict(self._store.load_review(self._run_id, loop_id))
        if loop.type not in {"focused_plan", "focused_output"}:
            raise ProviderRunError(f"review loop {loop_id} is not a focused review loop")

        config = self._store.load_resolved_config(self._run_id)
        max_revision_cycles = _focused_revision_limit(config, loop.type)
        loop = self._normalize_loop_for_resume(loop)

        while True:
            if loop.status == "pending":
                session_id = loop.reviewer_session_id
                if session_id is None:
                    session_id = self._start_reviewer_session(loop)
                    loop = self._reload_loop(loop.id)
                decision = self._consume_reviewer_turn(session_id, loop.id)
                loop = self._reload_loop(loop.id)
                if decision is None:
                    raise ProviderRunError("reviewer turn completed without a decision")
            else:
                decision = loop.status

            if decision == "approved":
                return self._result_from_loop(loop, ok=True)

            if decision == "blocked":
                return self._result_from_loop(
                    loop,
                    ok=False,
                    reason="focused reviewer blocked the scoped review",
                )

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

            if revision_cycles > max_revision_cycles:
                loop = self._persist_loop(
                    ReviewLoop(
                        id=loop.id,
                        type=loop.type,
                        reviewer_session_id=loop.reviewer_session_id,
                        target_revision=loop.target_revision,
                        scope=loop.scope,
                        status="blocked",
                        findings=loop.findings,
                        revision_cycles=revision_cycles,
                    )
                )
                self._append_event(
                    "focused_review_failed",
                    loop_id=loop.id,
                    review_type=loop.type,
                    reason=(
                        "focused review exceeded max_revision_cycles_per_loop "
                        f"({max_revision_cycles})"
                    ),
                )
                return self._result_from_loop(
                    loop,
                    ok=False,
                    reason=(
                        "focused review exceeded max_revision_cycles_per_loop "
                        f"({max_revision_cycles})"
                    ),
                )

            self._resume_primary_with_findings(loop)
            loop = self._prepare_recheck(loop)

    def _normalize_loop_for_resume(self, loop: ReviewLoop) -> ReviewLoop:
        if loop.status != "changes_requested":
            return loop

        current_revision = _current_target_revision(self._store, self._run_id, loop.type)
        if current_revision <= loop.target_revision:
            return loop

        return self._prepare_recheck(loop)

    def _start_reviewer_session(self, loop: ReviewLoop) -> str:
        package = build_focused_review_package(
            self._run_id,
            self._store.load_run(self._run_id),
            self._store.load_resolved_config(self._run_id),
            loop,
            production=(
                self._store.load_production(self._run_id)
                if loop.type == "focused_output"
                else None
            ),
        )
        session_id = self._provider.start_reviewer_session(package)
        updated = ReviewLoop(
            id=loop.id,
            type=loop.type,
            reviewer_session_id=session_id,
            target_revision=loop.target_revision,
            scope=loop.scope,
            status=loop.status,
            findings=loop.findings,
            revision_cycles=loop.revision_cycles,
        )
        self._persist_loop(updated)
        self._append_event(
            "focused_review_started",
            loop_id=loop.id,
            review_type=loop.type,
            session_id=session_id,
            scope=loop.scope,
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

        role = event.get("role")
        if role is None or str(role).strip() != "reviewer":
            raise ProviderRunError("review_respond tool_call requires role=reviewer")

        request = dict(request)
        request.setdefault("loop_id", loop_id)
        self._review_service.respond(request, role=role)

    def _resume_primary_with_findings(self, loop: ReviewLoop) -> None:
        run = self._store.load_run(self._run_id)
        if loop.type == "focused_plan":
            session_id = _primary_planner_session_id(run)
            phase = PLANNING
            role = "planner"
        else:
            session_id = _primary_producer_session_id(run)
            phase = PRODUCTION
            role = "producer"

        if session_id is None:
            raise ProviderRunError(f"primary {role} session is missing for focused revision")

        self._provider.resume_primary_session(
            session_id,
            {
                "action": "address_review_findings",
                "phase": phase,
                "loop_id": loop.id,
                "review_type": loop.type,
                "target_revision": loop.target_revision,
                "scope": dict(loop.scope),
                "findings": [finding.to_dict() for finding in loop.findings],
            },
        )
        self._consume_primary_turn(session_id, loop.type)
        if loop.type == "focused_output":
            self._sync_output_digest()

    def _consume_primary_turn(self, session_id: str, review_type: str) -> None:
        for event in self._provider.stream_events(session_id):
            event_type = str(event.get("type") or "")
            if event_type == "error":
                text = event.get("text") or "provider error"
                raise ProviderRunError(str(text))
            if event_type == "tool_call":
                self._handle_primary_tool_call(event, review_type)
                continue
            if event_type == "done":
                if event.get("is_error"):
                    text = event.get("text") or "primary revision turn failed"
                    raise ProviderRunError(str(text))
                return

    def _handle_primary_tool_call(self, event: dict[str, Any], review_type: str) -> None:
        tool = str(event.get("tool") or "")
        if review_type == "focused_plan":
            if tool == "plan_apply":
                request = event.get("request")
                if not isinstance(request, dict):
                    raise ProviderRunError("plan_apply tool_call requires a request object")
                role = event.get("role")
                if role is None or str(role).strip() != "planner":
                    raise ProviderRunError("plan_apply tool_call requires role=planner")
                self._plan_service.apply(request, role=role)
                return
            if tool == "review_request":
                raise ProviderRunError(
                    "review_request is not allowed while addressing focused review findings; "
                    "complete the current focused review revision first"
                )
            return

        if tool == "plan_apply":
            raise ProviderRunError(
                "plan mutations are not allowed during focused output review; "
                "use `tdp agent production request-amendment` when a material plan "
                "defect is found"
            )

        handler_name = _PRODUCTION_TOOL_HANDLERS.get(tool)
        if handler_name is not None:
            request = event.get("request")
            if not isinstance(request, dict):
                raise ProviderRunError(f"{tool} tool_call requires a request object")
            role = event.get("role")
            if role is None or str(role).strip() != "producer":
                raise ProviderRunError(f"{tool} tool_call requires role=producer")
            handler = getattr(self._production_service, handler_name)
            try:
                handler(request, role=str(role).strip())
            except AgentToolError as exc:
                raise ProviderRunError(str(exc)) from exc
            return

        if tool == "review_request":
            raise ProviderRunError(
                "review_request is not allowed while addressing focused review findings; "
                "complete the current focused review revision first"
            )

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
        session_id = loop.reviewer_session_id
        if session_id is None:
            raise ProviderRunError("reviewer session is missing for recheck")

        updated = ReviewLoop(
            id=loop.id,
            type=loop.type,
            reviewer_session_id=session_id,
            target_revision=current_revision,
            scope=loop.scope,
            status="pending",
            findings=loop.findings,
            revision_cycles=loop.revision_cycles,
        )
        self._persist_loop(updated)
        phase = PLANNING if loop.type == "focused_plan" else PRODUCTION
        self._provider.send(
            session_id,
            {
                "action": "recheck_revision",
                "phase": phase,
                "loop_id": loop.id,
                "review_type": loop.type,
                "target_revision": current_revision,
                "scope": dict(loop.scope),
            },
        )
        return updated

    def _persist_loop(self, loop: ReviewLoop) -> ReviewLoop:
        self._store.save_review(self._run_id, loop.to_dict())
        return loop

    def _reload_loop(self, loop_id: str) -> ReviewLoop:
        return ReviewLoop.from_dict(self._store.load_review(self._run_id, loop_id))

    def _result_from_loop(
        self,
        loop: ReviewLoop,
        *,
        ok: bool,
        reason: str | None = None,
    ) -> FocusedReviewResult:
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
            reviewer_session_id=loop.reviewer_session_id,
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
    production: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Package a bounded focused review for a fresh reviewer session."""

    run_section = config.get("run") or {}
    digests = dict(run.get("digests") or {})
    phase = PLANNING if loop.type == "focused_plan" else PRODUCTION
    revision_label = "plan" if loop.type == "focused_plan" else "output"

    package: dict[str, Any] = {
        "run_id": run_id,
        "phase": phase,
        "type": loop.type,
        "loop_id": loop.id,
        "purpose": f"Optional focused {revision_label} review within declared scope",
        "scope": dict(loop.scope),
        "target_revision": loop.target_revision,
        "input_refs": list(run_section.get("input_refs") or []),
        "output_goal": str(run_section.get("output_goal") or ""),
        "boundaries": run_section.get("boundaries"),
        "acceptance": run_section.get("acceptance"),
        "digests": digests,
        "tool_instructions": {
            "role": "Only the reviewer role may submit review responses.",
            "respond": (
                f"tdp agent review respond --run {run_id} --role reviewer "
                "--request <file>"
            ),
            "scope_rule": (
                "Findings must reference only item ids declared in scope.item_ids."
            ),
        },
    }
    if production is not None:
        package["output_revision"] = int(production["output_revision"])
        package["production"] = build_production_review_snapshot(production)
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


def _primary_planner_session_id(run: dict[str, Any]) -> str | None:
    sessions = run.get("sessions") or {}
    session_id = sessions.get("primary_planner_session_id")
    if session_id is None:
        return None
    return str(session_id)


def _primary_producer_session_id(run: dict[str, Any]) -> str | None:
    sessions = run.get("sessions") or {}
    session_id = sessions.get("primary_producer_session_id")
    if session_id is None:
        return None
    return str(session_id)
