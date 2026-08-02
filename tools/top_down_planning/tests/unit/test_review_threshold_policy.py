"""Domain tests for threshold-aware required/optional finding policy."""

from __future__ import annotations

import pytest

from top_down_planning.domain.reviews import (
    FindingAction,
    ReviewFinding,
    assert_owner_action_allowed_for_finding,
    findings_permit_approval,
    open_optional_findings_missing_owner_response,
    optional_open_findings,
    policy_observability_fields,
    required_open_findings,
)
from tests.helpers import make_review_loop


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
        open_optional_findings_missing_owner_response(findings, actions, "major")
        == []
    )


def test_approval_rejected_when_optional_missing_owner_response() -> None:
    findings = [_finding("f-minor", severity="minor")]
    assert findings_permit_approval(findings, [], "major") is False
    missing = open_optional_findings_missing_owner_response(findings, [], "major")
    assert [finding.id for finding in missing] == ["f-minor"]


def test_fix_and_challenge_complete_handoff_but_block_approval() -> None:
    findings = [_finding("f-minor", severity="minor")]
    fix_action = _action("f-minor", "fix")
    challenge_action = FindingAction(
        finding_id="f-minor",
        action="challenge",
        rationale="Not applicable",
        actor_role="producer",
        artifact_revision=1,
        finding_set_id="fs-1",
        proposed_disposition="invalid",
    )

    assert open_optional_findings_missing_owner_response(findings, [fix_action], "major") == []
    assert findings_permit_approval(findings, [fix_action], "major") is False

    assert (
        open_optional_findings_missing_owner_response(
            findings,
            [challenge_action],
            "major",
        )
        == []
    )
    assert findings_permit_approval(findings, [challenge_action], "major") is False


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


def test_finding_set_scoped_handoff_ignores_prior_set_actions() -> None:
    findings = [_finding("f-minor", severity="minor")]
    prior_action = _action("f-minor", "defer", finding_set_id="fs-old")
    assert open_optional_findings_missing_owner_response(
        findings,
        [prior_action],
        "major",
        finding_set_id="fs-new",
    ) == findings


def test_active_set_empty_skips_carried_optional_handoff() -> None:
    from top_down_planning.domain.reviews import (
        needs_advisory_handoff,
        open_optional_findings_missing_owner_response_in_active_set,
    )

    findings = [_finding("f-minor", severity="minor")]
    defer = _action("f-minor", "defer", finding_set_id="fs-01")
    assert (
        open_optional_findings_missing_owner_response_in_active_set(
            findings,
            [defer],
            "major",
            finding_set_id="fs-02",
            finding_ids_in_active_set=set(),
        )
        == []
    )
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        target_revision=0,
        scope={"kind": "whole_plan"},
        status="approved",
        revise_at="major",
        finding_set_id="fs-02",
        lifecycle_status="scope_review_pending",
        active_stage="scope_review",
        findings=[finding.to_dict() for finding in findings],
        finding_actions=[defer.to_dict()],
        finding_ids_by_set={"fs-01": ["f-minor"]},
        advisory_handoffs_completed=["fs-01"],
    )
    assert not needs_advisory_handoff(loop)


def test_policy_observability_fields_scope_clear_omits_carried_missing() -> None:
    from top_down_planning.domain.reviews import policy_observability_fields_for_loop

    findings = [_finding("f-minor", severity="minor")]
    defer = _action("f-minor", "defer", finding_set_id="fs-01")
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        target_revision=0,
        scope={"kind": "whole_plan"},
        status="pending",
        revise_at="major",
        finding_set_id="fs-02",
        lifecycle_status="scope_review_pending",
        active_stage="scope_review",
        findings=[finding.to_dict() for finding in findings],
        finding_actions=[defer.to_dict()],
        finding_ids_by_set={"fs-01": ["f-minor"]},
    )
    fields = policy_observability_fields_for_loop(loop)
    assert fields["optional_finding_ids_missing_owner_response"] == []


def test_scope_discovery_new_optional_still_needs_handoff() -> None:
    from top_down_planning.domain.reviews import (
        allocate_discovery_finding_set_id,
        apply_discovery_response,
        needs_advisory_handoff,
    )

    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        target_revision=0,
        scope={"kind": "whole_plan"},
        status="pending",
        revise_at="major",
        finding_set_id="fs-01",
        lifecycle_status="scope_review_pending",
        active_stage="scope_review",
        findings=[],
        finding_actions=[],
        finding_ids_by_set={},
    )
    loop, finding_set_id = allocate_discovery_finding_set_id(loop)
    loop, _, outcome = apply_discovery_response(
        loop,
        {
            "finding_set_id": finding_set_id,
            "reported_findings": [_finding("f-new", severity="minor").to_dict()],
            "review_completed": True,
            "summary": "new polish issue",
            "target_digest": "digest-1",
        },
        stage="scope_review",
    )
    assert outcome == "pending"
    assert loop.status == "advisory_pending"
    assert needs_advisory_handoff(loop)


def test_complete_advisory_handoff_skips_empty_scope_pass() -> None:
    from top_down_planning.domain.reviews import (
        complete_advisory_handoff_if_owner_responses_recorded,
    )

    findings = [_finding("f-minor", severity="minor")]
    defer = _action("f-minor", "defer", finding_set_id="fs-01")
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        target_revision=0,
        scope={"kind": "whole_plan"},
        status="pending",
        revise_at="major",
        finding_set_id="fs-02",
        lifecycle_status="scope_review_pending",
        active_stage="scope_review",
        findings=[finding.to_dict() for finding in findings],
        finding_actions=[defer.to_dict()],
        finding_ids_by_set={"fs-01": ["f-minor"]},
        advisory_handoffs_completed=["fs-01"],
    )
    completed = complete_advisory_handoff_if_owner_responses_recorded(loop)
    assert completed.advisory_handoffs_completed == ["fs-01"]


def test_mandatory_scope_clear_approves_with_carried_deferred_optional() -> None:
    from top_down_planning.agent_tool.review_discovery import (
        apply_mandatory_discovery_response,
    )
    from top_down_planning.config.defaults import DEFAULT_CONFIG
    from top_down_planning.domain.mandatory_audit_passes import WHOLE_PLAN_AUDIT_PASS_IDS
    from top_down_planning.orchestrator.review_analysis_context import rubric_items_with_ids

    findings = [_finding("f-minor", severity="minor")]
    defer = _action("f-minor", "defer", finding_set_id="fs-01")
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        target_revision=0,
        scope={"kind": "whole_plan"},
        status="pending",
        revise_at="major",
        finding_set_id="fs-02",
        lifecycle_status="scope_review_pending",
        active_stage="scope_review",
        findings=[finding.to_dict() for finding in findings],
        finding_actions=[defer.to_dict()],
        finding_ids_by_set={"fs-01": ["f-minor"]},
        advisory_handoffs_completed=["fs-01"],
        review_record_schema_version=2,
        review_contract_version=2,
    )
    rubric_items = rubric_items_with_ids(
        [str(item) for item in DEFAULT_CONFIG["review"]["whole_plan"]["rubric"]]
    )
    rubric_ids = [item["id"] for item in rubric_items]
    updated, _merged, outcome, _events = apply_mandatory_discovery_response(
        loop,
        {
            "finding_set_id": "fs-02",
            "review_completed": True,
            "target_digest": "digest-1",
            "scope_id": "whole_plan",
            "summary": "Scope clear.",
            "reported_findings": [],
            "audit_attestation": {
                "artifact_revision": 0,
                "artifact_digest": "digest-1",
                "passes": [
                    {
                        "pass_id": pass_id,
                        "completed": True,
                        "scope_id": "whole-plan-active-v1",
                        "search_dimensions": ["acceptance"],
                        "inspected_refs": ["active-items:*"],
                        "rubric_item_ids": rubric_ids,
                        "summary": f"Completed {pass_id}.",
                    }
                    for pass_id in WHOLE_PLAN_AUDIT_PASS_IDS
                ],
            },
            "finding_families": [],
        },
        stage="scope_review",
        review_type="whole_plan",
        artifact_revision=0,
        artifact_digest="digest-1",
        rubric=[str(item) for item in DEFAULT_CONFIG["review"]["whole_plan"]["rubric"]],
    )
    assert outcome == "approved"
    assert updated.status == "approved"


def test_findings_permit_approval_for_loop_scope_carried_defer() -> None:
    from top_down_planning.domain.reviews import findings_permit_approval_for_loop

    findings = [_finding("f-minor", severity="minor")]
    defer = _action("f-minor", "defer", finding_set_id="fs-01")
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        target_revision=0,
        scope={"kind": "whole_plan"},
        status="pending",
        revise_at="major",
        finding_set_id="fs-02",
        lifecycle_status="scope_review_pending",
        active_stage="scope_review",
        findings=[finding.to_dict() for finding in findings],
        finding_actions=[defer.to_dict()],
        finding_ids_by_set={"fs-01": ["f-minor"]},
    )
    assert findings_permit_approval_for_loop(loop) is True


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
        "optional_finding_ids_missing_owner_response": ["f-minor"],
        "optional_finding_ids_requiring_verification": [],
    }
