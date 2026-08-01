"""Tests for mandatory whole-output review orchestration."""

from __future__ import annotations

from top_down_planning.persistence.session_bindings import update_primary_binding
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
from tests.helpers import apply_production, create_run_kwargs, done_events, grant_capability, mandatory_initial_respond_request, mandatory_output_digest, respond_review, save_review_payload, script_mandatory_clear_approval, script_reviewer_allocate, script_verification_then_scope_review_approval, sessions_with_primary_session, whole_plan_approval_record


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
        kind="aggregate",
    )
    leaf = PlanItem(
        id="item-leaf",
        parent_id="item-root",
        order_key="0000000000",
        title="Leaf",
        outcome="Leaf outcome.",
        kind="work",
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
    save_review_payload(store, run_id,
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
        sessions = update_primary_binding(sessions, role="producer", provider_session_id=session_id)
    run["sessions"] = sessions
    store.save_run(run_id, run, expected_revision)
    save_review_payload(store, run_id, {
            "id": "review-whole-output-01",
            "type": "whole_output",
            "revise_at": "blocker",
            "target_revision": int(production["output_revision"]),
            "scope": {"kind": "whole_output"},
            "status": "pending",
            "findings": [],
            "revision_cycles": 0,
            "lifecycle_status": "review_pending",
            "scope_review_rounds": 0,
        },
    )
    return session_id


def _review_respond_request(
    *,
    decision: str,
    target_revision: int = 1,
    findings: list[dict] | None = None,
    store: FileRunStore | None = None,
    run_id: str | None = None,
) -> dict:
    assert store is not None and run_id is not None
    return mandatory_initial_respond_request(
        store,
        run_id,
        loop_id="review-whole-output-01",
        target_revision=target_revision,
        review_type="whole_output",
        decision=decision,
        findings=findings,
    )


def test_whole_output_review_approve_reaches_accepted(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_output_review(store, provider=provider)

    run_id = "run-20260101T000801-000801"
    script_mandatory_clear_approval(
        provider,
        store,
        run_id,
        loop_id="review-whole-output-01",
        phase=WHOLE_OUTPUT_REVIEW,
        target_revision=1,
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
    respond_review(
        store,
        run_id,
        _review_respond_request(
            decision="changes_requested",
            findings=[
                {
                    "id": "finding-01",
                    "severity": "blocker",
                    "target_refs": ["item-leaf"],
                    "issue": "Output evidence is missing.",
                    "recommended_change": "Add artifact reference.",
                    "status": "unresolved",
                }
            ],
            store=store,
            run_id=run_id,
        ),
        phase=WHOLE_OUTPUT_REVIEW,
        loop_id="review-whole-output-01",
    )()
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
    )()
    apply_production(
        store,
        run_id,
        {
            "goal_assessment": "Output goal is fully met after revision.",
            "goal_met": True,
        },
        handler="submit_completion",
        phase=WHOLE_OUTPUT_REVIEW,
    )()
    script_verification_then_scope_review_approval(
        provider,
        store,
        run_id,
        loop_id="review-whole-output-01",
        phase=WHOLE_OUTPUT_REVIEW,
        target_revision=2,
    )

    result = WholeOutputReviewOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.outcome == "accepted"
    review = store.load_review(run_id, "review-whole-output-01")
    assert review.get("verification_result")
    assert review.get("scope_review_result")


def test_missing_goal_assessment_blocks_acceptance(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    _create_run_at_whole_output_review(
        store,
        provider=provider,
        goal_assessment="",
    )

    run_id = "run-20260101T000801-000801"
    script_mandatory_clear_approval(
        provider,
        store,
        run_id,
        loop_id="review-whole-output-01",
        phase=WHOLE_OUTPUT_REVIEW,
        target_revision=1,
    )

    result = WholeOutputReviewOrchestrator(store, run_id, provider).run()
    assert result.outcome == "blocked"
    assert result.reason is not None
    assert "validation" in result.reason


def test_revision_cycle_limit_yields_paused_not_accepted(tmp_path: Path) -> None:
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
                        "severity": "blocker",
                        "target_refs": ["item-leaf"],
                        "issue": "Needs work.",
                        "recommended_change": "Improve output.",
                        "status": "unresolved",
                    }
                ],
                store=store,
                run_id=run_id,
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
                        "severity": "blocker",
                        "target_refs": ["item-leaf"],
                        "issue": "Still needs work.",
                        "recommended_change": "Improve again.",
                        "status": "unresolved",
                    }
                ],
                store=store,
                run_id=run_id,
            ),
            phase=WHOLE_OUTPUT_REVIEW,
            loop_id="review-whole-output-01",
        ),
    )

    result = WholeOutputReviewOrchestrator(store, run_id, provider).run()

    assert result.ok is False
    assert result.outcome is None
    assert "max_revision_cycles" in (result.reason or "")

    run = store.load_run(run_id)
    assert run["status"] == "paused"
    assert run["stop"]["code"] == "limit_exhausted"


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
    save_review_payload(store, "run-20260101T000801-000801", {
            "id": "review-whole-output-01",
            "type": "whole_output",
            "revise_at": "blocker",
            "reviewer_session_id": "stub-session-reviewer",
            "target_revision": 1,
            "scope": {"kind": "whole_output"},
            "status": "pending",
            "findings": [],
            "revision_cycles": 0,
            "finding_set_id": "review-whole-output-01-fs-01",
            "lifecycle_status": "review_pending",
            "active_stage": "initial_review",
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
            _review_respond_request(
                decision="approved",
                target_revision=0,
                store=store,
                run_id="run-20260101T000801-000801",
            ),
            capability_token=token,
        )


def test_whole_output_review_resumes_interrupted_producer_revision(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    provider = StubProvider()
    producer_session_id = _create_run_at_whole_output_review(store, provider=provider)
    run_id = "run-20260101T000801-000801"
    save_review_payload(store, run_id, {
            "id": "review-whole-output-01",
            "type": "whole_output",
            "revise_at": "blocker",
            "reviewer_session_id": "stub-session-reviewer",
            "target_revision": 1,
            "scope": {"kind": "whole_output"},
            "status": "pending",
            "revision_cycles": 1,
            "lifecycle_status": "verification_pending",
            "active_stage": "finding_verification",
            "finding_set_id": "review-whole-output-01-fs-01",
            "findings": [
                {
                    "id": "finding-01",
                    "severity": "blocker",
                    "target_refs": ["item-leaf"],
                    "issue": "Output evidence is missing.",
                    "recommended_change": "Add artifact reference.",
                    "status": "unresolved",
                }
            ],
        },
    )
    run = store.load_run(run_id)
    expected_revision = int(run["revision"])
    run = dict(run)
    run["revision"] = expected_revision + 1
    run["status"] = "running"
    run["stop"] = None
    run["sessions"] = sessions_with_primary_session(producer=producer_session_id)
    store.save_run(run_id, run, expected_revision)

    provider = StubProvider()
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "leaf.txt").write_text("leaf artifact", encoding="utf-8")
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
    )()
    apply_production(
        store,
        run_id,
        {
            "goal_assessment": "Output goal is fully met after revision.",
            "goal_met": True,
        },
        handler="submit_completion",
        phase=WHOLE_OUTPUT_REVIEW,
    )()
    script_verification_then_scope_review_approval(
        provider,
        store,
        run_id,
        loop_id="review-whole-output-01",
        phase=WHOLE_OUTPUT_REVIEW,
        target_revision=2,
        finding_set_id="review-whole-output-01-fs-01",
        finding_results=[
            {
                "finding_id": "finding-01",
                "disposition": "resolved",
                "evidence": ["artifact added"],
                "direct_side_effects": [],
            }
        ],
    )

    result = WholeOutputReviewOrchestrator(store, run_id, provider).run()

    assert result.ok is True
    assert result.phase == OUTPUT_VALIDATED
    assert result.outcome == "accepted"
    assert store.load_run(run_id)["status"] == "completed"
