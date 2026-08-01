"""Fill remaining proposal Test Plan coverage gaps."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.domain.reviews import (
    FindingAction,
    ReviewFinding,
    ReviewLoop,
    apply_discovery_response,
    apply_owner_finding_actions,
    budgets_snapshot,
    focused_output_revision_target_ids,
    merge_scope_review_findings,
    merge_verification_findings,
    owner_actions_require_revision,
    owner_actions_require_verification,
    verification_required_for_loop,
    whole_output_revision_target_ids,
)
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, review_loop_dict_with_binding, save_review_payload


def _finding(
    finding_id: str,
    *,
    severity: str = "minor",
    target: str = "item-a",
    status: str = "unresolved",
    issue: str | None = None,
) -> ReviewFinding:
    return ReviewFinding(
        id=finding_id,
        severity=severity,  # type: ignore[arg-type]
        category="correctness",
        target_refs=[target],
        issue=issue or f"Issue {finding_id}",
        recommended_change="Address",
        status=status,  # type: ignore[arg-type]
    )


def _action(
    finding_id: str,
    action: str,
    *,
    finding_set_id: str = "fs-01",
    **extra: object,
) -> FindingAction:
    payload: dict[str, object] = {
        "finding_id": finding_id,
        "action": action,
        "actor_role": "producer",
        "artifact_revision": 1,
        "finding_set_id": finding_set_id,
        **extra,
    }
    if action in {"defer", "accept_as_is", "challenge"}:
        payload.setdefault("rationale", "owner rationale")
    return FindingAction.from_dict(payload)  # type: ignore[arg-type]


def test_fix_requires_revision_and_verification_challenge_verification_only() -> None:
    fix = _action("f-1", "fix")
    challenge = _action(
        "f-2",
        "challenge",
        proposed_disposition="invalid",
    )
    defer = _action("f-3", "defer")

    assert owner_actions_require_revision([fix]) is True
    assert owner_actions_require_verification([fix]) is True
    assert owner_actions_require_revision([challenge]) is False
    assert owner_actions_require_verification([challenge]) is True
    assert owner_actions_require_revision([defer]) is False
    assert owner_actions_require_verification([defer]) is False


def test_challenge_marks_verification_required_without_budget_mutation() -> None:
    loop = ReviewLoop(
        id="review-focused-plan-01",
        type="focused_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "focused_plan", "item_ids": ["item-a"]},
        status="advisory_pending",
        revise_at="blocker",
        finding_set_id="fs-01",
        revision_cycles=2,
        scope_review_rounds=1,
        findings=[_finding("f-opt")],
    )
    before = budgets_snapshot(loop)
    updated, parsed = apply_owner_finding_actions(
        loop,
        [
            {
                "finding_id": "f-opt",
                "action": "challenge",
                "rationale": "Not applicable here",
                "proposed_disposition": "invalid",
                "finding_set_id": "fs-01",
            }
        ],
        actor_role="planner",
        artifact_revision=0,
    )
    assert budgets_snapshot(updated) == before
    assert owner_actions_require_revision(parsed) is False
    assert verification_required_for_loop(updated) is True
    assert updated.findings[0].status == "unresolved"


def test_optional_fix_requires_revision_advance() -> None:
    loop = ReviewLoop(
        id="review-focused-plan-01",
        type="focused_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "focused_plan", "item_ids": ["item-a"]},
        status="advisory_pending",
        revise_at="blocker",
        finding_set_id="fs-01",
        findings=[_finding("f-opt")],
    )
    with pytest.raises(ValueError, match="requires artifact revision"):
        apply_owner_finding_actions(
            loop,
            [{"finding_id": "f-opt", "action": "fix", "finding_set_id": "fs-01"}],
            actor_role="planner",
            artifact_revision=0,
        )
    _updated, parsed = apply_owner_finding_actions(
        loop,
        [{"finding_id": "f-opt", "action": "fix", "finding_set_id": "fs-01"}],
        actor_role="planner",
        artifact_revision=1,
    )
    assert owner_actions_require_revision(parsed) is True
    assert owner_actions_require_verification(parsed) is True


def test_evidence_revision_includes_voluntary_optional_fix_targets() -> None:
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
            "finding_set_id": "fs-01",
            "findings": [
                _finding("f-block", severity="blocker", target="item-a").to_dict(),
                _finding("f-minor", severity="minor", target="item-b").to_dict(),
            ],
            "finding_actions": [
                _action("f-block", "fix").to_dict(),
                _action("f-minor", "fix").to_dict(),
            ],
            }
        )
    ]
    assert focused_output_revision_target_ids(
        reviews, loop_id="review-focused-output-01"
    ) == {"item-a", "item-b"}


def test_voluntary_optional_only_fix_is_accepted_as_evidence_target() -> None:
    reviews = [
        review_loop_dict_with_binding(
            {
            "id": "review-focused-output-01",
            "type": "focused_output",
            "reviewer_session_id": "sess",
            "target_revision": 1,
            "scope": {"kind": "focused_output", "item_ids": ["item-b"]},
            "status": "changes_requested",
            "revise_at": "blocker",
            "finding_set_id": "fs-01",
            "findings": [
                _finding("f-minor", severity="minor", target="item-b").to_dict(),
            ],
            "finding_actions": [_action("f-minor", "fix").to_dict()],
            }
        )
    ]
    assert focused_output_revision_target_ids(
        reviews, loop_id="review-focused-output-01"
    ) == {"item-b"}

    whole = [
        review_loop_dict_with_binding(
            {
            "id": "review-whole-output-01",
            "type": "whole_output",
            "reviewer_session_id": "sess",
            "target_revision": 2,
            "scope": {"kind": "whole_output"},
            "status": "changes_requested",
            "revise_at": "major",
            "finding_set_id": "fs-02",
            "findings": [
                _finding("f-minor", severity="minor", target="item-leaf").to_dict(),
            ],
            "finding_actions": [
                _action("f-minor", "fix", finding_set_id="fs-02").to_dict()
            ],
            }
        )
    ]
    assert whole_output_revision_target_ids(whole) == {"item-leaf"}


def test_deferred_optional_remains_in_final_review_history() -> None:
    loop = ReviewLoop(
        id="review-whole-output-01",
        type="whole_output",
        reviewer_session_id="sess",
        target_revision=1,
        scope={"kind": "whole_output"},
        status="advisory_pending",
        revise_at="major",
        finding_set_id="fs-01",
        findings=[_finding("f-opt", severity="suggestion", target="item-leaf")],
    )
    updated, parsed = apply_owner_finding_actions(
        loop,
        [
            {
                "finding_id": "f-opt",
                "action": "defer",
                "rationale": "Ship without polish",
                "finding_set_id": "fs-01",
            }
        ],
        actor_role="producer",
        artifact_revision=1,
    )
    assert updated.status == "approved"
    assert parsed[0].action == "defer"
    persisted = ReviewLoop.from_dict(updated.to_dict())
    assert [finding.id for finding in persisted.findings] == ["f-opt"]
    assert persisted.findings[0].status == "unresolved"
    assert persisted.finding_actions[0].action == "defer"


def test_duplicate_findings_across_fresh_reviews_not_deduplicated() -> None:
    prior = ReviewLoop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=1,
        scope={"kind": "whole_plan"},
        revise_at="major",
        findings=[
            _finding(
                "f-old",
                severity="minor",
                issue="Missing acceptance criteria",
            )
        ],
    )
    fresh = [
        _finding(
            "f-new",
            severity="minor",
            issue="Missing acceptance criteria",
        )
    ]
    merged = merge_scope_review_findings(prior, fresh)
    assert [finding.id for finding in merged] == ["f-old", "f-new"]
    assert merged[0].issue == merged[1].issue


def test_superseded_by_finding_id_validated_at_verification() -> None:
    loop = ReviewLoop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=1,
        scope={"kind": "whole_plan"},
        lifecycle_status="verification_pending",
        active_stage="finding_verification",
        revise_at="major",
        finding_set_id="fs-01",
        findings=[
            _finding("f-old", severity="minor", issue="Same issue"),
            _finding("f-new", severity="minor", issue="Same issue"),
        ],
        finding_actions=[
            _action(
                "f-new",
                "challenge",
                proposed_disposition="superseded",
                superseded_by_finding_id="f-old",
            )
        ],
    )
    with pytest.raises(ValueError, match="missing challenged finding_id"):
        merge_verification_findings(
            loop,
            {
                "decision": "verified",
                "finding_set_id": "fs-01",
                "finding_results": [],
                "target_digest": "digest-1",
            },
        )

    bad_link = ReviewLoop.from_dict(
        {
            **loop.to_dict(),
            "finding_actions": [
                _action(
                    "f-new",
                    "challenge",
                    proposed_disposition="superseded",
                    superseded_by_finding_id="missing",
                ).to_dict()
            ],
        }
    )
    with pytest.raises(ValueError, match="superseded_by_finding_id"):
        merge_verification_findings(
            bad_link,
            {
                "decision": "verified",
                "finding_set_id": "fs-01",
                "finding_results": [
                    {
                        "finding_id": "f-new",
                        "disposition": "superseded",
                        "evidence": ["duplicate of f-old"],
                        "direct_side_effects": [],
                    }
                ],
                "target_digest": "digest-1",
            },
        )

    merged, result = merge_verification_findings(
        loop,
        {
            "decision": "verified",
            "finding_set_id": "fs-01",
            "finding_results": [
                {
                    "finding_id": "f-new",
                    "disposition": "superseded",
                    "evidence": ["duplicate of f-old"],
                    "direct_side_effects": [],
                }
            ],
            "target_digest": "digest-1",
        },
    )
    assert [finding.id for finding in merged] == ["f-old", "f-new"]
    assert merged[1].status == "superseded"
    assert result.decision == "verified"


def test_fresh_scope_discovery_preserves_prior_and_new_ids() -> None:
    loop = ReviewLoop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=2,
        scope={"kind": "whole_plan"},
        lifecycle_status="scope_review_pending",
        active_stage="scope_review",
        revise_at="major",
        finding_set_id="fs-scope-02",
        findings=[_finding("f-prior", severity="suggestion")],
    )
    updated, merged, outcome = apply_discovery_response(
        loop,
        {
            "finding_set_id": "fs-scope-02",
            "reported_findings": [
                {
                    "id": "f-fresh",
                    "severity": "suggestion",
                    "category": "documentation",
                    "target_refs": ["item-a"],
                    "issue": "Same theme as prior",
                    "recommended_change": "Clarify",
                    "status": "unresolved",
                }
            ],
            "review_completed": True,
            "summary": "fresh scope",
        },
        stage="scope_review",
    )
    assert outcome in {"pending", "changes_requested", "approved"}
    ids = [finding.id for finding in updated.findings]
    assert "f-prior" in ids
    assert "f-fresh" in ids
    assert len(merged) >= 1


def test_loop_revise_at_persists_through_store_roundtrip(tmp_path: Path) -> None:
    from top_down_planning.domain.models import Plan, PlanItem
    from top_down_planning.orchestrator.phases import PLANNING

    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T000001-a1b2c3"
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
        **create_run_kwargs(tmp_path, resolved_config={"run": {"output_goal": "G"}}),
        phase=PLANNING,
    )
    loop = ReviewLoop(
        id="review-focused-plan-01",
        type="focused_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "focused_plan", "item_ids": ["item-root"]},
        revise_at="minor",
    )
    save_review_payload(store, run_id, loop.to_dict())
    loaded = ReviewLoop.from_dict(store.load_review(run_id, loop.id))
    assert loaded.revise_at == "minor"
