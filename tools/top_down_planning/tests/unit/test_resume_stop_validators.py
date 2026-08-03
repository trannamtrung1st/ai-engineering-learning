"""Tests for stop-specific resume apply validators."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import (
    create_run_kwargs,
    make_review_loop,
    save_review_payload,
)
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator.phases import PLANNING, WHOLE_PLAN_REVIEW
from top_down_planning.orchestrator.resume_stop_validators import (
    ResumeStopValidationError,
    validate_limit_exhausted_stop,
)
from top_down_planning.persistence import FileRunStore


def _plan() -> Plan:
    return Plan(
        id="plan-run-test",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Root",
                kind="aggregate",
            )
        },
    )


def test_validate_limit_exhausted_requires_integer_consumed(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T002001-002001"
    store.create_run(
        run_id,
        plan=_plan(),
        phase=PLANNING,
        **create_run_kwargs(store.root),
    )
    run = {
        "phase": PLANNING,
        "stop": {
            "code": "limit_exhausted",
            "phase": PLANNING,
            "details": {
                "limit": "limits.planning.max_agent_turns",
                "consumed": True,
                "configured": 1,
            },
        },
    }
    with pytest.raises(ResumeStopValidationError, match="integer details.consumed"):
        validate_limit_exhausted_stop(store, run_id, run, run["stop"])


def test_validate_limit_exhausted_rejects_consumed_loop_mismatch(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T002002-002002"
    store.create_run(
        run_id,
        plan=_plan(),
        phase=WHOLE_PLAN_REVIEW,
        **create_run_kwargs(store.root),
    )
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        status="blocked",
        lifecycle_status="limit_reached",
        exhausted_budget="scope_review",
        scope_review_rounds=2,
        target_revision=0,
        scope={"kind": "whole_plan"},
        revise_at="blocker",
    )
    save_review_payload(store, run_id, loop.to_dict())
    stop = {
        "code": "limit_exhausted",
        "phase": WHOLE_PLAN_REVIEW,
        "details": {
            "limit": "limits.whole_plan_review.max_scope_review_rounds",
            "consumed": 1,
            "configured": 1,
            "loop_id": loop.id,
            "exhausted_budget": "scope_review",
        },
    }
    run = {"phase": WHOLE_PLAN_REVIEW, "stop": stop}
    with pytest.raises(ResumeStopValidationError, match="does not match loop"):
        validate_limit_exhausted_stop(store, run_id, run, stop)


def test_validate_limit_exhausted_accepts_review_gate_turn_pause(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T002003-002003"
    store.create_run(
        run_id,
        plan=_plan(),
        phase=WHOLE_PLAN_REVIEW,
        **create_run_kwargs(store.root),
    )
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        status="pending",
        lifecycle_status="review_pending",
        gate_agent_turns=1,
        target_revision=0,
        scope={"kind": "whole_plan"},
        revise_at="blocker",
    )
    save_review_payload(store, run_id, loop.to_dict())
    stop = {
        "code": "limit_exhausted",
        "phase": WHOLE_PLAN_REVIEW,
        "details": {
            "limit": "limits.review.max_agent_turns_per_gate",
            "consumed": 1,
            "configured": 1,
            "loop_id": loop.id,
        },
    }
    run = {"phase": WHOLE_PLAN_REVIEW, "stop": stop}
    validated = validate_limit_exhausted_stop(store, run_id, run, stop)
    assert validated.id == loop.id
    assert validated.gate_agent_turns == 1


def test_validate_limit_exhausted_accepts_focused_gate_turn_pause_in_planning(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T002004-002004"
    store.create_run(
        run_id,
        plan=_plan(),
        phase=PLANNING,
        **create_run_kwargs(store.root),
    )
    loop = make_review_loop(
        id="review-focused-plan-01",
        type="focused_plan",
        status="pending",
        lifecycle_status="review_pending",
        gate_agent_turns=2,
        target_revision=0,
        scope={"kind": "focused_plan", "item_ids": ["item-root"]},
        revise_at="blocker",
    )
    save_review_payload(store, run_id, loop.to_dict())
    stop = {
        "code": "limit_exhausted",
        "phase": PLANNING,
        "details": {
            "limit": "limits.review.max_agent_turns_per_gate",
            "consumed": 2,
            "configured": 2,
            "loop_id": loop.id,
        },
    }
    run = {"phase": PLANNING, "stop": stop}
    validated = validate_limit_exhausted_stop(store, run_id, run, stop)
    assert validated.id == loop.id
    assert validated.type == "focused_plan"
