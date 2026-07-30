"""Shared helpers for stub-provider end-to-end lifecycle tests (todo 17)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from top_down_planning.agent_tool.config import planning_limits_from_config
from top_down_planning.domain.outcome import (
    evaluate_acceptance_invariant,
    load_approvals_for_acceptance,
)
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.digests import (
    compute_config_digest,
    compute_output_digest,
    compute_plan_digest,
)
from core_tools.provider import StubProvider
from tests.helpers import done_events, plan_apply_turn, write_config

ScriptBuilder = Callable[[str], list[dict[str, Any]]]


class E2EStubProvider(StubProvider):
    """Stub provider that can synthesize a final turn when the script queue runs dry."""

    def __init__(
        self,
        fallback_builder: ScriptBuilder | None = None,
    ) -> None:
        super().__init__()
        self._fallback_builder = fallback_builder

    def set_fallback_builder(self, builder: ScriptBuilder | None) -> None:
        self._fallback_builder = builder

    def _resolve_script(self, session_id: str) -> list[dict[str, Any]]:
        if (
            self._fallback_builder is not None
            and not self._session_scripts.get(session_id)
            and not self._default_scripts
        ):
            return self._fallback_builder(session_id)
        return super()._resolve_script(session_id)


def write_e2e_config(
    path: Path,
    *,
    limits: dict[str, Any] | None = None,
) -> Path:
    """Write a minimal stub-provider config for lifecycle e2e tests."""

    limits_block = limits or {}
    planning_limits = limits_block.get("planning") or {}
    whole_plan_limits = limits_block.get("whole_plan_review") or {}
    production_limits = limits_block.get("production") or {}
    whole_output_limits = limits_block.get("whole_output_review") or {}
    amendment_limits = limits_block.get("amendment") or {}

    body = f"""
run:
  output_goal: Deliver the sample output for e2e verification.
provider:
  name: stub
planning:
  max_depth: 4
limits:
  planning:
    max_expansion_iterations: {planning_limits.get("max_expansion_iterations", 20)}
    max_agent_turns: {planning_limits.get("max_agent_turns", 40)}
  whole_plan_review:
    max_revision_cycles: {whole_plan_limits.get("max_revision_cycles", 5)}
  production:
    max_batches: {production_limits.get("max_batches", 50)}
    max_agent_turns_per_batch: {production_limits.get("max_agent_turns_per_batch", 10)}
  whole_output_review:
    max_revision_cycles: {whole_output_limits.get("max_revision_cycles", 5)}
  amendment:
    max_requests: {amendment_limits.get("max_requests", 3)}
    max_revision_cycles_per_request: {amendment_limits.get("max_revision_cycles_per_request", 3)}
"""
    return write_config(path, body)


def planning_single_leaf_script() -> list[dict[str, Any]]:
    """Add one actionable leaf and signal candidate plan ready."""

    return plan_apply_turn(
        operations=[
            {
                "op": "add_item",
                "temp_id": "item-task",
                "parent_id": "item-root",
                "placement": {"last_child": True},
                "item": {
                    "title": "Deliver feature",
                    "outcome": "Feature is delivered and verifiable.",
                    "acceptance": ["Feature behavior is testable."],
                },
            }
        ],
    )


def planning_two_item_script() -> list[dict[str, Any]]:
    """Add two sibling leaves for amendment scenarios."""

    return plan_apply_turn(
        operations=[
            {
                "op": "add_item",
                "temp_id": "item-first",
                "parent_id": "item-root",
                "placement": {"last_child": True},
                "item": {
                    "title": "First",
                    "outcome": "First outcome.",
                    "acceptance": ["First is verifiable."],
                },
            },
            {
                "op": "add_item",
                "temp_id": "item-second",
                "parent_id": "item-root",
                "placement": {"last_child": True},
                "item": {
                    "title": "Second",
                    "outcome": "Second outcome.",
                    "acceptance": ["Second is verifiable."],
                },
            },
        ],
    )


def review_respond_script(
    *,
    decision: str,
    loop_id: str,
    target_revision: int = 0,
    findings: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    return [
        {
            "type": "tool_call",
            "tool": "review_respond",
            "role": "reviewer",
            "request": {
                "loop_id": loop_id,
                "target_revision": target_revision,
                "decision": decision,
                "findings": findings or [],
            },
        },
        *done_events(text="review turn"),
    ]


def production_batch_script(
    *,
    plan_items: list[str],
    dispositions: dict[str, dict[str, Any]],
    production_revision: int = 0,
    submit_completion: bool = False,
    goal_assessment: str = "Output goal is fully met.",
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = [
        {
            "type": "tool_call",
            "tool": "production_apply",
            "role": "producer",
            "request": {
                "production_revision": production_revision,
                "plan_items": plan_items,
                "dispositions": dispositions,
                "outputs": [],
                "contributions": [],
                "summary": "batch complete",
            },
        },
    ]
    if submit_completion:
        events.append(
            {
                "type": "tool_call",
                "tool": "production_submit_completion",
                "role": "producer",
                "request": {"goal_assessment": goal_assessment},
            }
        )
    events.extend(done_events(signal="batch_complete", text="production turn"))
    return events


def leaf_item_ids(store: FileRunStore, run_id: str) -> list[str]:
    plan = store.load_plan_model(run_id)
    return sorted(
        item_id
        for item_id, item in plan.items.items()
        if item_id != "item-root" and item.parent_id == "item-root"
    )


def current_plan_revision(store: FileRunStore, run_id: str) -> int:
    return int(store.load_plan(run_id)["revision"])


def whole_plan_review_script(
    store: FileRunStore,
    run_id: str,
    *,
    decision: str,
    loop_id: str = "review-whole-plan-01",
) -> list[dict[str, Any]]:
    return review_respond_script(
        decision=decision,
        loop_id=loop_id,
        target_revision=current_plan_revision(store, run_id),
    )


def whole_output_review_script(
    store: FileRunStore,
    run_id: str,
    *,
    decision: str,
    loop_id: str = "review-whole-output-01",
) -> list[dict[str, Any]]:
    production = store.load_production(run_id)
    return review_respond_script(
        decision=decision,
        loop_id=loop_id,
        target_revision=int(production["output_revision"]),
    )


def write_agent_request(path: Path, payload: dict[str, Any]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def assert_acceptance_invariant_for_run(store: FileRunStore, run_id: str) -> None:
    """Assert proposal §21 acceptance invariant for a completed accepted run."""

    run = store.load_run(run_id)
    assert run.get("outcome") == "accepted"
    assert run.get("status") == "completed"
    assert run.get("phase") == "output_validated"

    plan = store.load_plan_model(run_id)
    production = store.load_production(run_id)
    config = store.load_resolved_config(run_id)
    reviews = store.list_reviews(run_id)
    limits = planning_limits_from_config(config)

    plan_approval, output_approval = load_approvals_for_acceptance(
        reviews,
        plan_revision=plan.revision,
        output_revision=int(production["output_revision"]),
    )
    assert plan_approval is not None
    assert output_approval is not None

    invariant, plan_validation, output_validation = evaluate_acceptance_invariant(
        plan=plan,
        production=production,
        reviews=reviews,
        limits=limits,
        run=run,
        plan_approval=plan_approval,
        output_approval=output_approval,
        actual_plan_digest=compute_plan_digest(plan),
        actual_config_digest=compute_config_digest(config),
        actual_output_digest=compute_output_digest(production),
    )

    assert invariant.satisfied is True
    assert plan_validation.ok is True
    assert output_validation.ok is True
