"""Tests for discovery respond contract and finding_set_id allocation."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.agent_tool import RequestError, ReviewAgentService
from top_down_planning.domain.reviews import (
    ReviewFinding,
    ReviewLoop,
    allocate_discovery_finding_set_id,
    parse_discovery_respond_findings,
    parse_reported_finding,
)
from top_down_planning.orchestrator.focused_review import build_focused_review_package
from top_down_planning.persistence import FileRunStore
from top_down_planning.schema_docs import show_example, show_schema
from core_tools.schema import validate_against_schema
from tests.helpers import create_run_kwargs, grant_capability, review_loop_dict_with_binding, save_review_payload


def _loop(**overrides: object) -> ReviewLoop:
    payload = review_loop_dict_with_binding(
        {
        "id": "review-focused-plan-01",
        "type": "focused_plan",
        "reviewer_session_id": "sess",
        "target_revision": 0,
        "scope": {"kind": "focused_plan", "item_ids": ["item-api"]},
        "status": "pending",
        "revise_at": "blocker",
        "finding_set_id": "review-focused-plan-01-fs-01",
        "findings": [],
        }
    )
    payload.update(overrides)
    return ReviewLoop.from_dict(payload)  # type: ignore[arg-type]


def test_allocate_finding_set_id_for_fresh_discovery() -> None:
    loop = _loop(finding_set_id=None)
    updated, finding_set_id = allocate_discovery_finding_set_id(loop)
    assert finding_set_id == "review-focused-plan-01-fs-01"
    assert updated.finding_set_id == finding_set_id


def test_allocate_reuses_id_when_review_incomplete() -> None:
    loop = _loop(
        finding_set_id="review-focused-plan-01-fs-02",
        review_incomplete={"reason": "missing inputs"},
    )
    updated, finding_set_id = allocate_discovery_finding_set_id(loop)
    assert finding_set_id == "review-focused-plan-01-fs-02"
    assert updated is loop


def test_echo_mismatch_rejected() -> None:
    loop = _loop()
    with pytest.raises(ValueError, match="finding_set_id mismatch"):
        parse_discovery_respond_findings(
            loop,
            {
                "finding_set_id": "wrong-id",
                "reported_findings": [],
                "review_completed": True,
                "summary": "ok",
            },
        )


def test_reused_finding_id_rejected() -> None:
    loop = _loop(
        findings=[
            ReviewFinding(
                id="finding-001",
                severity="blocker",
                category="correctness",
                target_refs=["item-api"],
                issue="Old",
                recommended_change="Fix",
                status="resolved",
            ).to_dict()
        ]
    )
    with pytest.raises(ValueError, match="already exists"):
        parse_discovery_respond_findings(
            loop,
            {
                "finding_set_id": "review-focused-plan-01-fs-01",
                "reported_findings": [
                    {
                        "id": "finding-001",
                        "severity": "major",
                        "category": "correctness",
                        "target_refs": ["item-api"],
                        "issue": "Again",
                        "recommended_change": "Fix",
                        "status": "unresolved",
                    }
                ],
                "review_completed": True,
                "summary": "reuse",
            },
        )


def test_missing_severity_or_category_rejected() -> None:
    with pytest.raises(ValueError, match="requires severity"):
        parse_reported_finding(
            {
                "id": "f-1",
                "category": "other",
                "target_refs": [],
                "issue": "x",
                "recommended_change": "y",
            }
        )
    with pytest.raises(ValueError, match="requires category"):
        parse_reported_finding(
            {
                "id": "f-1",
                "severity": "minor",
                "target_refs": [],
                "issue": "x",
                "recommended_change": "y",
            }
        )


def test_discovery_examples_validate_against_schema() -> None:
    schema = show_schema("review-respond")
    for name in ("review-respond", "review-respond-initial"):
        example = show_example(name)
        issues = validate_against_schema(example["payload"], schema)
        assert issues == [], f"{name}: {issues}"


def test_focused_package_includes_allocated_finding_set_id(tmp_path: Path) -> None:
    from top_down_planning.domain.models import Plan, PlanItem

    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T000001-d15c01"
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
    config = store.load_resolved_config(run_id)
    run = store.load_run(run_id)
    loop, finding_set_id = allocate_discovery_finding_set_id(
        ReviewLoop(
            id="review-focused-plan-01",
            type="focused_plan",
            reviewer_session_id=None,
            target_revision=0,
            scope={"kind": "focused_plan", "item_ids": ["item-root"]},
            revise_at="blocker",
        )
    )
    package = build_focused_review_package(
        run_id, run, config, loop, plan=plan
    )
    assert package["finding_set_id"] == finding_set_id


def test_review_service_rejects_finding_set_id_mismatch(tmp_path: Path) -> None:
    from top_down_planning.domain.models import Plan, PlanItem

    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T000001-d15c02"
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
        finding_set_id="review-focused-plan-01-fs-01",
    )
    save_review_payload(store, run_id, loop.to_dict())
    service = ReviewAgentService(store, run_id)
    token = grant_capability(
        store,
        run_id,
        role="reviewer",
        phase="planning",
        loop_id=loop.id,
        session_id="sess",
    )
    with pytest.raises(RequestError, match="finding_set_id mismatch"):
        service.respond(
            {
                "loop_id": loop.id,
                "target_revision": 0,
                "finding_set_id": "wrong",
                "reported_findings": [],
                "review_completed": True,
                "summary": "clear",
            },
            capability_token=token,
        )
