"""Tests for optional focused plan and output reviews."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from top_down_planning.agent_tool import RequestError, ReviewAgentService
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator import (
    PlanningPhaseOrchestrator,
    ProductionPhaseOrchestrator,
)
from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.orchestrator.focused_review import FocusedReviewOrchestrator
from top_down_planning.orchestrator.phases import PLANNING, PRODUCTION
from top_down_planning.persistence import FileRunStore
from core_tools.provider import StubProvider
from tests.helpers import (
    apply_plan,
    apply_production,
    create_run_kwargs,
    done_events,
    grant_capability,
    request_focused_review,
    respond_review,
    run_digests_for_config,
    save_review_payload,
    script_reviewer_allocate,
    sessions_with_primary_session,
    whole_plan_approval_record,
)


def _planning_config(*, limits: dict | None = None, review: dict | None = None) -> dict:
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
        "provider": {"name": "stub"},
    }
    if limits:
        config["limits"]["focused_plan_review"].update(limits)
    if review:
        config["review"].update(review)
    return config


def _create_planning_run(
    store: FileRunStore,
    run_id: str = "run-20260101T000401-000401",
    *,
    limits: dict | None = None,
    review: dict | None = None,
) -> None:
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        kind="aggregate",
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
            resolved_config=_planning_config(limits=limits, review=review),
        ),
    )


def _focused_plan_request(item_ids: list[str]) -> dict:
    return {
        "type": "focused_plan",
        "revise_at": "blocker",
        "scope": {
            "kind": "focused_plan",
            "item_ids": item_ids,
        },
    }


def _focused_verification_respond_request(
    store: FileRunStore,
    run_id: str,
    *,
    loop_id: str,
    target_revision: int,
    finding_results: list[dict] | None = None,
    decision: str = "verified",
) -> dict:
    from tests.helpers import mandatory_plan_digest

    loop_payload = store.load_review(run_id, loop_id)
    return {
        "loop_id": loop_id,
        "target_revision": target_revision,
        "stage": "finding_verification",
        "decision": decision,
        "finding_set_id": str(loop_payload.get("finding_set_id") or ""),
        "finding_results": finding_results or [],
        "new_direct_side_effect_findings": [],
        "target_digest": mandatory_plan_digest(store, run_id),
        "summary": "focused verification",
    }


def _review_respond_request(
    store: FileRunStore,
    run_id: str,
    *,
    loop_id: str,
    decision: str,
    target_revision: int = 0,
    findings: list[dict] | None = None,
) -> dict:
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
            severity = str(finding.get("severity") or "").strip()
            finding["severity"] = "blocker" if severity == "blocker" else "minor"
        if not str(finding.get("category") or "").strip():
            finding["category"] = "other"
        if "recommended_change" not in finding and "recommended_change" in finding:
            finding["recommended_change"] = finding["recommended_change"]
        reported.append(finding)
    return {
        "loop_id": loop_id,
        "target_revision": target_revision,
        "finding_set_id": finding_set_id,
        "reported_findings": reported,
        "review_completed": decision != "blocked",
        "summary": "focused review respond",
    }


def test_focused_plan_review_changes_then_approve_does_not_advance_phase(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    _create_planning_run(store)
    provider = StubProvider()

    run_id = "run-20260101T000401-000401"
    request_focused_review(
        store,
        run_id,
        _focused_plan_request(["item-api"]),
    )()
    respond_review(
        store,
        run_id,
        _review_respond_request(
            store,
            run_id,
            loop_id="review-focused-plan-01",
            decision="changes_requested",
            findings=[
                {
                    "id": "finding-01",
                    "severity": "blocker",
                    "category": "other",
                    "target_refs": ["item-api"],
                    "issue": "API outcome is too vague.",
                    "recommended_change": "Add concrete acceptance criteria.",
                    "status": "unresolved",
                }
            ],
        ),
        phase=PLANNING,
        loop_id="review-focused-plan-01",
    )()
    apply_plan(
        store,
        run_id,
        base_revision=0,
        operations=[
            {
                "op": "update_item",
                "item_id": "item-api",
                "patch": {
                    "outcome": "REST API endpoints exist.",
                    "acceptance": ["GET /health returns 200."],
                },
            }
        ],
    )()
    script_reviewer_allocate(provider)
    with pytest.raises(ProviderRunError, match="without a decision"):
        FocusedReviewOrchestrator(store, run_id, provider).run("review-focused-plan-01")
    provider.script_turn(
        done_events(text="reviewer verify"),
        mutate_store=respond_review(
            store,
            run_id,
            _focused_verification_respond_request(
                store,
                run_id,
                loop_id="review-focused-plan-01",
                target_revision=1,
                finding_results=[
                    {
                        "finding_id": "finding-01",
                        "disposition": "resolved",
                        "evidence": ["acceptance criteria added"],
                        "direct_side_effects": [],
                    }
                ],
            ),
            phase=PLANNING,
            loop_id="review-focused-plan-01",
        ),
    )
    assert FocusedReviewOrchestrator(store, run_id, provider).run(
        "review-focused-plan-01"
    ).ok
    provider.script_turn(done_events(signal="candidate_plan_ready", text="planning turn"))

    result = PlanningPhaseOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.phase == "whole_plan_review"

    review = store.load_review("run-20260101T000401-000401", "review-focused-plan-01")
    assert review["status"] == "verified"
    assert review["target_revision"] == 1

    run = store.load_run("run-20260101T000401-000401")
    assert run["phase"] == "whole_plan_review"
    assert run["status"] == "running"


def test_focused_plan_scope_violation_on_request_is_rejected(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_planning_run(store)
    service = ReviewAgentService(store, "run-20260101T000401-000401")
    token = grant_capability(store, "run-20260101T000401-000401", role="planner", phase=PLANNING)

    with pytest.raises(RequestError, match="whole scope kind"):
        service.request(
            {
                "type": "focused_plan",
                "revise_at": "blocker",
                "scope": {"kind": "whole_plan", "item_ids": ["item-api"]},
            },
            capability_token=token,
        )


def test_focused_plan_finding_outside_scope_is_rejected(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_planning_run(store)
    service = ReviewAgentService(store, "run-20260101T000401-000401")
    planner_token = grant_capability(store, "run-20260101T000401-000401", role="planner", phase=PLANNING)

    created = service.request(_focused_plan_request(["item-api"]), capability_token=planner_token)
    save_review_payload(store, "run-20260101T000401-000401", {
            **store.load_review("run-20260101T000401-000401", created["loop_id"]),
            "reviewer_session_id": "stub-session-reviewer",
        },
    )
    reviewer_token = grant_capability(
        store,
        "run-20260101T000401-000401",
        role="reviewer",
        phase=PLANNING,
        session_kind="reviewer",
        session_id="stub-session-reviewer",
        loop_id=created["loop_id"],
    )

    with pytest.raises(RequestError, match="outside declared scope"):
        service.respond(
            _review_respond_request(
                store,
                "run-20260101T000401-000401",
                loop_id=created["loop_id"],
                decision="changes_requested",
                findings=[
                    {
                        "id": "finding-01",
                        "severity": "blocker",
                        "target_refs": ["item-root"],
                        "issue": "Root needs work.",
                        "recommended_change": "Improve root.",
                        "status": "unresolved",
                    }
                ],
            ),
            capability_token=reviewer_token,
        )


def test_disabled_focused_plan_review_request_is_rejected(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_planning_run(
        store,
        review={
            "focused_plan": {"enabled": False},
        },
    )
    service = ReviewAgentService(store, "run-20260101T000401-000401")
    token = grant_capability(store, "run-20260101T000401-000401", role="planner", phase=PLANNING)

    with pytest.raises(RequestError, match="disabled in config"):
        service.request(_focused_plan_request(["item-api"]), capability_token=token)


def test_focused_plan_loop_limit_is_enforced(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_planning_run(store, limits={"max_loops": 1})
    service = ReviewAgentService(store, "run-20260101T000401-000401")
    token = grant_capability(store, "run-20260101T000401-000401", role="planner", phase=PLANNING)

    created = service.request(_focused_plan_request(["item-api"]), capability_token=token)
    save_review_payload(store, "run-20260101T000401-000401", {
            **store.load_review("run-20260101T000401-000401", created["loop_id"]),
            "status": "approved",
        },
    )
    with pytest.raises(RequestError, match="max_loops"):
        service.request(_focused_plan_request(["item-root"]), capability_token=token)


def test_overlapping_active_focused_plan_request_is_rejected(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_planning_run(store)
    service = ReviewAgentService(store, "run-20260101T000401-000401")
    token = grant_capability(store, "run-20260101T000401-000401", role="planner", phase=PLANNING)

    created = service.request(_focused_plan_request(["item-api"]), capability_token=token)
    with pytest.raises(RequestError, match="overlapping scope"):
        service.request(_focused_plan_request(["item-api"]), capability_token=token)

    review = store.load_review("run-20260101T000401-000401", created["loop_id"])
    assert review["status"] == "pending"


def test_focused_plan_revision_cycle_limit_does_not_accept_loop(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_planning_run(store, limits={"max_revision_cycles_per_loop": 1})
    provider = StubProvider()

    created = ReviewAgentService(store, "run-20260101T000401-000401").request(
        _focused_plan_request(["item-api"]),
        capability_token=grant_capability(store, "run-20260101T000401-000401", role="planner", phase=PLANNING),
    )
    loop_id = created["loop_id"]

    provider.script_turn([*done_events(text="planner start")])
    planner_session_id = provider.start_primary_session(
        "planner",
        {"run_id": "run-20260101T000401-000401", "phase": PLANNING},
    )
    list(provider.stream_events(planner_session_id))
    run = store.load_run("run-20260101T000401-000401")
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["sessions"] = sessions_with_primary_session(planner=planner_session_id)
    store.save_run("run-20260101T000401-000401", run, expected_revision)

    script_reviewer_allocate(provider)
    provider.script_turn(
        done_events(text="reviewer turn"),
        mutate_store=respond_review(
            store,
            "run-20260101T000401-000401",
            _review_respond_request(
                store,
                "run-20260101T000401-000401",
                loop_id=loop_id,
                decision="changes_requested",
                findings=[
                    {
                        "id": "finding-01",
                        "severity": "blocker",
                        "target_refs": ["item-api"],
                        "issue": "Needs work.",
                        "recommended_change": "Improve acceptance.",
                        "status": "unresolved",
                    }
                ],
            ),
            phase=PLANNING,
            loop_id=loop_id,
        ),
    )
    provider.script_session_turn(
        planner_session_id,
        done_events(text="planner revision"),
        mutate_store=apply_plan(
            store,
            "run-20260101T000401-000401",
            base_revision=0,
            operations=[
                {
                    "op": "update_item",
                    "item_id": "item-api",
                    "patch": {"outcome": "REST API endpoints exist."},
                }
            ],
        ),
    )
    script_reviewer_allocate(provider)
    provider.script_turn(
        done_events(text="reviewer verify"),
        mutate_store=lambda: respond_review(
            store,
            "run-20260101T000401-000401",
            _focused_verification_respond_request(
                store,
                "run-20260101T000401-000401",
                loop_id=loop_id,
                target_revision=1,
                decision="needs_revision",
                finding_results=[
                    {
                        "finding_id": "finding-01",
                        "disposition": "unresolved",
                        "evidence": ["still insufficient"],
                        "direct_side_effects": [],
                    }
                ],
            ),
            phase=PLANNING,
            loop_id=loop_id,
        ),
    )

    result = FocusedReviewOrchestrator(store, "run-20260101T000401-000401", provider).run(loop_id)

    assert result.ok is False
    review = store.load_review("run-20260101T000401-000401", loop_id)
    assert review["status"] == "blocked"
    run = store.load_run("run-20260101T000401-000401")
    assert run["phase"] == PLANNING


def _create_production_run(
    store: FileRunStore,
    run_id: str = "run-20260101T000501-000501",
    *,
    limits: dict | None = None,
    review: dict | None = None,
    provider: StubProvider | None = None,
) -> str:
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
        "provider": {"name": "stub"},
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
    run["sessions"] = sessions_with_primary_session(producer=session_id)
    store.save_run(run_id, run, expected_revision)
    return session_id


def test_focused_output_approval_does_not_enter_whole_output_review(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    producer_session_id = _create_production_run(store, provider=provider)
    run_id = "run-20260101T000501-000501"
    provider.script_session_turn(
        producer_session_id,
        done_events(text="after review request"),
        mutate_store=request_focused_review(
            store,
            run_id,
            {
                "type": "focused_output",
                "revise_at": "blocker",
                "scope": {
                    "kind": "focused_output",
                    "item_ids": ["item-first"],
                },
            },
            role="producer",
            phase=PRODUCTION,
        ),
    )
    script_reviewer_allocate(provider)
    provider.script_turn(
        done_events(text="reviewer approve"),
        mutate_store=respond_review(
            store,
            run_id,
            _review_respond_request(
                store,
                run_id,
                loop_id="review-focused-output-01",
                decision="approved",
            ),
            phase=PRODUCTION,
            loop_id="review-focused-output-01",
        ),
    )
    provider.script_session_turn(
        producer_session_id,
        done_events(signal="batch_complete", text="production turn"),
        mutate_store=apply_production(
            store,
            run_id,
            {
                "production_revision": 0,
                "plan_items": ["item-first"],
                "dispositions": {"item-first": {"disposition": "completed"}},
                "outputs": [],
                "contributions": [],
                "summary": "batch complete",
                "empty_output": False,
            },
            handler="apply",
        ),
    )
    provider.script_session_turn(
        producer_session_id,
        done_events(signal="batch_complete", text="production turn"),
        mutate_store=apply_production(
            store,
            run_id,
            {"goal_assessment": "Output goal is fully met.", "goal_met": True},
            handler="submit_completion",
        ),
    )

    result = ProductionPhaseOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.phase == "whole_output_review"
    run = store.load_run("run-20260101T000501-000501")
    assert run["phase"] == "whole_output_review"


def test_blocking_focused_output_findings_prevent_production_apply(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    producer_session_id = _create_production_run(store, provider=provider)

    save_review_payload(store, "run-20260101T000501-000501", {
            "id": "review-focused-output-01",
            "type": "focused_output",
            "revise_at": "blocker",
            "reviewer_session_id": "stub-session-reviewer",
            "target_revision": 0,
            "scope": {"kind": "focused_output", "item_ids": ["item-first"]},
            "status": "changes_requested",
            "findings": [
                {
                    "id": "finding-01",
                    "severity": "blocker",
                    "target_refs": ["item-first"],
                    "issue": "Output incomplete.",
                    "recommended_change": "Add evidence.",
                    "status": "unresolved",
                }
            ],
            "revision_cycles": 1,
        },
    )

    provider.script_session_turn(
        producer_session_id,
        done_events(signal="batch_complete", text="production turn"),
        mutate_store=apply_production(
            store,
            "run-20260101T000501-000501",
            {
                "production_revision": 0,
                "plan_items": ["item-first"],
                "dispositions": {"item-first": {"disposition": "completed"}},
                "outputs": [],
                "contributions": [],
                "summary": "batch complete",
                "empty_output": False,
            },
            handler="apply",
        ),
    )

    with pytest.raises(RequestError, match="focused output findings"):
        ProductionPhaseOrchestrator(store, "run-20260101T000501-000501", provider).run()
