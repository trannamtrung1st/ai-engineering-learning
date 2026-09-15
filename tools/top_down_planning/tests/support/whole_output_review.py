"""Shared whole-output review run fixtures for unit and integration tests."""

from __future__ import annotations

from core_tools.provider import StubProvider
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator.phases import WHOLE_OUTPUT_REVIEW
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.digests import compute_output_digest
from top_down_planning.persistence.session_bindings import update_primary_binding
from tests.helpers import (
    create_run_kwargs,
    done_events,
    ensure_plan_work_scope_contracts,
    plan_root_item,
    save_review_payload,
    whole_plan_approval_record,
)


def create_run_at_whole_output_review(
    store: FileRunStore,
    run_id: str = "run-20260101T000801-000801",
    *,
    limits: dict | None = None,
    provider: StubProvider | None = None,
    goal_assessment: str = "Output goal is fully met.",
) -> str | None:
    root = plan_root_item(
        title="Deliver the feature",
        outcome="Deliver the feature.",
    )
    leaf = PlanItem(
        id="item-leaf",
        parent_id="item-root",
        order_key="0000000000",
        title="Leaf",
        outcome="Leaf outcome.",
        kind="work",
    )
    plan = ensure_plan_work_scope_contracts(
        Plan(
            id=f"plan-{run_id}",
            revision=0,
            output_goal="Deliver the feature.",
            items={"item-root": root, "item-leaf": leaf},
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
            "whole_output_review": {
                "max_revision_cycles": 5,
            }
        },
    }
    if limits:
        config["limits"]["whole_output_review"].update(limits)

    production = {
        "revision": 2,
        "output_revision": 1,
        "batches": [
            {
                "id": "batch-01",
                "plan_items": ["item-leaf"],
                "status": "completed",
                "result": {
                    "outputs": [],
                    "contributions": [],
                    "dispositions": {"item-leaf": {"disposition": "completed"}},
                    "summary": "done",
                    "empty_output": False,
                    "goal_assessment": "",
                },
            }
        ],
        "dispositions": {"item-leaf": "completed"},
        "output_evidence": [],
        "completion_claim": {
            "goal_assessment": goal_assessment,
            "goal_met": True,
            "summary": "All items complete.",
            "plan_revision": 0,
            "output_revision": 1,
            "all_applicable_items_processed": True,
        },
    }

    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=config),
        phase=WHOLE_OUTPUT_REVIEW,
        production=production,
    )
    save_review_payload(
        store,
        run_id,
        whole_plan_approval_record(
            store,
            run_id,
            id="review-whole-plan-01",
            reviewer_session_id="stub-session-plan-reviewer",
        ),
    )

    session_id = None
    if provider is not None:
        provider.script_turn(done_events(text="turn complete"))
        session_id = provider.start_primary_session(
            "producer",
            {"run_id": run_id, "phase": WHOLE_OUTPUT_REVIEW},
        )
        list(provider.stream_events(session_id))

    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    digests = dict(run.get("digests") or {})
    digests["output"] = compute_output_digest(production)
    run["digests"] = digests
    sessions = dict(run["sessions"])
    if session_id is not None:
        sessions = update_primary_binding(
            sessions,
            role="producer",
            provider_session_id=session_id,
        )
    run["sessions"] = sessions
    store.save_run(run_id, run, expected_revision)
    save_review_payload(
        store,
        run_id,
        {
            "id": "review-whole-output-01",
            "type": "whole_output",
            "revise_at": "blocker",
            "target_revision": int(production["output_revision"]),
            "scope": {"kind": "whole_output"},
            "status": "pending",
            "findings": [],
            "revision_cycles": 0,
            "lifecycle_status": "review_pending",
            "scope_review_rounds": 0,
            "review_record_schema_version": 2,
            "review_contract_version": 2,
        },
    )
    return session_id
