"""Observability fields and review audit events for severity-threshold reviews."""

from __future__ import annotations

from pathlib import Path

from top_down_planning.agent_tool.review_service import ReviewAgentService
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.reviews import ReviewFinding, ReviewLoop, policy_observability_fields
from top_down_planning.orchestrator.phases import WHOLE_PLAN_REVIEW
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.digests import compute_plan_digest
from tests.helpers import create_run_kwargs, grant_capability, minimal_resolved_config, make_review_loop


def test_policy_observability_includes_counts() -> None:
    findings = [
        ReviewFinding(
            id="f-major",
            severity="major",
            category="other",
            target_refs=["item-a"],
            issue="major",
            recommended_change="fix",
        ),
        ReviewFinding(
            id="f-minor",
            severity="minor",
            category="other",
            target_refs=["item-a"],
            issue="minor",
            recommended_change="optional",
        ),
    ]
    fields = policy_observability_fields(findings, [], "major")
    assert fields["required_open_finding_count"] == 1
    assert fields["optional_open_finding_count"] == 1
    assert fields["finding_count"] == 2


def test_review_respond_emits_observability_events(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T009901-009901"
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        outcome="Done.",
        kind="aggregate",
    )
    leaf = PlanItem(
        id="item-a",
        parent_id="item-root",
        order_key="0000000001",
        title="Leaf",
        outcome="Done.",
        kind="work",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver.",
        items={"item-root": root, "item-a": leaf},
    )
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
        phase=WHOLE_PLAN_REVIEW,
    )
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "whole_plan"},
        status="pending",
        lifecycle_status="review_pending",
        active_stage=None,
        finding_set_id="review-whole-plan-01-fs-01",
        revise_at="major",
    )
    store.save_review(run_id, loop.to_dict())
    token = grant_capability(
        store,
        run_id,
        role="reviewer",
        phase=WHOLE_PLAN_REVIEW,
        loop_id=loop.id,
        session_id="sess",
    )

    digest = compute_plan_digest(plan)
    response = ReviewAgentService(store, run_id).respond(
        {
            "loop_id": loop.id,
            "target_revision": 0,
            "stage": "initial_review",
            "finding_set_id": loop.finding_set_id,
            "reported_findings": [
                {
                    "id": "f-major",
                    "severity": "major",
                    "category": "other",
                    "target_refs": ["item-a"],
                    "issue": "gap",
                    "recommended_change": "fix",
                }
            ],
            "review_completed": True,
            "target_digest": digest,
            "summary": "Required finding.",
        },
        capability_token=token,
    )
    assert response["revise_at"] == "major"
    assert response["required_open_finding_count"] == 1
    assert response["required_open_finding_ids"] == ["f-major"]
    events = store.load_events(run_id)
    types = [event.get("type") for event in events]
    assert "review_responded" in types
    assert "review_findings_reported" in types
    assert "review_revision_required" in types
    findings_event = next(
        event for event in events if event.get("type") == "review_findings_reported"
    )
    assert "findings" not in findings_event
    assert findings_event["required_open_finding_count"] == 1
