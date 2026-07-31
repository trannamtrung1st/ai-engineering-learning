"""Domain tests for threshold-aware required/optional finding policy."""

from __future__ import annotations

import pytest

from top_down_planning.domain.reviews import (
    FindingAction,
    ReviewFinding,
    assert_owner_action_allowed_for_finding,
    findings_permit_approval,
    open_optional_findings_without_owner_action,
    optional_open_findings,
    policy_observability_fields,
    required_open_findings,
)


def _finding(
    finding_id: str,
    *,
    severity: str,
    status: str = "unresolved",
) -> ReviewFinding:
    return ReviewFinding(
        id=finding_id,
        severity=severity,  # type: ignore[arg-type]
        category="other",
        target_refs=["item-a"],
        issue=f"issue-{finding_id}",
        recommended_change="fix",
        status=status,  # type: ignore[arg-type]
    )


def _action(
    finding_id: str,
    action: str,
    *,
    finding_set_id: str = "fs-1",
) -> FindingAction:
    return FindingAction(
        finding_id=finding_id,
        action=action,  # type: ignore[arg-type]
        rationale="Acknowledged for this pass.",
        actor_role="producer",
        artifact_revision=1,
        finding_set_id=finding_set_id,
    )


def test_required_versus_optional_partitioning() -> None:
    findings = [
        _finding("f-blocker", severity="blocker"),
        _finding("f-major", severity="major"),
        _finding("f-minor", severity="minor"),
        _finding("f-suggestion", severity="suggestion"),
        _finding("f-closed", severity="major", status="resolved"),
    ]

    required = required_open_findings(findings, "major")
    optional = optional_open_findings(findings, "major")
    assert [finding.id for finding in required] == ["f-blocker", "f-major"]
    assert [finding.id for finding in optional] == ["f-minor", "f-suggestion"]

    required_blocker = required_open_findings(findings, "blocker")
    optional_blocker = optional_open_findings(findings, "blocker")
    assert [finding.id for finding in required_blocker] == ["f-blocker"]
    assert [finding.id for finding in optional_blocker] == [
        "f-major",
        "f-minor",
        "f-suggestion",
    ]


def test_approval_rejected_with_open_required_findings() -> None:
    findings = [
        _finding("f-major", severity="major"),
        _finding("f-minor", severity="minor"),
    ]
    actions = [_action("f-minor", "defer")]
    assert findings_permit_approval(findings, actions, "major") is False


def test_approval_permitted_when_optionals_deferred_or_accepted() -> None:
    findings = [
        _finding("f-minor", severity="minor"),
        _finding("f-suggestion", severity="suggestion"),
    ]
    actions = [
        _action("f-minor", "defer"),
        _action("f-suggestion", "accept_as_is"),
    ]
    assert findings_permit_approval(findings, actions, "major") is True
    assert (
        open_optional_findings_without_owner_action(findings, actions, "major")
        == []
    )


def test_approval_rejected_when_optional_unacknowledged() -> None:
    findings = [_finding("f-minor", severity="minor")]
    assert findings_permit_approval(findings, [], "major") is False
    unacked = open_optional_findings_without_owner_action(findings, [], "major")
    assert [finding.id for finding in unacked] == ["f-minor"]


def test_required_finding_cannot_be_deferred_or_accepted() -> None:
    required = _finding("f-major", severity="major")
    with pytest.raises(ValueError, match="cannot use action 'defer'"):
        assert_owner_action_allowed_for_finding(required, "defer", "major")
    with pytest.raises(ValueError, match="cannot use action 'accept_as_is'"):
        assert_owner_action_allowed_for_finding(required, "accept_as_is", "major")
    assert assert_owner_action_allowed_for_finding(required, "fix", "major") == "fix"
    assert (
        assert_owner_action_allowed_for_finding(required, "challenge", "major")
        == "challenge"
    )

    optional = _finding("f-minor", severity="minor")
    assert assert_owner_action_allowed_for_finding(optional, "defer", "major") == "defer"


def test_policy_observability_fields() -> None:
    findings = [
        _finding("f-major", severity="major"),
        _finding("f-minor", severity="minor"),
    ]
    fields = policy_observability_fields(findings, [], "major")
    assert fields == {
        "revise_at": "major",
        "finding_count": 2,
        "required_open_finding_count": 1,
        "optional_open_finding_count": 1,
        "required_open_finding_ids": ["f-major"],
        "optional_open_finding_ids": ["f-minor"],
        "unacknowledged_optional_finding_ids": ["f-minor"],
    }
