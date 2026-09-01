"""Shared focused-review run builders for unit tests."""

from __future__ import annotations

from typing import Any

from core_tools.provider import StubProvider
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator.phases import PRODUCTION
from top_down_planning.persistence import FileRunStore
from tests.helpers import (
    create_run_kwargs,
    done_events,
    plan_root_item,
    save_review_payload,
    sessions_with_primary_session,
    whole_plan_approval_record,
)


def review_respond_request(
    store: FileRunStore,
    run_id: str,
    *,
    loop_id: str,
    decision: str,
    target_revision: int = 0,
    findings: list[dict] | None = None,
) -> dict[str, Any]:
    loop_payload: dict[str, Any] | None = None
    try:
        loop_payload = store.load_review(run_id, loop_id)
    except Exception:
        loop_payload = None
    finding_set_id = (
        str(loop_payload.get("finding_set_id") or "")
        if loop_payload is not None
        else f"{loop_id}-fs-01"
    )
    reported: list[dict] = []
    for item in findings or []:
        finding = dict(item)
        if not str(finding.get("severity") or "").strip():
            finding["severity"] = "minor"
        if not str(finding.get("category") or "").strip():
            raise ValueError("focused review test findings require category")
        reported.append(finding)
    return {
        "loop_id": loop_id,
        "target_revision": target_revision,
        "finding_set_id": finding_set_id,
        "reported_findings": reported,
        "review_completed": decision != "blocked",
        "summary": "focused review respond",
    }


def create_production_run(
    store: FileRunStore,
    run_id: str = "run-20260101T000501-000501",
    *,
    limits: dict | None = None,
    review: dict | None = None,
    provider: StubProvider | None = None,
) -> str:
    root = plan_root_item(
        title="Deliver the feature",
        outcome="Deliver the feature.",
    )
    first = PlanItem(
        id="item-first",
        parent_id="item-root",
        order_key="0000000000",
        title="First",
        outcome="First outcome.",
        kind="work",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the feature.",
        items={"item-root": root, "item-first": first},
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
            "production": {
                "max_batches": 50,
                "max_agent_turns_per_batch": 10,
            },
            "focused_output_review": {
                "max_loops": 5,
                "max_revision_cycles_per_loop": 3,
            },
        },
        "review": {
            "focused_plan": {"enabled": True},
            "focused_output": {"enabled": True},
        },
    }
    if limits:
        config["limits"]["focused_output_review"].update(limits)
    if review:
        config["review"].update(review)

    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=config),
        phase=PRODUCTION,
    )
    save_review_payload(store, run_id, whole_plan_approval_record(store, run_id))
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    if provider is not None:
        provider.script_turn([*done_events(text="producer start")])
        session_id = provider.start_primary_session(
            "producer",
            {"run_id": run_id, "phase": PRODUCTION},
        )
        list(provider.stream_events(session_id))
    else:
        session_id = "stub-session-producer"
    run["sessions"] = sessions_with_primary_session(
        producer=session_id,
        config=config,
        workspace=store.root,
    )
    store.save_run(run_id, run, expected_revision)
    return session_id
