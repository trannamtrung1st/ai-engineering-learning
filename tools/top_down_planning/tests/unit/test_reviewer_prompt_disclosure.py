"""Reviewer prompt and package policy guidance (material disclosure)."""

from __future__ import annotations

from pathlib import Path

from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.reviews import ReviewLoop, allocate_discovery_finding_set_id
from top_down_planning.orchestrator.focused_review import build_focused_review_package
from top_down_planning.orchestrator.mandatory_review_stages import stage_package_fields
from top_down_planning.orchestrator.reviewer_session import (
    build_reviewer_protocol_instructions,
)
from top_down_planning.orchestrator.whole_plan_review import build_whole_plan_review_package
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, minimal_resolved_config


def test_discovery_protocol_requires_full_material_disclosure() -> None:
    protocol = " ".join(build_reviewer_protocol_instructions()).lower()
    assert "every material issue" in protocol
    assert "do not omit lower-severity" in protocol
    assert "review_policy" in protocol
    assert "blocking findings when needed" not in protocol


def test_scope_review_protocol_is_not_blocker_only() -> None:
    protocol = " ".join(
        build_reviewer_protocol_instructions(stage="scope_review")
    ).lower()
    assert "every material issue" in protocol
    assert "remaining approval blockers within the current scope only" not in protocol
    assert "do not raise optional style" not in protocol
    assert "reported_findings" in protocol


def test_verification_protocol_stays_narrow() -> None:
    protocol = " ".join(
        build_reviewer_protocol_instructions(stage="finding_verification")
    ).lower()
    assert "broad discovery" in protocol
    assert "direct revision side effects" in protocol
    assert "every material issue" not in protocol


def test_stage_packages_include_review_policy_without_revise_at() -> None:
    loop = ReviewLoop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=1,
        scope={"kind": "whole_plan"},
        lifecycle_status="review_pending",
        active_stage="initial_review",
        finding_set_id="fs-1",
        revise_at="major",
    )
    fields = stage_package_fields(loop)
    assert "revise_at" not in fields
    assert fields["review_policy"]["severity_order"] == [
        "suggestion",
        "minor",
        "major",
        "blocker",
    ]
    assert "severity_definitions" in fields["review_policy"]
    assert "categories" in fields["review_policy"]


def test_focused_and_whole_packages_omit_revise_at(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T000001-b2c3d4"
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
        revision=1,
        output_goal="Deliver.",
        items={"item-root": root},
    )
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(tmp_path, resolved_config=minimal_resolved_config()),
    )
    run = store.load_run(run_id)
    config = store.load_resolved_config(run_id)
    focused, finding_set_id = allocate_discovery_finding_set_id(
        ReviewLoop(
            id="review-focused-plan-01",
            type="focused_plan",
            reviewer_session_id=None,
            target_revision=1,
            scope={"kind": "focused_plan", "item_ids": ["item-root"]},
            revise_at="blocker",
        )
    )
    focused_pkg = build_focused_review_package(
        run_id, run, config, focused, plan=plan
    )
    assert focused_pkg["finding_set_id"] == finding_set_id
    assert "revise_at" not in focused_pkg
    assert focused_pkg["review_policy"]["severity_order"][-1] == "blocker"
    protocol = " ".join(focused_pkg["protocol_instructions"]).lower()
    assert "every material issue" in protocol

    whole = ReviewLoop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=1,
        scope={"kind": "whole_plan"},
        lifecycle_status="scope_review_pending",
        active_stage="scope_review",
        finding_set_id="review-whole-plan-01-fs-01",
        revise_at="major",
    )
    whole_pkg = build_whole_plan_review_package(run_id, run, config, plan, whole)
    assert "revise_at" not in whole_pkg
    assert "review_policy" in whole_pkg
    assert whole_pkg["freshness"]["purpose"].lower().find("every material") >= 0
