"""Tests for mandatory whole-output review orchestration."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.agent_tool import RequestError, ReviewAgentService
from top_down_planning.agent_tool.errors import CapabilityDeniedError
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.orchestrator import ProviderRunError, WholeOutputReviewOrchestrator
from top_down_planning.orchestrator.phases import OUTPUT_VALIDATED, WHOLE_OUTPUT_REVIEW
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.digests import compute_output_digest
from core_tools.provider import StubProvider
from tests.helpers import apply_production, create_run_kwargs, done_events, grant_capability, respond_review, script_reviewer_allocate, whole_plan_approval_record


def _create_run_at_whole_output_review(
    store: FileRunStore,
    run_id: str = "run-20260101T000801-000801",
    *,
    limits: dict | None = None,
    provider: StubProvider | None = None,
    goal_assessment: str = "Output goal is fully met.",
) -> str | None:
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
    )
    leaf = PlanItem(
        id="item-leaf",
        parent_id="item-root",
        order_key="0000000000",
        title="Leaf",
        outcome="Leaf outcome.",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the feature.",
        items={"item-root": root, "item-leaf": leaf},
    )
    config = {
        "run": {
            "output_goal": "Deliver the feature.",
            "input_refs": ["README.md"],
        },
        "planning": {
            "stop_hint": "Stop when ready.",
            "max_depth": 4,
            "max_expansion_per_item": 7,
        },
        "limits": {
            "whole_output_review": {
                "max_revision_cycles": 5,
            }
        },
        "provider": {"name": "stub"},
    }
    if limits:
        config["limits"]["whole_output_review"].update(limits)

    production = {
        "revision": 2,
        "output_revision": 1,
        "batches": [
            {
                "id": "batch-01",
                "plan_items": ["item-leaf"],
                "status": "completed",
                "result": {
                    "outputs": [],
                    "contributions": [],
                    "dispositions": {"item-leaf": {"disposition": "completed"}},
                    "summary": "done",
                    "empty_output": False,
                    "goal_assessment": "",
                },
            }
        ],
        "dispositions": {"item-leaf": "completed"},
        "output_evidence": [],
        "completion_claim": {
            "goal_assessment": goal_assessment,
            "goal_met": True,
            "summary": "All items complete.",
            "plan_revision": 0,
            "output_revision": 1,
            "all_applicable_items_processed": True,
        },
    }

    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=config),
        phase=WHOLE_OUTPUT_REVIEW,
        production=production,
    )
    store.save_review(
        run_id,
        whole_plan_approval_record(
            store,
            run_id,
            id="review-whole-plan-01",
            reviewer_session_id="stub-session-plan-reviewer",
        ),
    )

    session_id = None
    if provider is not None:
        provider.script_turn(done_events(text="turn complete"))
        session_id = provider.start_primary_session(
            "producer",
            {"run_id": run_id, "phase": WHOLE_OUTPUT_REVIEW},
        )
        list(provider.stream_events(session_id))

    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    digests = dict(run.get("digests") or {})
    digests["output"] = compute_output_digest(production)
    run["digests"] = digests
    sessions: dict[str, str] = {}
    if session_id is not None:
        sessions["primary_producer_session_id"] = session_id
    run["sessions"] = sessions
    store.save_run(run_id, run, expected_revision)
    return session_id


def _review_respond_request(
    *,
    decision: str,
    target_revision: int = 1,
    findings: list[dict] | None = None,
) -> dict:
    return {
        "loop_id": "review-whole-output-01",
        "target_revision": target_revision,
        "decision": decision,
        "findings": findings or [],
    }


def test_whole_output_review_approve_reaches_accepted(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_output_review(store, provider=provider)

    run_id = "run-20260101T000801-000801"
    script_reviewer_allocate(provider)
    provider.script_turn(
        done_events(text="turn complete"),
        mutate_store=respond_review(
            store,
            run_id,
            _review_respond_request(decision="approved"),
            phase=WHOLE_OUTPUT_REVIEW,
            loop_id="review-whole-output-01",
        ),
    )

    result = WholeOutputReviewOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.phase == OUTPUT_VALIDATED
    assert result.outcome == "accepted"
    assert result.loop_id == "review-whole-output-01"

    run = store.load_run("run-20260101T000801-000801")
    assert run["status"] == "completed"
    assert run["outcome"] == "accepted"


def test_whole_output_review_changes_then_approve_reaches_accepted(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_output_review(store, provider=provider)
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "leaf.txt").write_text("leaf artifact", encoding="utf-8")

    run_id = "run-20260101T000801-000801"
    script_reviewer_allocate(provider)
    provider.script_turn(
        done_events(text="turn complete"),
        mutate_store=respond_review(
            store,
            run_id,
            _review_respond_request(
                decision="changes_requested",
                findings=[
                    {
                        "id": "finding-01",
                        "importance": "blocking",
                        "target_refs": ["item-leaf"],
                        "issue": "Output evidence is missing.",
                        "required_change": "Add artifact reference.",
                        "status": "unresolved",
                    }
                ],
            ),
            phase=WHOLE_OUTPUT_REVIEW,
            loop_id="review-whole-output-01",
        ),
    )
    provider.script_turn(
        done_events(text="turn complete"),
        mutate_store=lambda: (
            apply_production(
                store,
                run_id,
                {
                    "production_revision": 2,
                    "evidence_revision": True,
                    "plan_items": ["item-leaf"],
                    "dispositions": {
                        "item-leaf": {
                            "disposition": "completed",
                            "evidence": "Added artifact reference.",
                        }
                    },
                    "outputs": [
                        {
                            "id": "output-leaf",
                            "type": "artifact",
                            "ref": "artifacts/leaf.txt",
                        }
                    ],
                    "contributions": [
                        {
                            "item_id": "item-leaf",
                            "output_refs": ["output-leaf"],
                            "summary": "Revised evidence.",
                        }
                    ],
                    "summary": "Addressed reviewer finding.",
                },
                handler="apply",
                phase=WHOLE_OUTPUT_REVIEW,
            )(),
            apply_production(
                store,
                run_id,
                {
                    "goal_assessment": "Output goal is fully met after revision.",
                    "goal_met": True,
                },
                handler="submit_completion",
                phase=WHOLE_OUTPUT_REVIEW,
            )(),
        ),
    )
    provider.script_turn(
        done_events(text="turn complete"),
        mutate_store=respond_review(
            store,
            run_id,
            _review_respond_request(
                decision="approved",
                target_revision=2,
            ),
            phase=WHOLE_OUTPUT_REVIEW,
            loop_id="review-whole-output-01",
        ),
    )

    result = WholeOutputReviewOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.outcome == "accepted"
    assert result.revision_cycles == 1


def test_missing_goal_assessment_blocks_acceptance(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_output_review(
        store,
        provider=provider,
        goal_assessment="",
    )

    run_id = "run-20260101T000801-000801"
    script_reviewer_allocate(provider)
    provider.script_turn(
        done_events(text="turn complete"),
        mutate_store=respond_review(
            store,
            run_id,
            _review_respond_request(decision="approved"),
            phase=WHOLE_OUTPUT_REVIEW,
            loop_id="review-whole-output-01",
        ),
    )

    result = WholeOutputReviewOrchestrator(store, run_id, provider).run()
    assert result.outcome == "blocked"
    assert result.reason is not None
    assert "validation" in result.reason


def test_revision_cycle_limit_yields_rejected_not_accepted(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_output_review(store, limits={"max_revision_cycles": 1}, provider=provider)

    run_id = "run-20260101T000801-000801"
    script_reviewer_allocate(provider)
    provider.script_turn(
        done_events(text="turn complete"),
        mutate_store=respond_review(
            store,
            run_id,
            _review_respond_request(
                decision="changes_requested",
                findings=[
                    {
                        "id": "finding-01",
                        "importance": "blocking",
                        "target_refs": ["item-leaf"],
                        "issue": "Needs work.",
                        "required_change": "Improve output.",
                        "status": "unresolved",
                    }
                ],
            ),
            phase=WHOLE_OUTPUT_REVIEW,
            loop_id="review-whole-output-01",
        ),
    )
    provider.script_turn(done_events(text="turn complete"))
    provider.script_turn(
        done_events(text="turn complete"),
        mutate_store=respond_review(
            store,
            run_id,
            _review_respond_request(
                decision="changes_requested",
                findings=[
                    {
                        "id": "finding-02",
                        "importance": "blocking",
                        "target_refs": ["item-leaf"],
                        "issue": "Still needs work.",
                        "required_change": "Improve again.",
                        "status": "unresolved",
                    }
                ],
            ),
            phase=WHOLE_OUTPUT_REVIEW,
            loop_id="review-whole-output-01",
        ),
    )

    result = WholeOutputReviewOrchestrator(store, run_id, provider).run()

    assert result.ok is False
    assert result.outcome == "rejected"
    assert "max_revision_cycles" in (result.reason or "")


def test_provider_exception_does_not_set_outcome(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_output_review(store, provider=provider)

    script_reviewer_allocate(provider)
    provider.script_turn([{"type": "error", "text": "provider crashed"}])
    with pytest.raises(ProviderRunError, match="provider crashed"):
        WholeOutputReviewOrchestrator(store, "run-20260101T000801-000801", provider).run()

    run = store.load_run("run-20260101T000801-000801")
    assert run["phase"] == WHOLE_OUTPUT_REVIEW
    assert run["outcome"] is None
    assert run["status"] == "running"


def test_whole_output_review_respond_uses_output_revision(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_run_at_whole_output_review(store)
    store.save_review(
        "run-20260101T000801-000801",
        {
            "id": "review-whole-output-01",
            "type": "whole_output",
            "reviewer_session_id": "stub-session-reviewer",
            "target_revision": 1,
            "scope": {"kind": "whole_output"},
            "status": "pending",
            "findings": [],
            "revision_cycles": 0,
        },
    )

    service = ReviewAgentService(store, "run-20260101T000801-000801")
    token = grant_capability(
        store,
        "run-20260101T000801-000801",
        role="reviewer",
        phase=WHOLE_OUTPUT_REVIEW,
        session_kind="reviewer",
        session_id="stub-session-reviewer",
        loop_id="review-whole-output-01",
    )
    with pytest.raises(RequestError, match="does not match current output revision"):
        service.respond(
            _review_respond_request(decision="approved", target_revision=0),
            capability_token=token,
        )
