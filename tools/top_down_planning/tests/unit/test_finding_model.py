"""Domain tests for finding model, finding_actions, and legacy migration."""

from __future__ import annotations

import pytest

from top_down_planning.domain.reviews import (
    CURRENT_REVIEW_SCHEMA_VERSION,
    FindingAction,
    ReviewFinding,
    ReviewLoop,
    parse_finding_action,
    validate_reopens_finding_id,
    with_loop_revise_at,
)


def test_legacy_importance_maps_on_read() -> None:
    blocking = ReviewFinding.from_dict(
        {
            "id": "f-block",
            "importance": "blocking",
            "target_refs": ["item-a"],
            "issue": "Broken",
            "required_change": "Fix it",
            "status": "unresolved",
        }
    )
    assert blocking.severity == "blocker"
    assert blocking.category == "other"
    assert blocking.recommended_change == "Fix it"
    assert blocking.importance == "blocking"
    assert blocking.required_change == "Fix it"

    advisory = ReviewFinding.from_dict(
        {
            "id": "f-adv",
            "importance": "advisory",
            "target_refs": [],
            "issue": "Nit",
            "required_change": "Polish",
        }
    )
    assert advisory.severity == "minor"
    assert advisory.category == "other"


def test_new_writes_emit_only_new_shape() -> None:
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
    assert "importance" not in payload
    assert "required_change" not in payload
    assert payload["severity"] == "major"
    assert payload["category"] == "correctness"
    assert payload["recommended_change"] == "Cover it"
    assert payload["evidence"] == ["obs-1"]


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

    with pytest.raises(ValueError, match="same loop"):
        validate_reopens_finding_id(
            ReviewFinding(
                id="f-bad",
                severity="major",
                category="other",
                target_refs=[],
                issue="x",
                recommended_change="y",
                reopens_finding_id="missing",
            ),
            [closed],
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
            "proposed_disposition": "superseded",
            "superseded_by_finding_id": "f-old",
            "rationale": "Duplicate of earlier finding.",
            "actor_role": "planner",
            "artifact_revision": 3,
            "finding_set_id": "fs-2",
        }
    )
    assert challenge.proposed_disposition == "superseded"
    assert challenge.superseded_by_finding_id == "f-old"

    with pytest.raises(ValueError, match="requires rationale"):
        parse_finding_action(
            {
                "finding_id": "f-1",
                "action": "accept_as_is",
                "actor_role": "producer",
                "artifact_revision": 1,
                "finding_set_id": "fs-1",
            }
        )

    with pytest.raises(ValueError, match="proposed_disposition"):
        parse_finding_action(
            {
                "finding_id": "f-1",
                "action": "challenge",
                "rationale": "Disagree",
                "actor_role": "producer",
                "artifact_revision": 1,
                "finding_set_id": "fs-1",
            }
        )


def test_review_loop_persists_revise_at_actions_and_schema_version() -> None:
    loop = ReviewLoop(
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
    assert payload["finding_actions"][0]["action"] == "defer"
    assert payload["review_incomplete"] is None

    restored = ReviewLoop.from_dict(payload)
    assert restored.revise_at == "major"
    assert restored.finding_actions[0].finding_id == "f-1"
    assert restored.review_schema_version == CURRENT_REVIEW_SCHEMA_VERSION


def test_revise_at_immutable_after_loop_creation() -> None:
    loop = ReviewLoop(
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


def test_legacy_loop_without_schema_version_loads() -> None:
    restored = ReviewLoop.from_dict(
        {
            "id": "legacy-loop",
            "type": "focused_output",
            "reviewer_session_id": None,
            "target_revision": 2,
            "scope": {"kind": "focused_output", "item_ids": ["item-a"]},
            "status": "pending",
            "findings": [
                {
                    "id": "f-1",
                    "importance": "blocking",
                    "target_refs": ["item-a"],
                    "issue": "Gap",
                    "required_change": "Fix",
                    "status": "unresolved",
                }
            ],
        }
    )
    assert restored.review_schema_version == CURRENT_REVIEW_SCHEMA_VERSION
    assert restored.findings[0].severity == "blocker"
    assert restored.revise_at is None
    assert restored.finding_actions == []
