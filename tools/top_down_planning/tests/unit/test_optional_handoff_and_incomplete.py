"""Optional handoff, finding_actions, challenge, and review_incomplete transitions."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.agent_tool import RequestError, ReviewAgentService
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.reviews import (
    ReviewFinding,
    ReviewLoop,
    advisory_handoff_allowed,
    apply_discovery_response,
    apply_owner_finding_actions,
    budgets_snapshot,
    mark_advisory_handoff_completed,
    needs_advisory_handoff,
    prepare_review_incomplete_retry,
)
from top_down_planning.orchestrator.failure import (
    apply_review_incomplete_run_transition,
    restore_run_after_review_incomplete,
)
from top_down_planning.persistence import FileRunStore
from top_down_planning.schema_docs import show_example, show_schema
from core_tools.schema import validate_against_schema
from tests.helpers import create_run_kwargs, grant_capability


def _finding(
    finding_id: str,
    *,
    severity: str = "minor",
    status: str = "unresolved",
) -> ReviewFinding:
    return ReviewFinding(
        id=finding_id,
        severity=severity,  # type: ignore[arg-type]
        category="correctness",
        target_refs=["item-root"],
        issue=f"Issue {finding_id}",
        recommended_change="Address",
        status=status,  # type: ignore[arg-type]
    )


def _optional_loop(**overrides: object) -> ReviewLoop:
    payload = {
        "id": "review-focused-plan-01",
        "type": "focused_plan",
        "reviewer_session_id": "sess",
        "target_revision": 0,
        "scope": {"kind": "focused_plan", "item_ids": ["item-root"]},
        "status": "pending",
        "revise_at": "blocker",
        "finding_set_id": "fs-01",
        "revision_cycles": 0,
        "findings": [_finding("finding-opt").to_dict()],
        "finding_actions": [],
    }
    payload.update(overrides)
    return ReviewLoop.from_dict(payload)  # type: ignore[arg-type]


def test_advisory_handoff_bounds_one_per_finding_set_id() -> None:
    loop = _optional_loop()
    assert needs_advisory_handoff(loop)
    assert advisory_handoff_allowed(loop)
    marked = mark_advisory_handoff_completed(loop)
    assert marked.advisory_handoffs_completed == ["fs-01"]
    assert not advisory_handoff_allowed(marked)


def test_required_finding_cannot_defer_or_accept() -> None:
    loop = _optional_loop(
        findings=[_finding("finding-req", severity="blocker").to_dict()],
    )
    with pytest.raises(ValueError, match="cannot use action 'defer'"):
        apply_owner_finding_actions(
            loop,
            [
                {
                    "finding_id": "finding-req",
                    "action": "defer",
                    "rationale": "nope",
                    "finding_set_id": "fs-01",
                }
            ],
            actor_role="planner",
            artifact_revision=0,
        )


def test_challenge_requires_proposed_disposition_and_keeps_finding_open() -> None:
    loop = _optional_loop()
    with pytest.raises(ValueError, match="proposed_disposition"):
        apply_owner_finding_actions(
            loop,
            [
                {
                    "finding_id": "finding-opt",
                    "action": "challenge",
                    "rationale": "Not applicable",
                    "finding_set_id": "fs-01",
                }
            ],
            actor_role="planner",
            artifact_revision=0,
        )

    updated, parsed = apply_owner_finding_actions(
        loop,
        [
            {
                "finding_id": "finding-opt",
                "action": "challenge",
                "rationale": "Not applicable",
                "proposed_disposition": "invalid",
                "finding_set_id": "fs-01",
            }
        ],
        actor_role="planner",
        artifact_revision=0,
    )
    assert parsed[0].proposed_disposition == "invalid"
    assert updated.findings[0].status == "unresolved"
    assert updated.status != "approved"


def test_defer_does_not_mutate_artifact_and_permits_approval() -> None:
    loop = _optional_loop(revision_cycles=2, scope_review_rounds=1)
    before = budgets_snapshot(loop)
    updated, _parsed = apply_owner_finding_actions(
        loop,
        [
            {
                "finding_id": "finding-opt",
                "action": "defer",
                "rationale": "Later",
                "finding_set_id": "fs-01",
            }
        ],
        actor_role="planner",
        artifact_revision=0,
    )
    assert budgets_snapshot(updated) == before
    assert updated.status == "approved"
    assert updated.findings[0].status == "unresolved"


def test_owner_cannot_set_invalid_or_superseded_via_actions() -> None:
    loop = _optional_loop()
    updated, _ = apply_owner_finding_actions(
        loop,
        [
            {
                "finding_id": "finding-opt",
                "action": "challenge",
                "rationale": "Duplicate",
                "proposed_disposition": "superseded",
                "superseded_by_finding_id": "finding-older",
                "finding_set_id": "fs-01",
            }
        ],
        actor_role="planner",
        artifact_revision=0,
    )
    assert updated.findings[0].status == "unresolved"
    assert updated.findings[0].status not in {"invalid", "superseded"}


def test_review_incomplete_preserves_budgets_and_reuses_finding_set_id() -> None:
    loop = ReviewLoop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=1,
        scope={"kind": "whole_plan"},
        status="pending",
        lifecycle_status="review_pending",
        revise_at="major",
        finding_set_id="fs-scope-01",
        revision_cycles=3,
        scope_review_rounds=2,
    )
    before = budgets_snapshot(loop)
    incomplete, _findings, outcome = apply_discovery_response(
        loop,
        {
            "finding_set_id": "fs-scope-01",
            "reported_findings": [],
            "review_completed": False,
            "summary": "artifact unreadable",
        },
        stage="initial_review",
    )
    assert outcome == "review_incomplete"
    assert budgets_snapshot(incomplete) == before
    assert incomplete.review_incomplete is not None
    retried = prepare_review_incomplete_retry(incomplete)
    assert retried.finding_set_id == "fs-scope-01"
    assert budgets_snapshot(retried) == before
    assert retried.status == "pending"
    assert retried.review_incomplete is not None  # cleared only on successful rediscovery

    completed, _, done = apply_discovery_response(
        incomplete,
        {
            "finding_set_id": "fs-scope-01",
            "reported_findings": [],
            "review_completed": True,
            "summary": "ok",
        },
        stage="initial_review",
    )
    assert done == "approved"
    assert completed.review_incomplete is None
    assert budgets_snapshot(completed) == before


def test_review_incomplete_run_transition_and_resume(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T000001-c0ff01"
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        outcome="Done.",
        kind="aggregate",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver.",
        items={"item-root": root},
    )
    store.create_run(run_id, plan=plan, **create_run_kwargs(tmp_path))
    loop = ReviewLoop(
        id="review-focused-plan-01",
        type="focused_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "focused_plan", "item_ids": ["item-root"]},
        status="review_incomplete",
        revise_at="blocker",
        finding_set_id="fs-01",
        review_incomplete={
            "stage": "discovery",
            "finding_set_id": "fs-01",
            "reason": "missing inputs",
        },
    )
    store.save_review(run_id, loop.to_dict())

    result = apply_review_incomplete_run_transition(
        store,
        run_id,
        loop_id=loop.id,
        reason="missing inputs",
        finding_set_id="fs-01",
        stage="discovery",
    )
    run = store.load_run(run_id)
    assert result["status"] == "failed"
    assert run["status"] == "failed"
    assert run.get("outcome") is None
    events = store.load_events(run_id)
    assert any(event.get("type") == "review_incomplete" for event in events)

    assert restore_run_after_review_incomplete(store, run_id) is True
    resumed = store.load_run(run_id)
    assert resumed["status"] == "running"
    assert resumed.get("outcome") is None


def test_review_service_incomplete_does_not_fail_run_for_focused(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T000001-d00d01"
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        outcome="Done.",
        kind="aggregate",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver.",
        items={"item-root": root},
    )
    store.create_run(run_id, plan=plan, **create_run_kwargs(tmp_path))
    loop = ReviewLoop(
        id="review-focused-plan-01",
        type="focused_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "focused_plan", "item_ids": ["item-root"]},
        status="pending",
        revise_at="blocker",
        finding_set_id="fs-01",
        revision_cycles=1,
    )
    store.save_review(run_id, loop.to_dict())
    token = grant_capability(
        store,
        run_id,
        role="reviewer",
        phase="planning",
        loop_id=loop.id,
        session_id="sess",
    )
    service = ReviewAgentService(store, run_id)
    response = service.respond(
        {
            "loop_id": loop.id,
            "target_revision": 0,
            "finding_set_id": "fs-01",
            "reported_findings": [],
            "review_completed": False,
            "summary": "cannot read package",
        },
        capability_token=token,
    )
    assert response["derived_outcome"] == "review_incomplete"
    run = store.load_run(run_id)
    assert run["status"] == "running"
    assert run.get("outcome") is None
    persisted = ReviewLoop.from_dict(store.load_review(run_id, loop.id))
    assert persisted.revision_cycles == 1
    assert persisted.review_incomplete is not None


def test_record_finding_actions_service_path(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T000001-ac7101"
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        outcome="Done.",
        kind="aggregate",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver.",
        items={"item-root": root},
    )
    store.create_run(run_id, plan=plan, **create_run_kwargs(tmp_path))
    run = store.load_run(run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["sessions"] = {
        **dict(run.get("sessions") or {}),
        "primary_planner_session_id": "planner-sess",
    }
    store.save_run(run_id, run, expected)

    loop = _optional_loop(status="pending")
    store.save_review(run_id, loop.to_dict())
    token = grant_capability(
        store,
        run_id,
        role="planner",
        phase="planning",
        session_id="planner-sess",
    )
    service = ReviewAgentService(store, run_id)
    response = service.record_finding_actions(
        {
            "loop_id": loop.id,
            "artifact_revision": 0,
            "finding_actions": [
                {
                    "finding_id": "finding-opt",
                    "action": "accept_as_is",
                    "actor_role": "planner",
                    "artifact_revision": 0,
                    "finding_set_id": "fs-01",
                    "rationale": "Accept for now",
                }
            ],
        },
        capability_token=token,
    )
    assert response["status"] == "approved"
    assert response["recorded_actions"][0]["action"] == "accept_as_is"

    with pytest.raises(RequestError, match="cannot use action 'defer'"):
        # Re-open a required finding path
        required_loop = _optional_loop(
            findings=[_finding("finding-req", severity="blocker").to_dict()],
            status="changes_requested",
        )
        store.save_review(run_id, required_loop.to_dict())
        service.record_finding_actions(
            {
                "loop_id": loop.id,
                "finding_actions": [
                    {
                        "finding_id": "finding-req",
                        "action": "defer",
                        "actor_role": "planner",
                        "artifact_revision": 0,
                        "finding_set_id": "fs-01",
                        "rationale": "bad",
                    }
                ],
            },
            capability_token=token,
        )


def test_record_actions_schema_and_example_validate() -> None:
    schema = show_schema("review-record-finding-actions")
    example = show_example("review-record-finding-actions")
    validate_against_schema(example["payload"], schema)
