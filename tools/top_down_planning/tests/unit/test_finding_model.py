"""Domain tests for finding model, finding_actions, and revise_at persistence."""

from __future__ import annotations

import pytest

from tests.helpers import review_loop_dict_with_binding, make_review_loop

from top_down_planning.domain.reviews import (
    CURRENT_REVIEW_SCHEMA_VERSION,
    FindingAction,
    ReviewFinding,
    ReviewLoop,
    parse_finding_action,
    validate_reopens_finding_id,
    with_loop_revise_at,
)


def test_finding_from_dict_requires_severity_category_and_recommended_change() -> None:
    blocking = ReviewFinding.from_dict(
        {
            "id": "f-block",
            "severity": "blocker",
            "category": "correctness",
            "target_refs": ["item-a"],
            "issue": "Broken",
            "recommended_change": "Fix it",
            "status": "unresolved",
        }
    )
    assert blocking.severity == "blocker"
    assert blocking.category == "correctness"
    assert blocking.recommended_change == "Fix it"

    with pytest.raises(ValueError, match="finding requires category"):
        ReviewFinding.from_dict(
            {
                "id": "f-missing-category",
                "severity": "blocker",
                "target_refs": ["item-a"],
                "issue": "Broken",
                "recommended_change": "Fix it",
            }
        )

    with pytest.raises(ValueError, match="legacy finding field importance"):
        ReviewFinding.from_dict(
            {
                "id": "f-legacy",
                "importance": "blocking",
                "severity": "blocker",
                "category": "correctness",
                "target_refs": [],
                "issue": "x",
                "recommended_change": "y",
            }
        )


def test_finding_to_dict_emits_canonical_fields() -> None:
    finding = ReviewFinding(
        id="f-1",
        severity="major",
        category="correctness",
        target_refs=["item-a"],
        issue="Gap",
        recommended_change="Cover it",
        evidence=["obs-1"],
        reopens_finding_id=None,
    )
    payload = finding.to_dict()
    assert payload["severity"] == "major"
    assert payload["category"] == "correctness"
    assert payload["recommended_change"] == "Cover it"
    assert payload["evidence"] == ["obs-1"]
    assert "importance" not in payload
    assert "required_change" not in payload


def test_reopens_finding_id_requires_closed_same_loop_finding() -> None:
    closed = ReviewFinding(
        id="f-old",
        severity="major",
        category="correctness",
        target_refs=["item-a"],
        issue="Old",
        recommended_change="Fix",
        status="resolved",
    )
    open_finding = ReviewFinding(
        id="f-open",
        severity="major",
        category="correctness",
        target_refs=["item-a"],
        issue="Open",
        recommended_change="Fix",
        status="unresolved",
    )
    reopen = ReviewFinding(
        id="f-new",
        severity="major",
        category="correctness",
        target_refs=["item-a"],
        issue="Again",
        recommended_change="Fix",
        reopens_finding_id="f-old",
    )
    validate_reopens_finding_id(reopen, [closed, open_finding])

    with pytest.raises(ValueError, match="closed finding"):
        validate_reopens_finding_id(
            ReviewFinding(
                id="f-bad",
                severity="major",
                category="other",
                target_refs=[],
                issue="x",
                recommended_change="y",
                reopens_finding_id="f-open",
            ),
            [closed, open_finding],
        )


def test_finding_action_challenge_requires_proposed_disposition() -> None:
    action = parse_finding_action(
        {
            "finding_id": "f-1",
            "action": "defer",
            "rationale": "Out of scope for this pass.",
            "actor_role": "producer",
            "artifact_revision": 2,
            "finding_set_id": "fs-1",
        }
    )
    assert action.action == "defer"

    challenge = parse_finding_action(
        {
            "finding_id": "f-1",
            "action": "challenge",
            "challenge_reason": "duplicate",
            "proposed_disposition": "superseded",
            "superseded_by_finding_id": "f-old",
            "rationale": "Duplicate of earlier finding.",
            "actor_role": "planner",
            "artifact_revision": 3,
            "finding_set_id": "fs-2",
        }
    )
    assert challenge.proposed_disposition == "superseded"
    assert challenge.challenge_reason == "duplicate"
    assert challenge.superseded_by_finding_id == "f-old"


def test_review_loop_persists_revise_at_actions_and_schema_version() -> None:
    loop = make_review_loop(
        id="loop-1",
        type="whole_plan",
        reviewer_session_id=None,
        target_revision=1,
        scope={"kind": "whole_plan"},
        revise_at="major",
        finding_actions=[
            FindingAction(
                finding_id="f-1",
                action="defer",
                rationale="Later",
                actor_role="producer",
                artifact_revision=1,
                finding_set_id="fs-1",
            )
        ],
        review_incomplete=None,
    )
    payload = loop.to_dict()
    assert payload["review_schema_version"] == CURRENT_REVIEW_SCHEMA_VERSION
    assert payload["revise_at"] == "major"
    restored = ReviewLoop.from_dict(payload)
    assert restored.revise_at == "major"


def test_revise_at_immutable_after_loop_creation() -> None:
    loop = make_review_loop(
        id="loop-1",
        type="focused_plan",
        reviewer_session_id=None,
        target_revision=1,
        scope={"kind": "focused_plan", "item_ids": ["item-a"]},
        revise_at="blocker",
    )
    assert with_loop_revise_at(loop, "blocker") is loop
    with pytest.raises(ValueError, match="immutable"):
        with_loop_revise_at(loop, "major")


def test_review_loop_load_requires_revise_at() -> None:
    with pytest.raises(ValueError, match="missing required revise_at"):
        ReviewLoop.from_dict(review_loop_dict_with_binding(
            {
                "id": "legacy-loop",
                "type": "focused_output",
                "target_revision": 2,
                "scope": {"kind": "focused_output", "item_ids": ["item-a"]},
                "status": "pending",
                "findings": [],
            }
        ))
