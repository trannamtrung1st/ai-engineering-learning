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
from top_down_planning.orchestrator.phases import PLANNING, SUB_TDPS, WHOLE_PLAN_REVIEW
from top_down_planning.orchestrator.resume_stop_validators import (
    ResumeStopValidationError,
    validate_limit_exhausted_stop,
    validate_stop_for_resume_apply,
    validate_sub_tdps_awaiting_children_stop,
)
from top_down_planning.domain.run_kind import RUN_KIND_PARENT_EXECUTION
from top_down_planning.orchestrator.prepared_run_factory import PreparedRunFactory
from top_down_planning.persistence.sub_tdp_state import (
    initial_sub_tdp_state_from_package,
    merge_sub_tdp_state_into_production,
)
from top_down_planning.domain.sub_tdp_units import SubTdpUnit
from tests.support.run_builders import _built_package
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


def test_validate_sub_tdps_awaiting_children_stop_accepts_parent_pause(
    tmp_path: Path,
) -> None:
    store, _, package = _built_package(tmp_path)
    config = create_run_kwargs(tmp_path)["resolved_config"]
    parent_id = PreparedRunFactory().create_parent_run(
        store,
        package,
        resolved_config=config,
        invocation={"command": "execute", "observability": {}},
    )
    run = store.load_run(parent_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["phase"] = SUB_TDPS
    run["status"] = "paused"
    run["stop"] = {
        "code": "sub_tdps_awaiting_children",
        "category": "operational",
        "phase": SUB_TDPS,
        "message": "waiting",
        "role": None,
        "details": {},
    }
    store.save_run(parent_id, run, expected)
    units = [
        SubTdpUnit(
            plan_item_id=unit.unit_id,
            title=unit.title,
            outcome="",
            directory=unit.plan_file.parent.name,
            ordinal=unit.ordinal,
        )
        for unit in sorted(package.units.values(), key=lambda item: item.ordinal)
    ]
    production = store.load_production(parent_id)
    parent_binding = store.load_run(parent_id).get("package_binding") or {}
    state = initial_sub_tdp_state_from_package(
        package.manifest,
        manifest_path=str(parent_binding.get("manifest_path") or package.manifest_path),
        units=units,
        package_units=package.units,
    )
    merged = merge_sub_tdp_state_into_production(production, state)
    expected_revision = int(production["revision"])
    merged["revision"] = expected_revision + 1
    store.save_production(parent_id, merged, expected_revision)

    validate_sub_tdps_awaiting_children_stop(store, parent_id, store.load_run(parent_id))
    assert (
        validate_stop_for_resume_apply(
            store,
            parent_id,
            store.load_run(parent_id),
            store.load_run(parent_id)["stop"],
        )
        is None
    )
    assert store.load_run(parent_id).get("run_kind") == RUN_KIND_PARENT_EXECUTION
