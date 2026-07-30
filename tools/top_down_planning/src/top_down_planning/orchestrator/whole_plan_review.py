"""Whole-plan review orchestration (proposal §4.3, §5.2, §11, §12.1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from top_down_planning.agent_tool.config import planning_limits_from_config
from top_down_planning.agent_tool.views import build_plan_review_snapshot
from top_down_planning.agent_tool.plan_service import PlanAgentService
from top_down_planning.agent_tool.review_service import ReviewAgentService
from top_down_planning.config import compute_input_digest, compute_output_goal_digest
from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.domain.validators import (
    build_plan_approval_validation_context,
    validate_plan,
)
from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.orchestrator.phases import PLAN_VALIDATED, WHOLE_PLAN_REVIEW
from top_down_planning.workspace import run_workspace
from top_down_planning.persistence.digests import compute_config_digest, compute_plan_digest
from top_down_planning.persistence.interface import RunStore
from core_tools.provider import Provider

_WHOLE_PLAN_LIMIT_DEFAULTS = DEFAULT_CONFIG["limits"]["whole_plan_review"]


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
        self._plan_service = PlanAgentService(store, run_id)
        self._review_service = ReviewAgentService(store, run_id)

    def run(self) -> WholePlanReviewResult:
        run = self._store.load_run(self._run_id)
        phase = str(run.get("phase") or "")
        if phase == PLAN_VALIDATED:
            return self._result_from_run(run, ok=True)
        if phase != WHOLE_PLAN_REVIEW:
            raise ProviderRunError(f"run is not in whole-plan review phase: {phase}")

        config = self._store.load_resolved_config(self._run_id)
        max_revision_cycles = _whole_plan_revision_limit(config)
        loop = self._normalize_loop_for_resume(self._get_or_create_active_loop())

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
                return self._complete_with_approval(loop)

            if decision == "blocked":
                return self._terminate("blocked", "whole-plan reviewer blocked the run")

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

            if revision_cycles >= max_revision_cycles:
                return self._terminate(
                    "rejected",
                    (
                        "whole-plan review exceeded max_revision_cycles "
                        f"({max_revision_cycles})"
                    ),
                )

            self._resume_planner_with_findings(loop)
            loop = self._prepare_recheck(loop)

    def _complete_with_approval(self, loop: ReviewLoop) -> WholePlanReviewResult:
        plan = self._store.load_plan_model(self._run_id)
        run = self._store.load_run(self._run_id)
        config = self._store.load_resolved_config(self._run_id)
        limits = planning_limits_from_config(config)

        review_state, digest_bundle = build_plan_approval_validation_context(
            plan=plan,
            approval=loop.to_dict(),
            actual_plan_digest=compute_plan_digest(plan),
            actual_config_digest=compute_config_digest(config),
            actual_input_digest=compute_input_digest(
                config,
                base_dir=run_workspace(run),
            ),
            actual_output_goal_digest=compute_output_goal_digest(
                config,
                base_dir=run_workspace(run),
            ),
            actual_context_digest=(run.get("digests") or {}).get("context"),
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
        run = dict(run)
        run["revision"] = expected_revision + 1
        run["phase"] = PLAN_VALIDATED
        self._store.save_run(self._run_id, run, expected_revision)
        self._append_event(
            "whole_plan_review_approved",
            loop_id=loop.id,
            target_revision=plan.revision,
            reviewer_session_id=loop.reviewer_session_id,
        )
        run = self._store.load_run(self._run_id)
        return self._result_from_run(run, ok=True, loop=loop)

    def _terminate(self, outcome: str, message: str) -> WholePlanReviewResult:
        run = self._store.load_run(self._run_id)
        expected_revision = int(run["revision"])
        run = dict(run)
        run["revision"] = expected_revision + 1
        run["status"] = "completed"
        run["outcome"] = outcome
        self._store.save_run(self._run_id, run, expected_revision)
        self._append_event(
            "whole_plan_review_failed",
            outcome=outcome,
            message=message,
        )
        run = self._store.load_run(self._run_id)
        return self._result_from_run(run, ok=False, reason=message)

    def _normalize_loop_for_resume(self, loop: ReviewLoop) -> ReviewLoop:
        if loop.status != "changes_requested":
            return loop

        plan_revision = int(self._store.load_plan(self._run_id)["revision"])
        if plan_revision <= loop.target_revision:
            return loop

        return self._prepare_recheck(loop)

    def _get_or_create_active_loop(self) -> ReviewLoop:
        for payload in reversed(self._store.list_reviews(self._run_id)):
            if payload.get("type") != "whole_plan":
                continue
            loop = ReviewLoop.from_dict(payload)
            if loop.status in {"approved", "blocked"}:
                continue
            return loop
        return self._create_loop()

    def _create_loop(self) -> ReviewLoop:
        plan_revision = int(self._store.load_plan(self._run_id)["revision"])
        loop_id = self._next_loop_id()
        loop = ReviewLoop(
            id=loop_id,
            type="whole_plan",
            reviewer_session_id=None,
            target_revision=plan_revision,
            scope={"kind": "whole_plan"},
            status="pending",
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

    def _start_reviewer_session(self, loop: ReviewLoop) -> str:
        package = build_whole_plan_review_package(
            self._run_id,
            self._store.load_run(self._run_id),
            self._store.load_resolved_config(self._run_id),
            self._store.load_plan_model(self._run_id),
            loop,
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
            approved_digests=loop.approved_digests,
        )
        self._persist_loop(updated)
        self._append_event(
            "reviewer_session_started",
            loop_id=loop.id,
            session_id=session_id,
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

    def _resume_planner_with_findings(self, loop: ReviewLoop) -> None:
        run = self._store.load_run(self._run_id)
        session_id = _primary_planner_session_id(run)
        if session_id is None:
            raise ProviderRunError("primary planner session is missing for revision")

        self._provider.resume_primary_session(
            session_id,
            {
                "action": "address_review_findings",
                "phase": WHOLE_PLAN_REVIEW,
                "loop_id": loop.id,
                "target_revision": loop.target_revision,
                "findings": [finding.to_dict() for finding in loop.findings],
            },
        )
        self._consume_planner_turn(session_id)

    def _consume_planner_turn(self, session_id: str) -> None:
        for event in self._provider.stream_events(session_id):
            event_type = str(event.get("type") or "")
            if event_type == "error":
                text = event.get("text") or "provider error"
                raise ProviderRunError(str(text))
            if event_type == "tool_call":
                self._handle_plan_tool_call(event)
                continue
            if event_type == "done":
                if event.get("is_error"):
                    text = event.get("text") or "planner revision turn failed"
                    raise ProviderRunError(str(text))
                return

    def _handle_plan_tool_call(self, event: dict[str, Any]) -> None:
        tool = str(event.get("tool") or "")
        if tool != "plan_apply":
            return

        request = event.get("request")
        if not isinstance(request, dict):
            raise ProviderRunError("plan_apply tool_call requires a request object")

        role = event.get("role")
        if role is None or str(role).strip() != "planner":
            raise ProviderRunError("plan_apply tool_call requires role=planner")

        self._plan_service.apply(request, role=role)

    def _prepare_recheck(self, loop: ReviewLoop) -> ReviewLoop:
        plan_revision = int(self._store.load_plan(self._run_id)["revision"])
        session_id = loop.reviewer_session_id
        if session_id is None:
            raise ProviderRunError("reviewer session is missing for recheck")

        updated = ReviewLoop(
            id=loop.id,
            type=loop.type,
            reviewer_session_id=session_id,
            target_revision=plan_revision,
            scope=loop.scope,
            status="pending",
            findings=loop.findings,
            revision_cycles=loop.revision_cycles,
            approved_digests=None,
        )
        self._persist_loop(updated)
        self._provider.send(
            session_id,
            {
                "action": "recheck_revision",
                "phase": WHOLE_PLAN_REVIEW,
                "loop_id": loop.id,
                "target_revision": plan_revision,
            },
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
            reviewer_session_id=loop.reviewer_session_id if loop is not None else None,
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

    run_section = config.get("run") or {}
    digests = dict(run.get("digests") or {})
    limits = planning_limits_from_config(config)
    return {
        "run_id": run_id,
        "phase": WHOLE_PLAN_REVIEW,
        "type": "whole_plan",
        "loop_id": loop.id,
        "purpose": "Mandatory whole-plan review before production",
        "scope": dict(loop.scope),
        "target_revision": loop.target_revision,
        "plan_revision": plan.revision,
        "plan": build_plan_review_snapshot(plan, limits=limits),
        "input_refs": list(run_section.get("input_refs") or []),
        "output_goal": plan.output_goal,
        "boundaries": run_section.get("boundaries"),
        "acceptance": run_section.get("acceptance"),
        "digests": digests,
        "tool_instructions": {
            "role": "Only the reviewer role may submit review responses.",
            "plan_snapshot": (
                f"tdp agent plan snapshot --run {run_id} --view tree"
            ),
            "respond": (
                f"tdp agent review respond --run {run_id} --role reviewer "
                "--request <file>"
            ),
        },
    }


def _whole_plan_revision_limit(config: dict[str, Any]) -> int:
    review_limits = (config.get("limits") or {}).get("whole_plan_review") or {}
    return int(
        review_limits.get(
            "max_revision_cycles",
            _WHOLE_PLAN_LIMIT_DEFAULTS["max_revision_cycles"],
        )
    )


def _primary_planner_session_id(run: dict[str, Any]) -> str | None:
    sessions = run.get("sessions") or {}
    session_id = sessions.get("primary_planner_session_id")
    if session_id is None:
        return None
    return str(session_id)
