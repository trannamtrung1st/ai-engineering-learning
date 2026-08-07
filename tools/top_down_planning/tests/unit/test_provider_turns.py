"""Tests for provider turn observation helpers."""

from __future__ import annotations

from pathlib import Path

from top_down_planning.agent_tool import ReviewAgentService
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator import PlanningPhaseOrchestrator
from top_down_planning.orchestrator.phases import WHOLE_OUTPUT_REVIEW
from top_down_planning.orchestrator.provider_turns import (
    TurnTextAccumulator,
    clear_phase_action_id,
    ensure_phase_action_id,
    extract_completion_signal_from_text,
    find_pending_focused_review_loop_id,
    resolve_turn_signal,
    review_decision_from_store,
)
from top_down_planning.persistence import FileRunStore
from core_tools.provider import StubProvider
from tests.helpers import (
    apply_production,
    create_run_kwargs,
    done_events,
    grant_capability,
    mandatory_initial_respond_request,
    mandatory_output_digest,
    plan_root_item,
    record_finding_actions,
    respond_review,
    save_review_payload,
)
from tests.unit.test_whole_output_review import _create_run_at_whole_output_review


def test_ensure_phase_action_id_assigns_and_reuses(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000905-000905"
    root = plan_root_item(title="Deliver the feature", outcome="Deliver the feature.")
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the feature.",
        items={"item-root": root},
    )
    config = {
        "run": {"output_goal": "Deliver the feature.", "input_refs": ["README.md"]},
        "planning": {"stop_hint": "Stop when ready.", "max_depth": 4, "max_expansion_per_item": 7},
        "limits": {"planning": {"max_items_added": 20, "max_agent_turns": 40}},
    }
    store.create_run(run_id, plan=plan, **create_run_kwargs(store.root, resolved_config=config))

    first = ensure_phase_action_id(store, run_id)
    assert first.startswith("action-")
    assert store.load_run(run_id)["phase_action_id"] == first

    second = ensure_phase_action_id(store, run_id)
    assert second == first

    clear_phase_action_id(store, run_id)
    assert store.load_run(run_id)["phase_action_id"] is None
    events = store.load_events(run_id)
    assert any(event["type"] == "phase_action_assigned" for event in events)


def test_extract_completion_signal_from_exact_text() -> None:
    allowed = frozenset({"candidate_plan_ready"})
    assert (
        extract_completion_signal_from_text("candidate_plan_ready", allowed=allowed)
        == "candidate_plan_ready"
    )


def test_extract_completion_signal_from_multiline_text() -> None:
    allowed = frozenset({"candidate_plan_ready"})
    text = "Plan looks complete.\n\ncandidate_plan_ready\n"
    assert extract_completion_signal_from_text(text, allowed=allowed) == "candidate_plan_ready"


def test_resolve_turn_signal_prefers_done_signal() -> None:
    allowed = frozenset({"candidate_plan_ready", "batch_complete"})
    assert (
        resolve_turn_signal(
            done_signal="batch_complete",
            assistant_text="candidate_plan_ready",
            done_text="candidate_plan_ready",
            allowed=allowed,
        )
        == "batch_complete"
    )


def test_turn_text_accumulator_resolves_assistant_only_signal() -> None:
    accumulator = TurnTextAccumulator()
    accumulator.ingest({"type": "assistant", "text": "candidate_plan_ready"})
    accumulator.ingest(
        {
            "type": "done",
            "subtype": "success",
            "text": "done",
            "is_error": False,
        }
    )
    assert accumulator.resolve_signal(frozenset({"candidate_plan_ready"})) == (
        "candidate_plan_ready"
    )


def test_find_pending_focused_review_loop_id(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000901-000901"
    root = plan_root_item(title="Deliver the feature", outcome="Deliver the feature.")
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the feature.",
        items={"item-root": root},
    )
    config = {
        "run": {"output_goal": "Deliver the feature.", "input_refs": ["README.md"]},
        "planning": {"stop_hint": "Stop when ready.", "max_depth": 4, "max_expansion_per_item": 7},
        "limits": {"planning": {"max_items_added": 20, "max_agent_turns": 40}},
        "review": {"focused_plan": {"enabled": True}, "focused_output": {"enabled": True}},
    }
    store.create_run(run_id, plan=plan, **create_run_kwargs(store.root, resolved_config=config))

    token = grant_capability(store, run_id, role="planner", phase="planning")
    ReviewAgentService(store, run_id).request(
        {
            "type": "focused_plan",
            "scope": {"item_ids": ["item-root"]},
        },
        capability_token=token,
    )

    assert find_pending_focused_review_loop_id(
        store,
        run_id,
        review_type="focused_plan",
    ) == "review-focused-plan-01"


def test_build_reviewer_decision_boundary_observer_detects_terminal_decision(
    tmp_path: Path,
) -> None:
    from top_down_planning.orchestrator.provider_turns import (
        build_reviewer_decision_boundary_observer,
    )
    from top_down_planning.orchestrator.reviewer_session import (
        REVIEWER_DECISION_COMPLETE_SIGNAL,
    )

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000902-000902"
    _create_run_at_whole_output_review(store, run_id=run_id)
    observe = build_reviewer_decision_boundary_observer(
        store,
        run_id,
        "review-whole-output-01",
    )

    assert observe() is None

    production = store.load_production(run_id)
    respond_review(
        store,
        run_id,
        mandatory_initial_respond_request(
            store,
            run_id,
            loop_id="review-whole-output-01",
            target_revision=int(production["output_revision"]),
            review_type="whole_output",
        ),
        phase=WHOLE_OUTPUT_REVIEW,
        loop_id="review-whole-output-01",
    )()

    assert observe() == REVIEWER_DECISION_COMPLETE_SIGNAL


def test_reviewer_boundary_observer_ignores_prior_decision(tmp_path: Path) -> None:
    from top_down_planning.orchestrator.provider_turns import (
        build_reviewer_decision_boundary_observer,
    )

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000902-000902"
    _create_run_at_whole_output_review(store, run_id=run_id)
    production = store.load_production(run_id)
    respond_review(
        store,
        run_id,
        mandatory_initial_respond_request(
            store,
            run_id,
            loop_id="review-whole-output-01",
            target_revision=int(production["output_revision"]),
            review_type="whole_output",
        ),
        phase=WHOLE_OUTPUT_REVIEW,
        loop_id="review-whole-output-01",
    )()

    observe = build_reviewer_decision_boundary_observer(
        store,
        run_id,
        "review-whole-output-01",
    )

    assert observe() is None


def test_build_producer_batch_boundary_observer_ignores_prior_batch(
    tmp_path: Path,
) -> None:
    from top_down_planning.orchestrator.provider_turns import (
        build_producer_batch_boundary_observer,
        production_batch_count,
    )

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000902-000902"
    _create_run_at_whole_output_review(store, run_id=run_id)
    assert production_batch_count(store, run_id) > 0

    observe = build_producer_batch_boundary_observer(store, run_id)

    assert observe() is None


def test_build_producer_turn_boundary_observer_detects_completion_claim(
    tmp_path: Path,
) -> None:
    from top_down_planning.orchestrator.provider_turns import (
        PRODUCER_COMPLETION_COMPLETE_SIGNAL,
        build_producer_turn_boundary_observer,
    )

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000902-000902"
    _create_run_at_whole_output_review(store, run_id=run_id)
    observe = build_producer_turn_boundary_observer(store, run_id)

    assert observe() is None

    apply_production(
        store,
        run_id,
        {"goal_assessment": "Revised output goal is met."},
        handler="submit_completion",
        phase=WHOLE_OUTPUT_REVIEW,
    )()

    assert observe() == PRODUCER_COMPLETION_COMPLETE_SIGNAL


def test_build_owner_finding_action_boundary_observer_detects_record_actions(
    tmp_path: Path,
) -> None:
    from top_down_planning.orchestrator.provider_turns import (
        build_owner_finding_action_boundary_observer,
    )
    from top_down_planning.orchestrator.reviewer_session import (
        OWNER_FINDING_ACTION_COMPLETE_SIGNAL,
    )

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000902-000902"
    _create_run_at_whole_output_review(store, run_id=run_id)
    loop_id = "review-whole-output-01"
    save_review_payload(
        store,
        run_id,
        {
            **dict(store.load_review(run_id, loop_id)),
            "finding_set_id": "review-whole-output-01-fs-01",
            "findings": [
                {
                    "id": "finding-01",
                    "severity": "minor",
                    "category": "maintainability",
                    "target_refs": ["item-leaf"],
                    "issue": "Optional polish.",
                    "recommended_change": "Improve wording.",
                    "status": "unresolved",
                }
            ],
        },
    )
    observe = build_owner_finding_action_boundary_observer(store, run_id, loop_id)

    assert observe() is None

    record_finding_actions(
        store,
        run_id,
        {
            "loop_id": loop_id,
            "target_revision": 1,
            "target_digest": mandatory_output_digest(store, run_id),
            "finding_set_id": "review-whole-output-01-fs-01",
            "finding_actions": [
                {
                    "finding_id": "finding-01",
                    "action": "defer",
                    "actor_role": "producer",
                    "rationale": "Defer polish",
                }
            ],
        },
        role="producer",
        phase=WHOLE_OUTPUT_REVIEW,
        loop_id=loop_id,
    )()

    assert observe() == OWNER_FINDING_ACTION_COMPLETE_SIGNAL


def test_build_producer_completion_boundary_observer_detects_new_claim(
    tmp_path: Path,
) -> None:
    from top_down_planning.orchestrator.provider_turns import (
        build_producer_completion_boundary_observer,
    )
    from top_down_planning.orchestrator.producer_session import (
        PRODUCER_COMPLETION_COMPLETE_SIGNAL,
    )

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000902-000902"
    _create_run_at_whole_output_review(store, run_id=run_id)
    observe = build_producer_completion_boundary_observer(store, run_id)

    assert observe() is None

    apply_production(
        store,
        run_id,
        {"goal_assessment": "Revised output goal is met."},
        handler="submit_completion",
        phase=WHOLE_OUTPUT_REVIEW,
    )()

    assert observe() == PRODUCER_COMPLETION_COMPLETE_SIGNAL


def test_producer_completion_boundary_observer_ignores_prior_claim(
    tmp_path: Path,
) -> None:
    from top_down_planning.orchestrator.provider_turns import (
        build_producer_completion_boundary_observer,
    )

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000902-000902"
    _create_run_at_whole_output_review(store, run_id=run_id)
    apply_production(
        store,
        run_id,
        {"goal_assessment": "Initial completion claim."},
        handler="submit_completion",
        phase=WHOLE_OUTPUT_REVIEW,
    )()

    observe = build_producer_completion_boundary_observer(store, run_id)

    assert observe() is None


def test_review_decision_from_store_after_shell_respond(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000902-000902"
    root = plan_root_item(title="Deliver the feature", outcome="Deliver the feature.")
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the feature.",
        items={"item-root": root},
    )
    config = {
        "run": {"output_goal": "Deliver the feature.", "input_refs": ["README.md"]},
        "planning": {"stop_hint": "Stop when ready.", "max_depth": 4, "max_expansion_per_item": 7},
        "limits": {"planning": {"max_items_added": 20, "max_agent_turns": 40}},
        "review": {"focused_plan": {"enabled": True}, "focused_output": {"enabled": True}},
    }
    store.create_run(run_id, plan=plan, **create_run_kwargs(store.root, resolved_config=config))

    planner_token = grant_capability(store, run_id, role="planner", phase="planning")
    ReviewAgentService(store, run_id).request(
        {
            "type": "focused_plan",
            "scope": {"item_ids": ["item-root"]},
        },
        capability_token=planner_token,
    )

    reviewer_token = grant_capability(
        store,
        run_id,
        role="reviewer",
        phase="planning",
        loop_id="review-focused-plan-01",
    )
    loop = store.load_review(run_id, "review-focused-plan-01")
    ReviewAgentService(store, run_id).respond(
        {
            "loop_id": "review-focused-plan-01",
            "target_revision": 0,
            "finding_set_id": str(loop.get("finding_set_id") or ""),
            "reported_findings": [],
            "review_completed": True,
            "summary": "clear",
        },
        capability_token=reviewer_token,
    )

    assert review_decision_from_store(store, run_id, "review-focused-plan-01") == "approved"


def test_planning_accepts_assistant_text_completion_signal(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000903-000903"
    root = plan_root_item(title="Deliver the feature", outcome="Deliver the feature.")
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the feature.",
        items={"item-root": root},
    )
    config = {
        "run": {"output_goal": "Deliver the feature.", "input_refs": ["README.md"]},
        "planning": {"stop_hint": "Stop when ready.", "max_depth": 4, "max_expansion_per_item": 7},
        "limits": {"planning": {"max_items_added": 20, "max_agent_turns": 40}},
    }
    store.create_run(run_id, plan=plan, **create_run_kwargs(store.root, resolved_config=config))

    provider = StubProvider()
    provider.script_turn(
        [
            {"type": "assistant", "text": "candidate_plan_ready"},
            {"type": "done", "subtype": "success", "text": "done", "is_error": False},
        ]
    )

    result = PlanningPhaseOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.phase == "whole_plan_review"


def test_planning_runs_store_created_focused_review_before_advancing(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000904-000904"
    root = plan_root_item(title="Deliver the feature", outcome="Deliver the feature.")
    api = PlanItem(
        id="item-api",
        parent_id="item-root",
        order_key="0000000000",
        title="API",
        outcome="API exists.",
        acceptance=["API behavior is verifiable."],
        kind="work",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the feature.",
        items={"item-root": root, "item-api": api},
    )
    config = {
        "run": {"output_goal": "Deliver the feature.", "input_refs": ["README.md"]},
        "planning": {"stop_hint": "Stop when ready.", "max_depth": 4, "max_expansion_per_item": 7},
        "limits": {
            "planning": {"max_items_added": 20, "max_agent_turns": 40},
            "focused_plan_review": {
                "max_loops": 5,
                "max_revision_cycles_per_loop": 3,
            },
        },
        "review": {"focused_plan": {"enabled": True}, "focused_output": {"enabled": True}},
    }
    store.create_run(run_id, plan=plan, **create_run_kwargs(store.root, resolved_config=config))

    planner_token = grant_capability(store, run_id, role="planner", phase="planning")
    ReviewAgentService(store, run_id).request(
        {
            "type": "focused_plan",
            "scope": {"item_ids": ["item-api"]},
        },
        capability_token=planner_token,
    )
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    store.save_run(run_id, run, expected_revision)

    provider = StubProvider()
    provider.script_turn(done_events(text="planner session start"))
    provider.script_turn(
        done_events(text="reviewer approve"),
        mutate_store=respond_review(
            store,
            run_id,
            {
                "loop_id": "review-focused-plan-01",
                "target_revision": 0,
                "finding_set_id": str(
                    store.load_review(run_id, "review-focused-plan-01").get(
                        "finding_set_id"
                    )
                    or ""
                ),
                "reported_findings": [],
                "review_completed": True,
                "summary": "clear",
            },
            phase="planning",
            loop_id="review-focused-plan-01",
        ),
    )
    provider.script_turn(done_events(signal="candidate_plan_ready", text="planning turn"))

    result = PlanningPhaseOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.phase == "whole_plan_review"
    review = store.load_review(run_id, "review-focused-plan-01")
    assert review["status"] == "approved"
    events = store.load_events(run_id)
    assert any(event["type"] == "reviewer_session_started" for event in events)
