"""Threshold-aware focused and mandatory review orchestration tests."""

from __future__ import annotations

from pathlib import Path

from core_tools.provider import StubProvider
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.reviews import (
    ReviewFinding,
    ReviewLoop,
    apply_discovery_response,
    apply_owner_finding_actions,
    focused_output_revision_target_ids,
    loop_revise_at,
    map_discovery_outcome_to_loop_status,
    needs_advisory_handoff,
    primary_review_resume_fields,
)
from top_down_planning.orchestrator.focused_review import FocusedReviewOrchestrator
from top_down_planning.orchestrator.phases import PLANNING, WHOLE_PLAN_REVIEW
from top_down_planning.orchestrator.whole_plan_review import WholePlanReviewOrchestrator
from top_down_planning.persistence import FileRunStore
from tests.helpers import (
    make_review_loop,
    create_run_kwargs,
    done_events,
    grant_capability,
    minimal_resolved_config,
    review_loop_dict_with_binding,
    save_review_payload,
)


def _finding(
    finding_id: str,
    *,
    severity: str,
    target: str = "item-root",
) -> dict[str, object]:
    return {
        "id": finding_id,
        "severity": severity,
        "category": "correctness",
        "target_refs": [target],
        "issue": f"{severity} issue",
        "recommended_change": "Address",
        "status": "unresolved",
    }


def test_major_is_optional_under_focused_blocker_threshold() -> None:
    loop = make_review_loop(
        id="review-focused-plan-01",
        type="focused_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "focused_plan", "item_ids": ["item-root"]},
        revise_at="blocker",
        finding_set_id="fs-01",
    )
    updated, _findings, outcome = apply_discovery_response(
        loop,
        {
            "finding_set_id": "fs-01",
            "reported_findings": [_finding("f-major", severity="major")],
            "review_completed": True,
            "summary": "major only",
        },
    )
    assert outcome == "pending"
    assert updated.status == "advisory_pending"
    assert needs_advisory_handoff(updated)
    assert map_discovery_outcome_to_loop_status(outcome) == "advisory_pending"


def test_revise_at_major_forces_revision_for_major_finding() -> None:
    loop = make_review_loop(
        id="review-focused-plan-01",
        type="focused_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "focused_plan", "item_ids": ["item-root"]},
        revise_at="major",
        finding_set_id="fs-01",
    )
    updated, _findings, outcome = apply_discovery_response(
        loop,
        {
            "finding_set_id": "fs-01",
            "reported_findings": [_finding("f-major", severity="major")],
            "review_completed": True,
            "summary": "required major",
        },
    )
    assert outcome == "changes_requested"
    assert updated.status == "changes_requested"
    assert not needs_advisory_handoff(updated)


def test_primary_resume_fields_expose_revise_at_and_partitions() -> None:
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=1,
        scope={"kind": "whole_plan"},
        revise_at="major",
        finding_set_id="fs-01",
        findings=[
            ReviewFinding.from_dict(_finding("f-major", severity="major")),
            ReviewFinding.from_dict(_finding("f-minor", severity="minor")),
        ],
        finding_ids_by_set={"fs-01": ["f-major", "f-minor"]},
    )
    fields = primary_review_resume_fields(loop, config=minimal_resolved_config())
    assert fields["revise_at"] == "major"
    assert fields["required_open_finding_ids"] == ["f-major"]
    assert fields["optional_open_finding_ids"] == ["f-minor"]
    assert [item["id"] for item in fields["new_findings"]] == ["f-major", "f-minor"]
    assert fields["history_ref"]["loop_id"] == loop.id
    assert "required_findings" not in fields
    assert "optional_findings" not in fields


def test_evidence_revision_targets_required_findings_only() -> None:
    reviews = [
        review_loop_dict_with_binding(
            {
            "id": "review-focused-output-01",
            "type": "focused_output",
            "reviewer_session_id": "sess",
            "target_revision": 1,
            "scope": {"kind": "focused_output", "item_ids": ["item-a", "item-b"]},
            "status": "changes_requested",
            "revise_at": "blocker",
            "findings": [
                _finding("f-block", severity="blocker", target="item-a"),
                _finding("f-minor", severity="minor", target="item-b"),
            ],
            }
        )
    ]
    assert focused_output_revision_target_ids(
        reviews, loop_id="review-focused-output-01"
    ) == {"item-a"}


def test_focused_orchestrator_advisory_handoff_defer_completes(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T000001-f0c001"
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        outcome="Done.",
        kind="work",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver.",
        items={"item-root": root},
    )
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(tmp_path, resolved_config=minimal_resolved_config()),
        phase=PLANNING,
    )
    run = store.load_run(run_id)
    expected = int(run["revision"])
    from top_down_planning.persistence.session_bindings import update_primary_binding

    run = dict(run)
    run["revision"] = expected + 1
    run["sessions"] = update_primary_binding(
        dict(run.get("sessions") or {}),
        role="planner",
        provider_session_id="planner-sess",
    )
    store.save_run(run_id, run, expected)

    loop = make_review_loop(
        id="review-focused-plan-01",
        type="focused_plan",
        reviewer_session_id=None,
        target_revision=0,
        scope={"kind": "focused_plan", "item_ids": ["item-root"]},
        status="pending",
        revise_at="blocker",
    )
    save_review_payload(store, run_id, loop.to_dict())

    provider = StubProvider()

    def _reviewer_discovery() -> None:
        from top_down_planning.domain.session_bindings import binding_provider_session_id

        persisted = store.load_review(run_id, loop.id)
        token = grant_capability(
            store,
            run_id,
            role="reviewer",
            phase=PLANNING,
            loop_id=loop.id,
            session_id=str(binding_provider_session_id(persisted.get("reviewer_binding"))),
        )
        from top_down_planning.agent_tool import ReviewAgentService

        ReviewAgentService(store, run_id).respond(
            {
                "loop_id": loop.id,
                "target_revision": 0,
                "finding_set_id": persisted["finding_set_id"],
                "reported_findings": [_finding("f-minor", severity="minor")],
                "review_completed": True,
                "summary": "optional only",
            },
            capability_token=token,
        )

    def _planner_defers() -> None:
        persisted = store.load_review(run_id, loop.id)
        token = grant_capability(
            store,
            run_id,
            role="planner",
            phase=PLANNING,
            session_id="planner-sess",
        )
        from top_down_planning.agent_tool import ReviewAgentService

        ReviewAgentService(store, run_id).record_finding_actions(
            {
                "loop_id": loop.id,
                "artifact_revision": 0,
                "finding_actions": [
                    {
                        "finding_id": "f-minor",
                        "action": "defer",
                        "actor_role": "planner",
                        "artifact_revision": 0,
                        "finding_set_id": persisted["finding_set_id"],
                        "rationale": "Defer polish",
                    }
                ],
            },
            capability_token=token,
        )

    provider.script_turn(
        done_events(text="reviewed"),
        mutate_store=_reviewer_discovery,
    )
    provider.script_turn(
        done_events(text="deferred"),
        mutate_store=_planner_defers,
    )

    result = FocusedReviewOrchestrator(store, run_id, provider).run(loop.id)
    assert result.ok is True
    assert result.status == "approved"
    assert result.revision_cycles == 0
    persisted = ReviewLoop.from_dict(store.load_review(run_id, loop.id))
    assert persisted.finding_actions[0].action == "defer"
    assert persisted.advisory_handoffs_completed
    assert loop_revise_at(persisted) == "blocker"


def test_whole_plan_minor_only_enters_advisory_not_revision() -> None:
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=1,
        scope={"kind": "whole_plan"},
        lifecycle_status="review_pending",
        active_stage="initial_review",
        revise_at="major",
        finding_set_id="fs-01",
    )
    updated, _, outcome = apply_discovery_response(
        loop,
        {
            "finding_set_id": "fs-01",
            "reported_findings": [_finding("f-minor", severity="minor")],
            "review_completed": True,
            "summary": "minor only",
        },
        stage="initial_review",
    )
    assert outcome == "pending"
    assert updated.status == "advisory_pending"
    assert needs_advisory_handoff(updated)
    assert updated.revision_cycles == 0


def test_whole_plan_major_forces_revision_under_builtin_threshold() -> None:
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=1,
        scope={"kind": "whole_plan"},
        lifecycle_status="review_pending",
        active_stage="initial_review",
        revise_at="major",
        finding_set_id="fs-01",
    )
    updated, _, outcome = apply_discovery_response(
        loop,
        {
            "finding_set_id": "fs-01",
            "reported_findings": [_finding("f-major", severity="major")],
            "review_completed": True,
            "summary": "major required",
        },
        stage="initial_review",
    )
    assert outcome == "changes_requested"
    assert updated.status == "changes_requested"
    assert loop_revise_at(updated) == "major"


def test_clear_discovery_skips_verification_signal() -> None:
    """Approved clear discovery is ready for scope review, not verification."""

    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=1,
        scope={"kind": "whole_plan"},
        lifecycle_status="review_pending",
        active_stage="initial_review",
        revise_at="major",
        finding_set_id="fs-01",
    )
    updated, _, outcome = apply_discovery_response(
        loop,
        {
            "finding_set_id": "fs-01",
            "reported_findings": [],
            "review_completed": True,
            "summary": "clear",
        },
        stage="initial_review",
    )
    assert outcome == "approved"
    assert updated.status == "approved"
    from top_down_planning.orchestrator.mandatory_review_stages import (
        approved_means_start_scope_review,
    )

    assert approved_means_start_scope_review(updated) is True
