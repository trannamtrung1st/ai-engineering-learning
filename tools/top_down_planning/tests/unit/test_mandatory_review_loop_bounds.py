"""Config Loop Bounds for mandatory two-stage review."""

from __future__ import annotations

from top_down_planning.config.defaults import ALLOWED_OVERRIDE_PATHS, DEFAULT_CONFIG
from top_down_planning.domain.reviews import (
    FindingVerificationEntry,
    FindingVerificationResult,
    MandatoryReviewLimits,
    ReviewFinding,
    ScopeBlockerReviewResult,
    approval_allowed_under_loop_bounds,
    build_limit_reached_terminal,
    mandatory_review_limits_from_config,
    reject_approval_when_budget_exhausted,
)
from top_down_planning.schema_docs import show_schema


DIGEST = "artifact-digest-1"


def _open_finding() -> ReviewFinding:
    return ReviewFinding(
        id="finding-open",
        importance="blocking",
        target_refs=["item-a"],
        issue="Still open",
        required_change="Fix it",
        status="unresolved",
    )


def _clear_verification() -> FindingVerificationResult:
    return FindingVerificationResult(
        target_digest=DIGEST,
        decision="verified",
        finding_set_id="fs-1",
        finding_results=[
            FindingVerificationEntry(finding_id="finding-1", disposition="resolved")
        ],
    )


def _clear_blocker() -> ScopeBlockerReviewResult:
    return ScopeBlockerReviewResult(
        target_digest=DIGEST,
        decision="approve",
        scope_id="whole_plan",
    )


def test_default_mandatory_review_limits_include_stage_budgets() -> None:
    plan_limits = DEFAULT_CONFIG["limits"]["whole_plan_review"]
    output_limits = DEFAULT_CONFIG["limits"]["whole_output_review"]
    assert plan_limits["max_revision_cycles"] == 5
    assert plan_limits["max_blocker_review_rounds"] == 3
    assert output_limits["max_revision_cycles"] == 5
    assert output_limits["max_blocker_review_rounds"] == 3
    assert (
        "limits.whole_plan_review.max_blocker_review_rounds" in ALLOWED_OVERRIDE_PATHS
    )
    assert (
        "limits.whole_output_review.max_blocker_review_rounds" in ALLOWED_OVERRIDE_PATHS
    )


def test_config_schema_documents_blocker_review_rounds() -> None:
    limits = show_schema("config")["properties"]["limits"]["properties"]
    for key in ("whole_plan_review", "whole_output_review"):
        props = limits[key]["properties"]
        assert "max_revision_cycles" in props
        assert "max_blocker_review_rounds" in props
        assert props["max_blocker_review_rounds"]["type"] == "integer"


def test_mandatory_review_limits_from_config_defaults_and_overrides() -> None:
    defaults = mandatory_review_limits_from_config({}, "whole_plan")
    assert defaults == MandatoryReviewLimits()
    assert defaults.to_dict() == {
        "max_revision_cycles": 5,
        "max_blocker_review_rounds": 3,
    }

    loaded = mandatory_review_limits_from_config(
        {
            "limits": {
                "whole_output_review": {
                    "max_revision_cycles": 2,
                    "max_blocker_review_rounds": 1,
                }
            }
        },
        "whole_output",
    )
    assert loaded.max_revision_cycles == 2
    assert loaded.max_blocker_review_rounds == 1


def test_limit_reached_preserves_findings_and_rejects_approval() -> None:
    limits = MandatoryReviewLimits(max_revision_cycles=1, max_blocker_review_rounds=1)
    findings = [_open_finding()]
    terminal = build_limit_reached_terminal(
        exhausted_budget="verification_revision",
        findings=findings,
        limits=limits,
    )
    assert terminal.lifecycle_status == "limit_reached"
    assert terminal.decision == "blocked"
    assert terminal.to_dict()["approved"] is False
    assert [finding.id for finding in terminal.findings] == ["finding-open"]
    assert terminal.findings[0].status == "unresolved"
    assert terminal.to_dict()["approved"] is False

    exhausted = reject_approval_when_budget_exhausted(
        revision_cycles=1,
        blocker_review_rounds=0,
        limits=limits,
        findings=findings,
    )
    assert exhausted is not None
    assert exhausted.exhausted_budget == "verification_revision"
    assert exhausted.decision == "blocked"

    blocker_exhausted = reject_approval_when_budget_exhausted(
        revision_cycles=0,
        blocker_review_rounds=1,
        limits=limits,
        findings=findings,
    )
    assert blocker_exhausted is not None
    assert blocker_exhausted.exhausted_budget == "blocker_review"


def test_exhausted_budget_never_approves_even_when_stages_clear() -> None:
    limits = MandatoryReviewLimits(max_revision_cycles=1, max_blocker_review_rounds=1)
    findings = [_open_finding()]
    assert (
        approval_allowed_under_loop_bounds(
            revision_cycles=1,
            blocker_review_rounds=0,
            limits=limits,
            verification=_clear_verification(),
            blocker_review=_clear_blocker(),
            current_artifact_digest=DIGEST,
            findings=findings,
        )
        is False
    )
    assert (
        approval_allowed_under_loop_bounds(
            revision_cycles=0,
            blocker_review_rounds=1,
            limits=limits,
            verification=_clear_verification(),
            blocker_review=_clear_blocker(),
            current_artifact_digest=DIGEST,
            findings=findings,
        )
        is False
    )
    assert (
        approval_allowed_under_loop_bounds(
            revision_cycles=0,
            blocker_review_rounds=0,
            limits=limits,
            verification=_clear_verification(),
            blocker_review=_clear_blocker(),
            current_artifact_digest=DIGEST,
            findings=[],
        )
        is True
    )
