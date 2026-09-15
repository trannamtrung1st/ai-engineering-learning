"""Shared whole-plan review run fixtures for unit and integration tests."""

from __future__ import annotations

from core_tools.provider import StubProvider
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator.phases import WHOLE_PLAN_REVIEW
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.session_bindings import update_primary_binding
from tests.helpers import (
    create_run_kwargs,
    done_events,
    ensure_plan_work_scope_contracts,
    plan_root_item,
    save_review_payload,
)


def create_run_at_whole_plan_review(
    store: FileRunStore,
    run_id: str = "run-20260101T000301-000301",
    *,
    limits: dict | None = None,
    provider: StubProvider | None = None,
) -> str | None:
    root = plan_root_item(
        title="Deliver the feature",
        outcome="Deliver the feature.",
    )
    api = PlanItem(
        id="item-api",
        parent_id="item-root",
        order_key="0000000000",
        title="API",
        outcome="API exists.",
        acceptance=["API behavior is verifiable."],
        kind="work",
    )
    plan = ensure_plan_work_scope_contracts(
        Plan(
            id=f"plan-{run_id}",
            revision=0,
            output_goal="Deliver the feature.",
            items={"item-root": root, "item-api": api},
        )
    )
    config = {
        "run": {
            "output_goal": "Deliver the feature.",
            "input_refs": ["README.md"],
        },
        "planning": {
            "stop_hint": "Stop when ready.",
            "max_depth": 4,
            "max_expansion_per_item": 7,
        },
        "limits": {
            "whole_plan_review": {
                "max_revision_cycles": 5,
            }
        },
    }
    if limits:
        for key, value in limits.items():
            existing = config["limits"].get(key)
            if isinstance(value, dict) and isinstance(existing, dict):
                existing.update(value)
            else:
                config["limits"][key] = value

    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=config),
        phase=WHOLE_PLAN_REVIEW,
    )
    session_id = None
    if provider is not None:
        provider.script_turn(done_events(text="turn complete"))
        session_id = provider.start_primary_session(
            "planner",
            {"run_id": run_id, "phase": WHOLE_PLAN_REVIEW},
        )
        list(provider.stream_events(session_id))
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run["revision"] = expected_revision + 1
    sessions = dict(run["sessions"])
    if session_id is not None:
        sessions = update_primary_binding(sessions, role="planner", provider_session_id=session_id)
    run["sessions"] = sessions
    store.save_run(run_id, run, expected_revision)
    from top_down_planning.domain.review_loop_factory import new_whole_plan_review_loop

    loop = new_whole_plan_review_loop(
        loop_id="review-whole-plan-01",
        target_revision=0,
        config=config,
    )
    save_review_payload(store, run_id, loop.to_dict())
    return session_id
