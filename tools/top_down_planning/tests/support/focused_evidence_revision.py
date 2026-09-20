"""Shared run builders for focused-output evidence_revision tests."""

from __future__ import annotations

from pathlib import Path

from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator.phases import PRODUCTION
from top_down_planning.persistence import FileRunStore
from tests.helpers import (
    bind_evidence_snapshot,
    create_run_kwargs,
    save_review_payload,
    whole_plan_approval_record,
)


def create_focused_evidence_test_run(
    store: FileRunStore,
    run_id: str = "run-20260101T000551-000551",
) -> None:
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        kind="aggregate",
    )
    first = PlanItem(
        id="item-first",
        parent_id="item-root",
        order_key="0000000000",
        title="First",
        outcome="First outcome.",
        kind="work",
    )
    second = PlanItem(
        id="item-second",
        parent_id="item-root",
        order_key="0000000100",
        title="Second",
        outcome="Second outcome.",
        kind="work",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver.",
        items={"item-root": root, "item-first": first, "item-second": second},
    )
    config = {
        "run": {"output_goal": "Deliver.", "input_refs": ["README.md"]},
        "planning": {
            "stop_hint": "Stop.",
            "max_depth": 4,
            "max_expansion_per_item": 7,
        },
        "limits": {"production": {"max_batches": 50, "max_agent_turns_per_batch": 10}},
    }
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=config),
        phase=PRODUCTION,
    )
    save_review_payload(store, run_id, whole_plan_approval_record(store, run_id))
    run = store.load_run(run_id)
    workspace = Path(str(run["workspace"]))
    (workspace / "first.txt").write_text("1\n", encoding="utf-8")
    production = store.load_production(run_id)
    expected = int(production["revision"])
    production = dict(production)
    production["revision"] = expected + 1
    production["output_revision"] = 1
    production["dispositions"] = {
        "item-first": "completed",
        "item-second": "completed",
    }
    output_evidence, nested_output = bind_evidence_snapshot(
        store,
        run_id,
        {
            "id": "output-first",
            "type": "artifact",
            "ref": "first.txt",
            "media_type": "text/plain",
            "captured_at": "2026-01-01T00:00:00Z",
            "batch_id": "batch-01",
        },
        content=(workspace / "first.txt").read_bytes(),
    )
    production["batches"] = [
        {
            "id": "batch-01",
            "plan_items": ["item-first", "item-second"],
            "status": "completed",
            "result": {
                "outputs": [nested_output],
                "contributions": [
                    {
                        "item_id": "item-first",
                        "output_refs": ["output-first"],
                        "summary": "initial",
                    }
                ],
                "dispositions": {
                    "item-first": {"disposition": "completed", "evidence": "initial"},
                    "item-second": {"disposition": "completed", "evidence": "initial"},
                },
                "summary": "initial",
            },
        }
    ]
    production["output_evidence"] = [output_evidence]
    production["completion_claim"] = {
        "goal_assessment": "done",
        "goal_met": True,
        "summary": "",
        "plan_revision": 0,
        "output_revision": 1,
        "all_applicable_items_processed": True,
    }
    store.save_production(run_id, production, expected)


def create_agent_focused_test_run_open_item_second(
    store: FileRunStore,
    run_id: str = "run-20260101T000551-000551",
) -> None:
    """Agent-service fixture: item-first completed, item-second still open."""

    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        kind="aggregate",
    )
    first = PlanItem(
        id="item-first",
        parent_id="item-root",
        order_key="0000000000",
        title="First",
        outcome="First outcome.",
        kind="work",
    )
    second = PlanItem(
        id="item-second",
        parent_id="item-root",
        order_key="0000000100",
        title="Second",
        outcome="Second outcome.",
        kind="work",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver.",
        items={"item-root": root, "item-first": first, "item-second": second},
    )
    config = {
        "run": {"output_goal": "Deliver.", "input_refs": ["README.md"]},
        "planning": {
            "stop_hint": "Stop.",
            "max_depth": 4,
            "max_expansion_per_item": 7,
        },
        "limits": {"production": {"max_batches": 50, "max_agent_turns_per_batch": 10}},
    }
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=config),
        phase=PRODUCTION,
    )
    save_review_payload(store, run_id, whole_plan_approval_record(store, run_id))
    run = store.load_run(run_id)
    workspace = Path(str(run["workspace"]))
    (workspace / "first.txt").write_text("1\n", encoding="utf-8")
    (workspace / "second.txt").write_text("2\n", encoding="utf-8")
    production = store.load_production(run_id)
    expected = int(production["revision"])
    production = dict(production)
    production["revision"] = expected + 1
    production["output_revision"] = 1
    production["dispositions"] = {"item-first": "completed"}
    output_evidence, nested_output = bind_evidence_snapshot(
        store,
        run_id,
        {
            "id": "output-first",
            "type": "artifact",
            "ref": "first.txt",
            "media_type": "text/plain",
            "captured_at": "2026-01-01T00:00:00Z",
            "batch_id": "batch-01",
        },
        content=(workspace / "first.txt").read_bytes(),
    )
    production["batches"] = [
        {
            "id": "batch-01",
            "plan_items": ["item-first"],
            "status": "completed",
            "result": {
                "outputs": [nested_output],
                "contributions": [
                    {
                        "item_id": "item-first",
                        "output_refs": ["output-first"],
                        "summary": "initial",
                    }
                ],
                "dispositions": {
                    "item-first": {"disposition": "completed", "evidence": "initial"},
                },
                "summary": "initial",
            },
        }
    ]
    production["output_evidence"] = [output_evidence]
    store.save_production(run_id, production, expected)


def focused_output_review_payload(
    *,
    item_ids: list[str],
    status: str = "changes_requested",
) -> dict:
    return {
        "id": "review-focused-output-01",
        "type": "focused_output",
        "revise_at": "blocker",
        "reviewer_session_id": "stub-session-reviewer",
        "target_revision": 1,
        "scope": {"kind": "focused_output", "item_ids": item_ids},
        "status": status,
        "findings": [
            {
                "id": "finding-01",
                "severity": "blocker",
                "category": "correctness",
                "target_refs": item_ids[:1],
                "issue": "Need better evidence.",
                "recommended_change": "Add revised artifact.",
                "status": "unresolved",
            }
        ],
        "revision_cycles": 1,
    }
