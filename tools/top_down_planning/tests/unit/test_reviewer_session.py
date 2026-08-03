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


def test_whole_output_discovery_protocol_includes_family_procedure() -> None:
    protocol = " ".join(
        build_reviewer_protocol_instructions(
            stage="initial_review",
            review_type="whole_output",
        )
    ).lower()
    assert "traceability" in protocol
    assert "candidate_refs" in protocol
    assert "discovery_sweep" in protocol
    assert "audit attestation" in protocol
    assert "reopens_family_id" in protocol


def test_whole_output_verification_protocol_includes_bounded_family_sweep() -> None:
    protocol = " ".join(
        build_reviewer_protocol_instructions(
            stage="finding_verification",
            review_type="whole_output",
        )
    ).lower()
    assert "family_results" in protocol
    assert "verification_sweep" in protocol
    assert "not a new broad discovery pass" in protocol


    protocol = " ".join(
        build_reviewer_protocol_instructions(
            stage="initial_review",
            review_type="whole_plan",
        )
    ).lower()
    assert "validation_issues" in protocol
    assert "candidate_refs" in protocol
    assert "discovery_sweep" in protocol
    assert "audit attestation" in protocol
    assert "reopens_family_id" in protocol


def test_whole_plan_verification_protocol_includes_bounded_family_sweep() -> None:
    protocol = " ".join(
        build_reviewer_protocol_instructions(
            stage="finding_verification",
            review_type="whole_plan",
        )
    ).lower()
    assert "family_results" in protocol
    assert "verification_sweep" in protocol
    assert "not a new broad discovery pass" in protocol


def test_scope_review_protocol_is_prior_finding_independent() -> None:
    protocol = " ".join(
        build_reviewer_protocol_instructions(
            stage="scope_review",
            review_type="whole_plan",
        )
    ).lower()
    assert "do not use prior finding or family text as framing" in protocol
    assert "independently observe" in protocol
    assert "reopens_family_id" in protocol
    assert "discovery_sweep" in protocol
    assert "validation_issues" in protocol


def test_whole_plan_verification_protocol_omits_audit_attestation() -> None:
    protocol = " ".join(
        build_reviewer_protocol_instructions(
            stage="finding_verification",
            review_type="whole_plan",
        )
    ).lower()
    assert "audit_attestation" not in protocol
    assert "family_results" in protocol


def test_tool_instructions_discourage_uv_run() -> None:
    instructions = build_reviewer_tool_instructions("run-test")
    assert "discover" in instructions
    assert "agent_context.skills" in instructions["discover"]
    assert "tdp agent readme" in instructions["discover"].lower()
    assert "uv run" in instructions["respond"]
    assert "TDP_CAPABILITY_TOKEN" in instructions["authorization"]
    assert instructions["agent_requests_dir"] == "$TDP_AGENT_REQUESTS_DIR"
    assert "TDP_AGENT_REQUESTS_DIR" in instructions["respond"]


def test_tool_instructions_use_contract_specific_scope_examples() -> None:
    focused_plan = build_reviewer_tool_instructions(
        "run-test", review_type="focused_plan"
    )
    focused_examples = {part.strip() for part in focused_plan["examples"].split(";")}
    assert "tdp agent example review-respond" in focused_examples
    assert "tdp agent example review-respond-focused-with-instance-ref" in focused_examples
    assert "tdp agent example review-respond-family-discovery-focused-plan" in focused_examples
    assert "tdp agent example review-respond-verification" in focused_examples
    assert "tdp agent example review-respond-scope" not in focused_examples
    assert "tdp agent example review-respond-scope-v1" not in focused_examples

    focused_output = build_reviewer_tool_instructions(
        "run-test", review_type="focused_output"
    )
    output_examples = {part.strip() for part in focused_output["examples"].split(";")}
    assert "tdp agent example review-respond-family-discovery-focused-output" in output_examples
    assert "tdp agent example review-respond-scope-v1" not in output_examples

    family = build_reviewer_tool_instructions("run-test", family_protocol=True)
    family_examples = {part.strip() for part in family["examples"].split(";")}
    assert "tdp agent example review-respond-scope" in family_examples
    assert "tdp agent example review-respond-family-discovery" in family_examples
    assert "tdp agent example review-respond-scope-v1" not in family_examples


def test_tool_instructions_use_output_family_examples_for_whole_output() -> None:
    output = build_reviewer_tool_instructions("run-test", review_type="whole_output")
    output_examples = {part.strip() for part in output["examples"].split(";")}
    assert "tdp agent example review-respond-family-discovery-output" in output_examples
    assert "tdp agent example review-respond-family-verification-output" in output_examples
    assert "tdp agent example review-respond-family-discovery" not in output_examples


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
