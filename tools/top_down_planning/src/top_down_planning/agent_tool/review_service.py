"""Agent review request/respond service (proposal §8, §11)."""

from __future__ import annotations

from typing import Any

from top_down_planning.agent_tool.authorization import authorize_mutation
from top_down_planning.agent_tool.errors import RequestError
from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.domain.reviews import (
    ReviewLoop,
    apply_review_response,
    find_overlapping_active_focused_loop,
    focused_loop_count,
    parse_findings,
    validate_decision,
    validate_findings_within_scope,
    validate_focused_scope,
)
from top_down_planning.persistence.commit import CommitSpec

_FOCUSED_PLAN_LIMIT_DEFAULTS = DEFAULT_CONFIG["limits"]["focused_plan_review"]
_FOCUSED_OUTPUT_LIMIT_DEFAULTS = DEFAULT_CONFIG["limits"]["focused_output_review"]


class ReviewAgentService:
    """Structured review interaction for agents against a persisted run."""

    def __init__(self, store: RunStore, run_id: str) -> None:
        self._store = store
        self._run_id = run_id

    def request(
        self,
        request: dict[str, Any],
        *,
        capability_token: str | None = None,
    ) -> dict[str, Any]:
        role = authorize_mutation(
            self._store,
            self._run_id,
            operation="review_request",
            capability_token=capability_token,
        )
        review_type = str(request.get("type") or "").strip()
        if review_type not in {"focused_plan", "focused_output"}:
            raise RequestError(
                "request.type must be focused_plan or focused_output"
            )

        if review_type == "focused_plan" and role != "planner":
            raise RequestError("focused_plan reviews require a planner capability")
        if review_type == "focused_output" and role != "producer":
            raise RequestError("focused_output reviews require a producer capability")

        config = self._store.load_resolved_config(self._run_id)
        review_config = (config.get("review") or {}).get(
            "focused_plan" if review_type == "focused_plan" else "focused_output"
        ) or {}
        if review_config.get("enabled") is not True:
            raise RequestError(f"{review_type} reviews are disabled in config")

        try:
            scope = validate_focused_scope(request.get("scope"), review_type)
        except ValueError as exc:
            raise RequestError(str(exc)) from exc

        reviews = self._store.list_reviews(self._run_id)
        overlapping = find_overlapping_active_focused_loop(
            reviews,
            review_type,
            scope["item_ids"],
        )
        if overlapping is not None:
            raise RequestError(
                f"active {review_type} review {overlapping} already covers overlapping scope"
            )

        loop_count = focused_loop_count(reviews, review_type)
        max_loops = _focused_max_loops(config, review_type)
        if loop_count >= max_loops:
            raise RequestError(
                f"{review_type} review exceeded max_loops ({max_loops})"
            )

        if review_type == "focused_output":
            target_revision = int(self._store.load_production(self._run_id)["output_revision"])
        else:
            target_revision = int(self._store.load_plan(self._run_id)["revision"])

        loop_id = _next_focused_loop_id(reviews, review_type)
        loop = ReviewLoop(
            id=loop_id,
            type=review_type,  # type: ignore[arg-type]
            reviewer_session_id=None,
            target_revision=target_revision,
            scope=scope,
            status="pending",
        )
        self._store.commit(
            self._run_id,
            CommitSpec(
                reviews=[loop.to_dict()],
                events=[
                    {
                        "type": "focused_review_requested",
                        "run_id": self._run_id,
                        "loop_id": loop_id,
                        "review_type": review_type,
                        "scope": scope,
                        "target_revision": target_revision,
                        "requested_by": role,
                    }
                ],
            ),
        )

        return {
            "ok": True,
            "loop_id": loop_id,
            "type": review_type,
            "scope": scope,
            "target_revision": target_revision,
            "status": loop.status,
        }

    def respond(
        self,
        request: dict[str, Any],
        *,
        capability_token: str | None = None,
    ) -> dict[str, Any]:
        authorize_mutation(
            self._store,
            self._run_id,
            operation="review_respond",
            capability_token=capability_token,
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

        loop = ReviewLoop.from_dict(self._store.load_review(self._run_id, loop_id))
        if loop.status in {"approved", "blocked"}:
            raise RequestError(f"review loop {loop_id} is already terminal: {loop.status}")

        if loop.type in {"focused_plan", "focused_output"}:
            try:
                validate_findings_within_scope(findings, loop.scope)
            except ValueError as exc:
                raise RequestError(str(exc)) from exc

        if loop.type == "whole_output" or loop.type == "focused_output":
            current_revision = int(self._store.load_production(self._run_id)["output_revision"])
            revision_label = "output"
        else:
            current_revision = int(self._store.load_plan(self._run_id)["revision"])
            revision_label = "plan"
        if target_revision != current_revision:
            raise RequestError(
                f"target_revision {target_revision} does not match current {revision_label} "
                f"revision {current_revision}"
            )

        approved_digests: dict[str, str] | None = None
        if decision == "approved" and loop.type in {"whole_plan", "whole_output"}:
            run = self._store.load_run(self._run_id)
            approved_digests = {
                str(key): str(value)
                for key, value in (run.get("digests") or {}).items()
                if value is not None
            }
            if loop.type == "whole_output":
                from top_down_planning.persistence.digests import compute_output_digest

                production = self._store.load_production(self._run_id)
                approved_digests["output"] = compute_output_digest(production)

        try:
            updated = apply_review_response(
                loop,
                target_revision=target_revision,
                decision=decision,
                findings=findings,
                approved_digests=approved_digests,
            )
        except ValueError as exc:
            raise RequestError(str(exc)) from exc

        self._store.commit(
            self._run_id,
            CommitSpec(
                reviews=[updated.to_dict()],
                events=[
                    {
                        "type": "review_responded",
                        "run_id": self._run_id,
                        "loop_id": loop_id,
                        "decision": decision,
                        "target_revision": target_revision,
                        "finding_count": len(findings),
                    }
                ],
            ),
        )

        return {
            "ok": True,
            "loop_id": loop_id,
            "decision": decision,
            "target_revision": target_revision,
            "status": updated.status,
            "findings": [finding.to_dict() for finding in updated.findings],
        }


def _focused_max_loops(config: dict[str, Any], review_type: str) -> int:
    if review_type == "focused_plan":
        review_limits = (config.get("limits") or {}).get("focused_plan_review") or {}
        return int(
            review_limits.get("max_loops", _FOCUSED_PLAN_LIMIT_DEFAULTS["max_loops"])
        )
    review_limits = (config.get("limits") or {}).get("focused_output_review") or {}
    return int(
        review_limits.get("max_loops", _FOCUSED_OUTPUT_LIMIT_DEFAULTS["max_loops"])
    )


def _next_focused_loop_id(reviews: list[dict[str, Any]], review_type: str) -> str:
    prefix = (
        "review-focused-plan"
        if review_type == "focused_plan"
        else "review-focused-output"
    )
    existing = [
        payload.get("id")
        for payload in reviews
        if payload.get("type") == review_type and payload.get("id")
    ]
    index = len(existing) + 1
    return f"{prefix}-{index:02d}"
