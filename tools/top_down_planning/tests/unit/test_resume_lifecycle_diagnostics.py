"""Semantic resume --check diagnostics for cross-record lifecycle conflicts."""

from __future__ import annotations

from pathlib import Path

from top_down_planning.domain.production_blockers import (
    BLOCKER_KIND_FOCUSED_REVIEW_WAIT,
    BLOCKER_STATUS_ACTIVE,
)
from top_down_planning.domain.resume_lifecycle_diagnostics import (
    collect_lifecycle_diagnostics,
)
from top_down_planning.orchestrator.phases import PRODUCTION
from top_down_planning.persistence import FileRunStore
from tests.helpers import make_review_loop, save_review_payload
from tests.support.run_builders import _create_paused_production_run


def test_collects_stale_review_bound_blocker_diagnostic() -> None:
    loop = make_review_loop(
        id="review-focused-output-01",
        type="focused_output",
        target_revision=2,
        scope={"kind": "focused_output", "item_ids": ["item-first"]},
        status="approved",
        reviewer_session_id="sess",
        verification_result={"target_digest": "digest-a", "decision": "verified"},
    )
    diagnostics = collect_lifecycle_diagnostics(
        run={"status": "paused", "phase_action_id": None, "stop": None},
        production={
            "blocker_report": {
                "kind": BLOCKER_KIND_FOCUSED_REVIEW_WAIT,
                "status": BLOCKER_STATUS_ACTIVE,
                "review_loop_id": loop.id,
                "target_revision": 2,
                "target_digest": "digest-a",
                "evidence": "Waiting on focused review.",
            }
        },
        reviews=[loop.to_dict()],
    )
    assert any(item.code == "stale_review_bound_blocker" for item in diagnostics)
    row = next(item for item in diagnostics if item.code == "stale_review_bound_blocker")
    assert row.loop_id == loop.id
    assert "already satisfied" in row.message
    assert row.proposed_reconciliation


def test_collects_unsatisfiable_review_bound_blocker_diagnostic() -> None:
    loop = make_review_loop(
        id="review-focused-output-01",
        type="focused_output",
        target_revision=3,
        scope={"kind": "focused_output", "item_ids": ["item-first"]},
        status="approved",
        reviewer_session_id="sess",
        verification_result={"target_digest": "digest-b", "decision": "verified"},
    )
    diagnostics = collect_lifecycle_diagnostics(
        run={"status": "paused", "phase_action_id": None, "stop": None},
        production={
            "blocker_report": {
                "kind": BLOCKER_KIND_FOCUSED_REVIEW_WAIT,
                "status": BLOCKER_STATUS_ACTIVE,
                "review_loop_id": loop.id,
                "target_revision": 2,
                "target_digest": "digest-a",
                "evidence": "Waiting on focused review.",
            }
        },
        reviews=[loop.to_dict()],
    )
    assert any(item.code == "unsatisfiable_review_bound_blocker" for item in diagnostics)
    row = next(
        item for item in diagnostics if item.code == "unsatisfiable_review_bound_blocker"
    )
    assert row.loop_id == loop.id
    assert row.target_revision == 2
    assert "cannot be satisfied" in row.message
    assert "do not auto-clear" in row.proposed_reconciliation


def test_collects_unsatisfiable_blocker_for_verified_digest_mismatch() -> None:
    loop = make_review_loop(
        id="review-focused-output-01",
        type="focused_output",
        target_revision=2,
        scope={"kind": "focused_output", "item_ids": ["item-first"]},
        status="verified",
        reviewer_session_id="sess",
        verification_result={"target_digest": "digest-b", "decision": "verified"},
    )
    diagnostics = collect_lifecycle_diagnostics(
        run={"status": "paused", "stop": None},
        production={
            "blocker_report": {
                "kind": BLOCKER_KIND_FOCUSED_REVIEW_WAIT,
                "status": BLOCKER_STATUS_ACTIVE,
                "review_loop_id": loop.id,
                "target_revision": 2,
                "target_digest": "digest-a",
                "evidence": "Waiting on focused review.",
            }
        },
        reviews=[loop.to_dict()],
    )
    assert any(item.code == "unsatisfiable_review_bound_blocker" for item in diagnostics)


def test_collects_misclassified_provider_turn_failed_diagnostic() -> None:
    diagnostics = collect_lifecycle_diagnostics(
        run={
            "status": "paused",
            "phase_action_id": None,
            "phase_action_domain_committed_id": "action-abc",
            "stop": {
                "code": "provider_turn_failed",
                "category": "operational",
                "phase": PRODUCTION,
                "message": "advisory handoff already completed",
            },
        },
        production={"blocker_report": None},
        reviews=[],
    )
    assert any(item.code == "misclassified_provider_turn_failed" for item in diagnostics)
    row = next(
        item for item in diagnostics if item.code == "misclassified_provider_turn_failed"
    )
    assert row.phase_action_domain_committed_id == "action-abc"
    assert "orchestration/state handling" in row.message
    assert "do not restore phase_action_id" in row.proposed_reconciliation


def test_collects_advisory_identity_mismatch_diagnostic() -> None:
    loop = make_review_loop(
        id="review-whole-output-01",
        type="whole_output",
        target_revision=1,
        scope={"kind": "whole_output"},
        status="advisory_pending",
        lifecycle_status="scope_review_pending",
        active_stage="scope_review",
        reviewer_session_id="sess",
        finding_set_id="review-whole-output-01-fs-01",
        advisory_handoffs_completed=["review-whole-output-01-fs-01"],
        revise_at="blocker",
        findings=[
            {
                "id": "finding-opt",
                "severity": "minor",
                "category": "correctness",
                "target_refs": ["item-root"],
                "issue": "Optional polish.",
                "recommended_change": "Improve wording.",
                "status": "unresolved",
            }
        ],
        finding_actions=[],
        finding_ids_by_set={"review-whole-output-01-fs-01": ["finding-opt"]},
    )
    diagnostics = collect_lifecycle_diagnostics(
        run={"status": "paused", "stop": None},
        production={"blocker_report": None},
        reviews=[loop.to_dict()],
    )
    assert any(item.code == "advisory_handoff_identity_mismatch" for item in diagnostics)
    row = next(
        item for item in diagnostics if item.code == "advisory_handoff_identity_mismatch"
    )
    assert row.loop_id == loop.id
    assert row.finding_set_id == "review-whole-output-01-fs-01"
    assert "fresh finding_set_id" in row.proposed_reconciliation


def test_resume_allows_misclassified_provider_turn_failed(tmp_path: Path) -> None:
    from top_down_planning.orchestrator.prepare_resume import prepare_resume

    store = FileRunStore(tmp_path)
    run_id = _create_paused_production_run(store)
    run = store.load_run(run_id)
    expected = int(run["revision"])
    run = dict(run)
    run["revision"] = expected + 1
    run["phase_action_id"] = None
    run["phase_action_domain_committed_id"] = "action-committed"
    run["stop"] = {
        "code": "provider_turn_failed",
        "category": "operational",
        "phase": PRODUCTION,
        "message": "advisory handoff already completed",
        "details": {},
    }
    store.save_run(run_id, run, expected)
    stored = store.load_resolved_config(run_id)
    plan = prepare_resume(store, run_id, stored)
    assert plan.state_transition is not None
    assert plan.state_transition.to_status == "running"
