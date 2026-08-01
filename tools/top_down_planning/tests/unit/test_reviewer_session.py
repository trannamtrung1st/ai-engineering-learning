"""Tests for reviewer session allocation and capability delivery."""

from __future__ import annotations

from pathlib import Path

from core_tools.provider import StubProvider
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.orchestrator.mandatory_review_stages import verification_recheck_request
from top_down_planning.orchestrator.phases import WHOLE_PLAN_REVIEW
from top_down_planning.orchestrator.reviewer_session import (
    build_reviewer_protocol_instructions,
    build_reviewer_tool_instructions,
    begin_reviewer_review,
    deliver_reviewer_turn,
)
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, done_events, make_review_loop


def _create_review_run(store: FileRunStore, run_id: str) -> None:
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        kind="aggregate",
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
                "run": {"output_goal": "Deliver the feature."},
            },
        ),
        phase=WHOLE_PLAN_REVIEW,
    )


def test_reviewer_protocol_discourages_host_planning_artifacts() -> None:
    protocol = " ".join(build_reviewer_protocol_instructions())
    assert "review respond" in protocol
    assert "host planning modes" in protocol


def test_tool_instructions_discourage_uv_run() -> None:
    instructions = build_reviewer_tool_instructions("run-test")
    assert "uv run" in instructions["respond"]
    assert "TDP_CAPABILITY_TOKEN" in instructions["authorization"]


def test_begin_reviewer_review_starts_session_with_review_package(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T009901-009901"
    _create_review_run(store, run_id)
    provider = StubProvider()
    provider.script_turn(done_events(text="review turn"))

    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="stub-session-reviewer-pending",
        target_revision=0,
        scope={"kind": "whole_plan"},
        revise_at="blocker",
    )
    store.save_review(run_id, loop.to_dict())

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
    assert '"purpose": "review"' in session.history[0]["prompt"]


def test_deliver_reviewer_turn_binds_token_before_send(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T009902-009902"
    _create_review_run(store, run_id)
    provider = StubProvider()
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="stub-session-reviewer-pending",
        target_revision=0,
        scope={"kind": "whole_plan"},
        revise_at="blocker",
    )
    store.save_review(run_id, loop.to_dict())
    provider.script_turn(done_events(text="initial review"))
    session_id, _token = begin_reviewer_review(
        provider,
        store,
        run_id,
        loop_id="review-whole-plan-01",
        review_package={"loop_id": "review-whole-plan-01", "purpose": "initial"},
        phase=WHOLE_PLAN_REVIEW,
    )
    provider.script_turn(done_events(text="recheck"))

    loop = ReviewLoop.from_dict(store.load_review(run_id, "review-whole-plan-01"))
    token = deliver_reviewer_turn(
        provider,
        store,
        run_id,
        session_id=session_id,
        loop_id="review-whole-plan-01",
        phase=WHOLE_PLAN_REVIEW,
        request=verification_recheck_request(
            phase=WHOLE_PLAN_REVIEW,
            loop=loop,
            target_revision=0,
        ),
    )

    assert token
    assert provider._capability_token == token
