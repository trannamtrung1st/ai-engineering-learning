"""Agent review respond service (proposal §8, §11)."""

from __future__ import annotations

from typing import Any

from top_down_planning.agent_tool.errors import RequestError, RoleDeniedError
from top_down_planning.domain.reviews import (
    ReviewLoop,
    apply_review_response,
    parse_findings,
    validate_decision,
)
from top_down_planning.persistence.interface import RunStore


class ReviewAgentService:
    """Structured review interaction for agents against a persisted run."""

    def __init__(self, store: RunStore, run_id: str) -> None:
        self._store = store
        self._run_id = run_id

    def respond(
        self,
        request: dict[str, Any],
        *,
        role: str,
    ) -> dict[str, Any]:
        normalized_role = str(role).strip()
        if normalized_role != "reviewer":
            raise RoleDeniedError(
                normalized_role,
                action="Only the reviewer role may submit review responses.",
            )

        loop_id = request.get("loop_id")
        if loop_id is None or not str(loop_id).strip():
            raise RequestError("respond requires loop_id")
        loop_id = str(loop_id).strip()

        if "target_revision" not in request:
            raise RequestError("respond requires target_revision")
        target_revision = int(request["target_revision"])

        if "decision" not in request:
            raise RequestError("respond requires decision")

        try:
            decision = validate_decision(str(request["decision"]))
            findings = parse_findings(request.get("findings") or [])
        except ValueError as exc:
            raise RequestError(str(exc)) from exc

        plan_revision = int(self._store.load_plan(self._run_id)["revision"])
        if target_revision != plan_revision:
            raise RequestError(
                f"target_revision {target_revision} does not match current plan "
                f"revision {plan_revision}"
            )

        loop = ReviewLoop.from_dict(self._store.load_review(self._run_id, loop_id))
        if loop.status in {"approved", "blocked"}:
            raise RequestError(f"review loop {loop_id} is already terminal: {loop.status}")

        try:
            updated = apply_review_response(
                loop,
                target_revision=target_revision,
                decision=decision,
                findings=findings,
            )
        except ValueError as exc:
            raise RequestError(str(exc)) from exc

        self._store.save_review(self._run_id, updated.to_dict())
        self._store.append_event(
            self._run_id,
            {
                "type": "review_responded",
                "run_id": self._run_id,
                "loop_id": loop_id,
                "decision": decision,
                "target_revision": target_revision,
                "finding_count": len(findings),
            },
        )

        return {
            "ok": True,
            "loop_id": loop_id,
            "decision": decision,
            "target_revision": target_revision,
            "status": updated.status,
            "findings": [finding.to_dict() for finding in updated.findings],
        }
