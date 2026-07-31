"""Shared helpers for stub-provider end-to-end lifecycle tests (todo 17)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from top_down_planning.agent_tool.config import planning_limits_from_config
from top_down_planning.config import compute_input_digest, compute_output_goal_digest
from top_down_planning.domain.outcome import (
    evaluate_acceptance_invariant,
    load_approvals_for_acceptance,
)
from top_down_planning.orchestrator.phases import WHOLE_PLAN_REVIEW, WHOLE_OUTPUT_REVIEW
from top_down_planning.workspace import run_workspace
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.digests import (
    compute_config_digest,
    compute_output_digest,
    compute_plan_digest,
)
from core_tools.provider import StubProvider
from tests.helpers import (
    apply_plan,
    apply_production,
    done_events,
    mandatory_blocker_respond_request,
    mandatory_initial_respond_request,
    only_run_id,
    request_amendment,
    respond_review,
    script_reviewer_allocate,
    write_config,
)

def queue_turn(
    provider: Any,
    script: tuple[list[dict[str, Any]], Callable[[], None]],
) -> None:
    """Queue a (events, mutate) script using keyword mutate_store."""

    events, mutate = script
    provider.script_turn(events, mutate_store=mutate)


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
    max_items_added: {planning_limits.get("max_items_added", 20)}
    max_agent_turns: {planning_limits.get("max_agent_turns", 40)}
  whole_plan_review:
    max_revision_cycles: {whole_plan_limits.get("max_revision_cycles", 5)}
    max_blocker_review_rounds: {whole_plan_limits.get("max_blocker_review_rounds", 3)}
  production:
    max_batches: {production_limits.get("max_batches", 50)}
    max_agent_turns_per_batch: {production_limits.get("max_agent_turns_per_batch", 10)}
  whole_output_review:
    max_revision_cycles: {whole_output_limits.get("max_revision_cycles", 5)}
    max_blocker_review_rounds: {whole_output_limits.get("max_blocker_review_rounds", 3)}
  amendment:
    max_requests: {amendment_limits.get("max_requests", 3)}
    max_revision_cycles_per_request: {amendment_limits.get("max_revision_cycles_per_request", 3)}
"""
    return write_config(path, body)


def planning_single_leaf_script(store: FileRunStore) -> tuple[list[dict[str, Any]], Callable[[], None]]:
    """Add one actionable leaf and signal candidate plan ready."""

    operations = [
        {
            "op": "add_item",
            "temp_id": "item-task",
            "parent_id": "item-root",
            "placement": {"last_child": True},
            "item": {
    "kind": "work",

                "title": "Deliver feature",
                "outcome": "Feature is delivered and verifiable.",
                "acceptance": ["Feature behavior is testable."],
            },
        }
    ]

    def mutate() -> None:
        run_id = only_run_id(store)
        apply_plan(store, run_id, base_revision=0, operations=operations)()

    return done_events(signal="candidate_plan_ready", text="planning turn"), mutate


def planning_two_item_script(store: FileRunStore) -> tuple[list[dict[str, Any]], Callable[[], None]]:
    """Add two sibling leaves for amendment scenarios."""

    operations = [
        {
            "op": "add_item",
            "temp_id": "item-first",
            "parent_id": "item-root",
            "placement": {"last_child": True},
            "item": {
    "kind": "work",

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
    "kind": "work",

                "title": "Second",
                "outcome": "Second outcome.",
                "acceptance": ["Second is verifiable."],
            },
        },
    ]

    def mutate() -> None:
        run_id = only_run_id(store)
        apply_plan(store, run_id, base_revision=0, operations=operations)()

    return done_events(signal="candidate_plan_ready", text="planning turn"), mutate


def review_respond_script(
    store: FileRunStore,
    run_id: str,
    *,
    decision: str,
    loop_id: str,
    target_revision: int = 0,
    findings: list[dict[str, Any]] | None = None,
    phase: str = WHOLE_PLAN_REVIEW,
) -> tuple[list[dict[str, Any]], Callable[[], None]]:
    if phase == WHOLE_PLAN_REVIEW:
        review_type = "whole_plan"
    elif phase == WHOLE_OUTPUT_REVIEW:
        review_type = "whole_output"
    else:
        review_type = None

    if review_type is not None:
        request = mandatory_initial_respond_request(
            store,
            run_id,
            loop_id=loop_id,
            target_revision=target_revision,
            review_type=review_type,
            decision=decision,
            findings=findings,
        )
    else:
        request = {
            "loop_id": loop_id,
            "target_revision": target_revision,
            "decision": decision,
            "findings": findings or [],
        }

    return done_events(text="review turn"), respond_review(
        store,
        run_id,
        request,
        phase=phase,
        loop_id=loop_id,
    )


def production_batch_script(
    store: FileRunStore,
    run_id: str,
    *,
    plan_items: list[str],
    dispositions: dict[str, dict[str, Any]],
    production_revision: int = 0,
    submit_completion: bool = False,
    goal_assessment: str = "Output goal is fully met.",
) -> tuple[list[dict[str, Any]], Callable[[], None]]:
    def mutate() -> None:
        apply_production(
            store,
            run_id,
            {
                "production_revision": production_revision,
                "plan_items": plan_items,
                "dispositions": dispositions,
                "outputs": [],
                "contributions": [],
                "summary": "batch complete",
            },
            handler="apply",
        )()
        if submit_completion:
            apply_production(
                store,
                run_id,
                {"goal_assessment": goal_assessment, "goal_met": True},
                handler="submit_completion",
            )()

    return done_events(signal="batch_complete", text="production turn"), mutate


def root_child_item_ids(store: FileRunStore, run_id: str) -> list[str]:
    """Direct children of item-root (flat e2e fixtures only)."""
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
) -> tuple[list[dict[str, Any]], Callable[[], None]]:
    return review_respond_script(
        store,
        run_id,
        decision=decision,
        loop_id=loop_id,
        target_revision=current_plan_revision(store, run_id),
        phase=WHOLE_PLAN_REVIEW,
    )


def script_whole_plan_review(
    provider: Any,
    store: FileRunStore,
    run_id: str,
    *,
    decision: str,
    loop_id: str = "review-whole-plan-01",
) -> None:
    """Queue allocate + respond turns for whole-plan review (mandatory gate when approved)."""

    target_revision = current_plan_revision(store, run_id)
    if decision == "approved":
        script_reviewer_allocate(provider)
        queue_turn(
            provider,
            (
                done_events(text="review turn"),
                respond_review(
                    store,
                    run_id,
                    mandatory_initial_respond_request(
                        store,
                        run_id,
                        loop_id=loop_id,
                        target_revision=target_revision,
                        review_type="whole_plan",
                    ),
                    phase=WHOLE_PLAN_REVIEW,
                    loop_id=loop_id,
                ),
            ),
        )
        script_reviewer_allocate(provider)
        queue_turn(
            provider,
            (
                done_events(text="blocker review turn"),
                respond_review(
                    store,
                    run_id,
                    mandatory_blocker_respond_request(
                        store,
                        run_id,
                        loop_id=loop_id,
                        target_revision=target_revision,
                        review_type="whole_plan",
                    ),
                    phase=WHOLE_PLAN_REVIEW,
                    loop_id=loop_id,
                ),
            ),
        )
        return

    script_reviewer_allocate(provider)
    queue_turn(
        provider,
        review_respond_script(
            store,
            run_id,
            decision=decision,
            loop_id=loop_id,
            target_revision=target_revision,
            phase=WHOLE_PLAN_REVIEW,
        ),
    )


def whole_output_review_script(
    store: FileRunStore,
    run_id: str,
    *,
    decision: str,
    loop_id: str = "review-whole-output-01",
) -> tuple[list[dict[str, Any]], Callable[[], None]]:
    production = store.load_production(run_id)
    return review_respond_script(
        store,
        run_id,
        decision=decision,
        loop_id=loop_id,
        target_revision=int(production["output_revision"]),
        phase=WHOLE_OUTPUT_REVIEW,
    )


def script_whole_output_review(
    provider: Any,
    store: FileRunStore,
    run_id: str,
    *,
    decision: str,
    loop_id: str = "review-whole-output-01",
) -> None:
    """Queue allocate + respond turns for whole-output review (mandatory gate when approved)."""

    production = store.load_production(run_id)
    target_revision = int(production["output_revision"])
    if decision == "approved":
        script_reviewer_allocate(provider)
        queue_turn(
            provider,
            (
                done_events(text="review turn"),
                respond_review(
                    store,
                    run_id,
                    mandatory_initial_respond_request(
                        store,
                        run_id,
                        loop_id=loop_id,
                        target_revision=target_revision,
                        review_type="whole_output",
                    ),
                    phase=WHOLE_OUTPUT_REVIEW,
                    loop_id=loop_id,
                ),
            ),
        )
        script_reviewer_allocate(provider)
        queue_turn(
            provider,
            (
                done_events(text="blocker review turn"),
                respond_review(
                    store,
                    run_id,
                    mandatory_blocker_respond_request(
                        store,
                        run_id,
                        loop_id=loop_id,
                        target_revision=target_revision,
                        review_type="whole_output",
                    ),
                    phase=WHOLE_OUTPUT_REVIEW,
                    loop_id=loop_id,
                ),
            ),
        )
        return

    script_reviewer_allocate(provider)
    queue_turn(
        provider,
        review_respond_script(
            store,
            run_id,
            decision=decision,
            loop_id=loop_id,
            target_revision=target_revision,
            phase=WHOLE_OUTPUT_REVIEW,
        ),
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
        plan_approval=plan_approval,
        output_approval=output_approval,
        actual_plan_digest=compute_plan_digest(plan),
        actual_config_digest=compute_config_digest(config),
        actual_output_digest=compute_output_digest(production),
        actual_input_digest=compute_input_digest(
            config,
            base_dir=run_workspace(run),
        ),
        actual_output_goal_digest=compute_output_goal_digest(
            config,
            base_dir=run_workspace(run),
        ),
        actual_context_spec_digest=(run.get("digests") or {}).get("context_spec"),
        actual_context_snapshot_digest=(run.get("digests") or {}).get("context_snapshot"),
    )

    assert invariant.satisfied is True
    assert plan_validation.ok is True
    assert output_validation.ok is True
