"""Shared focused-review run builders for unit tests."""

from __future__ import annotations

from typing import Any

from pathlib import Path

from core_tools.provider import StubProvider
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.session_bindings import new_session_binding
from top_down_planning.orchestrator.phases import PLANNING, PRODUCTION
from top_down_planning.persistence import FileRunStore
from tests.helpers import (
    bind_evidence_snapshot,
    bind_focused_review_freshness,
    create_run_kwargs,
    done_events,
    plan_root_item,
    review_loop_dict_with_binding,
    save_review_payload,
    sessions_with_primary_session,
    whole_plan_approval_record,
)


def focused_plan_request(
    item_ids: list[str],
    store: FileRunStore | None = None,
    run_id: str = "run-20260101T000401-000401",
) -> dict[str, Any]:
    payload = {
        "type": "focused_plan",
        "scope": {
            "item_ids": item_ids,
        },
    }
    if store is None:
        return payload
    return bind_focused_review_freshness(store, run_id, payload)


def planning_config(
    *,
    limits: dict | None = None,
    review: dict | None = None,
) -> dict[str, Any]:
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
            "planning": {
                "max_items_added": 20,
                "max_agent_turns": 40,
            },
            "focused_plan_review": {
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
        focused_keys = {"max_revision_cycles_per_loop", "max_loops"}
        if focused_keys.intersection(limits):
            config["limits"]["focused_plan_review"].update(limits)
        else:
            for key, value in limits.items():
                existing = config["limits"].get(key)
                if isinstance(value, dict) and isinstance(existing, dict):
                    existing.update(value)
                else:
                    config["limits"][key] = value
    if review:
        config["review"].update(review)
    return config


def create_planning_run(
    store: FileRunStore,
    run_id: str = "run-20260101T000401-000401",
    *,
    limits: dict | None = None,
    review: dict | None = None,
) -> None:
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
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the feature.",
        items={"item-root": root, "item-api": api},
    )
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(
            store.root,
            resolved_config=planning_config(limits=limits, review=review),
        ),
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


def create_production_run_open_item_second(
    store: FileRunStore,
    provider: StubProvider,
    *,
    run_id: str = "run-20260101T000501-000501",
) -> str:
    """Production orchestration fixture: item-first completed, item-second open."""

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
        output_goal="Deliver the feature.",
        items={"item-root": root, "item-first": first, "item-second": second},
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
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=config),
        phase=PRODUCTION,
    )
    save_review_payload(store, run_id, whole_plan_approval_record(store, run_id))
    run = store.load_run(run_id)
    workspace = Path(str(run["workspace"]))
    artifacts = workspace / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "first.txt").write_text("v1", encoding="utf-8")
    (artifacts / "second.txt").write_text("v2", encoding="utf-8")
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
            "ref": "artifacts/first.txt",
            "media_type": "text/plain",
            "captured_at": "2026-01-01T00:00:00Z",
            "batch_id": "batch-01",
        },
        content=(artifacts / "first.txt").read_bytes(),
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
                        "summary": "Initial evidence.",
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

    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    provider.script_turn([*done_events(text="producer start")])
    session_id = provider.start_primary_session(
        "producer",
        {"run_id": run_id, "phase": PRODUCTION},
    )
    list(provider.stream_events(session_id))
    run["sessions"] = sessions_with_primary_session(
        producer=session_id,
        config=config,
        workspace=store.root,
    )
    store.save_run(run_id, run, expected_revision)
    return session_id


def focused_owner_revision_pending_loop(*, item_ids: list[str]) -> dict:
    binding = new_session_binding(
        role="reviewer",
        kind="reviewer",
    ).with_provider_session_id("ended-reviewer-session")
    loop = review_loop_dict_with_binding(
        {
            "id": "review-focused-output-01",
            "type": "focused_output",
            "target_revision": 1,
            "scope": {"kind": "focused_output", "item_ids": item_ids},
            "status": "pending",
            "revise_at": "blocker",
            "revision_cycles": 1,
            "finding_set_id": "fs-owner-revision-01",
            "findings": [
                {
                    "id": "finding-01",
                    "severity": "blocker",
                    "category": "correctness",
                    "target_refs": item_ids[:1],
                    "issue": "Need better evidence.",
                    "recommended_change": "Revise artifact.",
                    "status": "unresolved",
                }
            ],
        }
    )
    loop["reviewer_binding"] = binding.to_dict()
    return loop
