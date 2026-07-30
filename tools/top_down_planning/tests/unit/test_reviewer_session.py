"""Tests for reviewer session allocation and capability delivery."""

from __future__ import annotations

from pathlib import Path

from core_tools.provider import StubProvider
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator.phases import WHOLE_PLAN_REVIEW
from top_down_planning.orchestrator.reviewer_session import (
    build_reviewer_allocation_request,
    build_reviewer_protocol_instructions,
    build_reviewer_tool_instructions,
    begin_reviewer_review,
    deliver_reviewer_turn,
)
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, done_events, script_reviewer_allocate


def _create_review_run(store: FileRunStore, run_id: str) -> None:
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the feature.",
        items={"item-root": root},
    )
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(
            store.root,
            resolved_config={
                "provider": {"name": "stub"},
                "run": {"output_goal": "Deliver the feature."},
            },
        ),
        phase=WHOLE_PLAN_REVIEW,
    )


def test_allocation_request_is_minimal() -> None:
    payload = build_reviewer_allocation_request(
        run_id="run-20260101T009901-009901",
        loop_id="review-whole-plan-01",
    )
    assert payload["action"] == "reviewer_session_allocate"
    assert "plan" not in payload


def test_reviewer_protocol_discourages_host_planning_artifacts() -> None:
    protocol = " ".join(build_reviewer_protocol_instructions())
    assert "review respond" in protocol
    assert "host planning modes" in protocol


def test_tool_instructions_discourage_uv_run() -> None:
    instructions = build_reviewer_tool_instructions("run-test")
    assert "uv run" in instructions["respond"]
    assert "TDP_CAPABILITY_TOKEN" in instructions["authorization"]


def test_begin_reviewer_review_delivers_package_after_allocate(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T009901-009901"
    _create_review_run(store, run_id)
    provider = StubProvider()
    script_reviewer_allocate(provider)
    provider.script_turn(done_events(text="review turn"))

    session_id, token = begin_reviewer_review(
        provider,
        store,
        run_id,
        loop_id="review-whole-plan-01",
        review_package={"loop_id": "review-whole-plan-01", "purpose": "review"},
        phase=WHOLE_PLAN_REVIEW,
    )

    assert session_id.startswith("stub-session-")
    assert token
    session = provider._sessions[session_id]
    assert session.history[-1]["purpose"] == "review"


def test_deliver_reviewer_turn_binds_token_before_send(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T009902-009902"
    _create_review_run(store, run_id)
    provider = StubProvider()
    script_reviewer_allocate(provider)
    session_id = provider.start_reviewer_session(
        build_reviewer_allocation_request(run_id=run_id, loop_id="review-whole-plan-01"),
    )
    provider.script_turn(done_events(text="recheck"))

    token = deliver_reviewer_turn(
        provider,
        store,
        run_id,
        session_id=session_id,
        loop_id="review-whole-plan-01",
        phase=WHOLE_PLAN_REVIEW,
        request={"action": "recheck_revision"},
    )

    assert token
    assert provider._capability_token == token
