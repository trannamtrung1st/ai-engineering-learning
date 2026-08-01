"""Discovery merge rules and service-derived lifecycle outcomes."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.agent_tool import RequestError, ReviewAgentService
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.reviews import (
    FindingAction,
    ReviewFinding,
    ReviewLoop,
    apply_discovery_response,
    derive_discovery_outcome,
    map_discovery_outcome_to_loop_status,
    merge_discovery_findings,
)
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, grant_capability, make_review_loop


def _finding(
    finding_id: str,
    *,
    severity: str = "major",
    status: str = "unresolved",
) -> ReviewFinding:
    return ReviewFinding(
        id=finding_id,
        severity=severity,  # type: ignore[arg-type]
        category="correctness",
        target_refs=["item-root"],
        issue=f"Issue {finding_id}",
        recommended_change="Fix it",
        status=status,  # type: ignore[arg-type]
    )


def test_merge_discovery_findings_is_append_only() -> None:
    prior = _finding("finding-001", severity="blocker", status="resolved")
    loop = make_review_loop(
        id="review-focused-plan-01",
        type="focused_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "focused_plan", "item_ids": ["item-root"]},
        findings=[prior],
        revise_at="blocker",
        finding_set_id="fs-01",
    )
    reported = [_finding("finding-002", severity="minor")]
    merged = merge_discovery_findings(loop, reported)
    assert [item.id for item in merged] == ["finding-001", "finding-002"]
    assert merged[0].status == "resolved"


def test_derive_outcomes_for_incomplete_required_optional_and_clear() -> None:
    required = [_finding("finding-req", severity="blocker")]
    optional = [_finding("finding-opt", severity="minor")]
    assert (
        derive_discovery_outcome(
            required,
            [],
            "blocker",
            review_completed=False,
        )
        == "review_incomplete"
    )
    assert (
        derive_discovery_outcome(
            required,
            [],
            "blocker",
            review_completed=True,
        )
        == "changes_requested"
    )
    assert (
        derive_discovery_outcome(
            optional,
            [],
            "blocker",
            review_completed=True,
        )
        == "pending"
    )
    assert (
        derive_discovery_outcome(
            optional,
            [
                FindingAction(
                    finding_id="finding-opt",
                    action="defer",
                    actor_role="planner",
                    artifact_revision=0,
                    finding_set_id="fs-01",
                    rationale="Later",
                )
            ],
            "blocker",
            review_completed=True,
        )
        == "approved"
    )
    assert (
        derive_discovery_outcome(
            optional,
            [
                FindingAction(
                    finding_id="finding-opt",
                    action="fix",
                    actor_role="planner",
                    artifact_revision=0,
                    finding_set_id="fs-01",
                )
            ],
            "blocker",
            review_completed=True,
        )
        == "changes_requested"
    )
    assert (
        derive_discovery_outcome(
            optional,
            [
                FindingAction(
                    finding_id="finding-opt",
                    action="challenge",
                    actor_role="planner",
                    artifact_revision=0,
                    finding_set_id="fs-01",
                    rationale="Not applicable",
                    proposed_disposition="invalid",
                )
            ],
            "blocker",
            review_completed=True,
        )
        == "changes_requested"
    )
    assert (
        derive_discovery_outcome([], [], "blocker", review_completed=True)
        == "approved"
    )


def test_apply_discovery_persists_finding_actions_and_incomplete_marker() -> None:
    loop = make_review_loop(
        id="review-focused-plan-01",
        type="focused_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "focused_plan", "item_ids": ["item-root"]},
        revise_at="blocker",
        finding_set_id="fs-01",
    )
    updated, findings, outcome = apply_discovery_response(
        loop,
        {
            "finding_set_id": "fs-01",
            "reported_findings": [
                {
                    "id": "finding-opt",
                    "severity": "minor",
                    "category": "correctness",
                    "target_refs": ["item-root"],
                    "issue": "Style",
                    "recommended_change": "Optional polish",
                    "status": "unresolved",
                }
            ],
            "finding_actions": [
                {
                    "finding_id": "finding-opt",
                    "action": "defer",
                    "actor_role": "planner",
                    "artifact_revision": 0,
                    "rationale": "Defer polish",
                    "finding_set_id": "fs-01",
                }
            ],
            "review_completed": True,
            "summary": "optional only",
        },
    )
    assert outcome == "approved"
    assert [item.id for item in findings] == ["finding-opt"]
    assert updated.finding_actions[0].action == "defer"
    assert updated.review_incomplete is None

    incomplete, _, incomplete_outcome = apply_discovery_response(
        loop,
        {
            "finding_set_id": "fs-01",
            "reported_findings": [],
            "review_completed": False,
            "summary": "missing inputs",
        },
    )
    assert incomplete_outcome == "review_incomplete"
    assert incomplete.status == "review_incomplete"
    assert incomplete.review_incomplete is not None
    assert incomplete.review_incomplete["reason"] == "missing inputs"


def test_legacy_severity_findings_remain_readable_after_merge() -> None:
    loop = make_review_loop(
        id="review-focused-plan-01",
        type="focused_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "focused_plan", "item_ids": ["item-root"]},
        revise_at="blocker",
        finding_set_id="fs-01",
        findings=[
            ReviewFinding.from_dict(
                {
                    "id": "legacy-1",
                    "severity": "blocker",
                    "category": "correctness",
                    "target_refs": ["item-root"],
                    "issue": "Legacy blocker",
                    "recommended_change": "Fix",
                    "status": "resolved",
                }
            )
        ],
    )
    updated, findings, outcome = apply_discovery_response(
        loop,
        {
            "finding_set_id": "fs-01",
            "reported_findings": [
                {
                    "id": "finding-new",
                    "severity": "minor",
                    "category": "other",
                    "target_refs": ["item-root"],
                    "issue": "New optional",
                    "recommended_change": "Optional",
                    "status": "unresolved",
                }
            ],
            "review_completed": True,
            "summary": "ok",
        },
    )
    assert outcome == "pending"
    assert findings[0].severity == "blocker"
    assert findings[0].severity == "blocker"
    assert findings[0].recommended_change == "Fix"
    assert updated.findings[0].id == "legacy-1"
    assert updated.status == "advisory_pending"


def test_block_review_yields_blocked_outcome_and_status() -> None:
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "whole_plan"},
        status="pending",
        active_stage="scope_review",
        finding_set_id="fs-1",
        findings=[],
        revise_at="blocker",
    )
    updated, findings, outcome = apply_discovery_response(
        loop,
        {
            "finding_set_id": "fs-1",
            "reported_findings": [],
            "review_completed": False,
            "block_review": True,
            "summary": "Cannot complete scope review.",
        },
        stage="scope_review",
    )
    assert outcome == "blocked"
    assert updated.status == "blocked"
    assert map_discovery_outcome_to_loop_status(outcome, stage="scope_review") == "blocked"
    assert findings == []


def _seed_focused_run(tmp_path: Path) -> tuple[FileRunStore, str, ReviewLoop, str]:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T000001-a1b2c3"
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
    loop = make_review_loop(
        id="review-focused-plan-01",
        type="focused_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "focused_plan", "item_ids": ["item-root"]},
        status="pending",
        revise_at="blocker",
        finding_set_id="review-focused-plan-01-fs-01",
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
    return store, run_id, loop, token


def test_review_service_derives_changes_requested_from_discovery(
    tmp_path: Path,
) -> None:
    store, run_id, loop, token = _seed_focused_run(tmp_path)
    service = ReviewAgentService(store, run_id)
    response = service.respond(
        {
            "loop_id": loop.id,
            "target_revision": 0,
            "finding_set_id": loop.finding_set_id,
            "reported_findings": [
                {
                    "id": "finding-001",
                    "severity": "blocker",
                    "category": "correctness",
                    "target_refs": ["item-root"],
                    "issue": "Broken",
                    "recommended_change": "Repair",
                    "status": "unresolved",
                }
            ],
            "review_completed": True,
            "summary": "required open",
        },
        capability_token=token,
    )
    assert response["derived_outcome"] == "changes_requested"
    assert response["status"] == "changes_requested"
    assert response["decision"] == "changes_requested"
    persisted = ReviewLoop.from_dict(store.load_review(run_id, loop.id))
    assert [item.id for item in persisted.findings] == ["finding-001"]


def test_review_service_rejects_legacy_decision_path(tmp_path: Path) -> None:
    store, run_id, loop, token = _seed_focused_run(tmp_path)
    service = ReviewAgentService(store, run_id)
    with pytest.raises(RequestError, match="discovery contract"):
        service.respond(
            {
                "loop_id": loop.id,
                "target_revision": 0,
                "decision": "changes_requested",
                "findings": [
                    {
                        "id": "finding-legacy",
                        "severity": "blocker",
                        "category": "correctness",
                        "target_refs": ["item-root"],
                        "issue": "Legacy path",
                        "recommended_change": "Fix",
                        "status": "unresolved",
                    }
                ],
                "summary": "legacy",
            },
            capability_token=token,
        )


def test_review_service_rejects_reused_finding_id_on_merge(tmp_path: Path) -> None:
    store, run_id, loop, token = _seed_focused_run(tmp_path)
    existing = loop.to_dict()
    existing["findings"] = [
        _finding("finding-001", severity="blocker", status="resolved").to_dict()
    ]
    store.save_review(run_id, existing)
    service = ReviewAgentService(store, run_id)
    with pytest.raises(RequestError, match="already exists"):
        service.respond(
            {
                "loop_id": loop.id,
                "target_revision": 0,
                "finding_set_id": loop.finding_set_id,
                "reported_findings": [
                    {
                        "id": "finding-001",
                        "severity": "major",
                        "category": "correctness",
                        "target_refs": ["item-root"],
                        "issue": "Reuse",
                        "recommended_change": "No",
                        "status": "unresolved",
                    }
                ],
                "review_completed": True,
                "summary": "bad",
            },
            capability_token=token,
        )
