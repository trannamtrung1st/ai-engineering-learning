"""Config loop bounds for mandatory review gates."""

from __future__ import annotations

from top_down_planning.config.defaults import ALLOWED_OVERRIDE_PATHS, DEFAULT_CONFIG
from top_down_planning.domain.reviews import (
    FindingVerificationEntry,
    FindingVerificationResult,
    MandatoryReviewLimits,
    ReviewFinding,
    ScopeReviewResult,
    approval_allowed_under_loop_bounds,
    build_limit_reached_terminal,
    mandatory_review_limits_from_config,
    reject_approval_when_budget_exhausted,
    review_gate_limits_from_config,
)
from top_down_planning.schema_docs import show_schema


DIGEST = "artifact-digest-1"


def _open_finding() -> ReviewFinding:
    return ReviewFinding(
        id="finding-open",
        severity="blocker",
                category="other",
        target_refs=["item-a"],
        issue="Still open",
        recommended_change="Fix it",
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


def _clear_blocker() -> ScopeReviewResult:
    return ScopeReviewResult(
        target_digest=DIGEST,
        decision="approved",
        scope_id="whole_plan",
    )


def test_default_mandatory_review_limits_include_stage_budgets() -> None:
    plan_limits = DEFAULT_CONFIG["limits"]["whole_plan_review"]
    output_limits = DEFAULT_CONFIG["limits"]["whole_output_review"]
    provider_limits = DEFAULT_CONFIG["limits"]["provider"]
    assert provider_limits["max_retries_per_call"] == 2
    assert provider_limits["turn_idle_timeout_seconds"] == 2.0
    assert provider_limits["max_stream_json_record_bytes"] == 1048576
    assert (
        "limits.provider.max_stream_json_record_bytes" in ALLOWED_OVERRIDE_PATHS
    )
    assert plan_limits["max_revision_cycles"] == 5
    assert plan_limits["max_scope_review_rounds"] == 3
    assert "max_blocker_review_rounds" not in plan_limits
    assert output_limits["max_revision_cycles"] == 5
    assert output_limits["max_scope_review_rounds"] == 3
    assert "max_blocker_review_rounds" not in output_limits
    assert (
        "limits.whole_plan_review.max_scope_review_rounds" in ALLOWED_OVERRIDE_PATHS
    )
    assert (
        "limits.whole_output_review.max_scope_review_rounds" in ALLOWED_OVERRIDE_PATHS
    )
    assert "limits.review.max_agent_turns_per_gate" in ALLOWED_OVERRIDE_PATHS
    assert review_gate_limits_from_config(DEFAULT_CONFIG) == {
        "max_agent_turns_per_gate": 5,
    }


def test_config_schema_documents_review_gate_turn_limit() -> None:
    review_limits = show_schema("config")["properties"]["limits"]["properties"]["review"]
    assert "max_agent_turns_per_gate" in review_limits["properties"]


def test_config_schema_documents_stream_json_record_limit() -> None:
    provider = show_schema("config")["properties"]["limits"]["properties"]["provider"]
    props = provider["properties"]
    assert "max_stream_json_record_bytes" in props
    assert props["max_stream_json_record_bytes"]["type"] == "integer"
    assert props["max_stream_json_record_bytes"]["minimum"] == 1
    assert props["max_stream_json_record_bytes"]["default"] == 1048576
    description = props["max_stream_json_record_bytes"]["description"]
    assert "TDP configuration requires an integer >= 1" in description
    assert "including the terminating newline" in description
    assert "invalid or non-positive" in description
    assert "Values below 1 are ignored" not in description


def test_config_schema_documents_scope_review_rounds() -> None:
    limits = show_schema("config")["properties"]["limits"]["properties"]
    for key in ("whole_plan_review", "whole_output_review"):
        props = limits[key]["properties"]
        assert "max_revision_cycles" in props
        assert "max_scope_review_rounds" in props
        assert props["max_scope_review_rounds"]["type"] == "integer"


def test_mandatory_review_limits_from_config_defaults_and_overrides() -> None:
    defaults = mandatory_review_limits_from_config({}, "whole_plan")
    assert defaults == MandatoryReviewLimits()
    assert defaults.to_dict() == {
        "max_revision_cycles": 5,
        "max_scope_review_rounds": 3,
    }

    loaded = mandatory_review_limits_from_config(
        {
            "limits": {
                "whole_output_review": {
                    "max_revision_cycles": 2,
                    "max_scope_review_rounds": 1,
                }
            }
        },
        "whole_output",
    )
    assert loaded.max_revision_cycles == 2
    assert loaded.max_scope_review_rounds == 1


def test_limit_reached_preserves_findings_and_rejects_approval() -> None:
    limits = MandatoryReviewLimits(max_revision_cycles=1, max_scope_review_rounds=1)
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
        scope_review_rounds=0,
        limits=limits,
        findings=findings,
    )
    assert exhausted is not None
    assert exhausted.exhausted_budget == "verification_revision"
    assert exhausted.decision == "blocked"

    blocker_exhausted = reject_approval_when_budget_exhausted(
        revision_cycles=0,
        scope_review_rounds=1,
        limits=limits,
        findings=findings,
    )
    assert blocker_exhausted is not None
    assert blocker_exhausted.exhausted_budget == "scope_review"


def test_exhausted_budget_never_approves_even_when_stages_clear() -> None:
    limits = MandatoryReviewLimits(max_revision_cycles=1, max_scope_review_rounds=1)
    findings = [_open_finding()]
    assert (
        approval_allowed_under_loop_bounds(
            revision_cycles=1,
            scope_review_rounds=0,
            limits=limits,
            verification=_clear_verification(),
            scope_review_result=_clear_blocker(),
            current_artifact_digest=DIGEST,
            findings=findings,
            revise_at="blocker",
        )
        is False
    )
    assert (
        approval_allowed_under_loop_bounds(
            revision_cycles=0,
            scope_review_rounds=1,
            limits=limits,
            verification=_clear_verification(),
            scope_review_result=_clear_blocker(),
            current_artifact_digest=DIGEST,
            findings=findings,
            revise_at="blocker",
        )
        is False
    )
    assert (
        approval_allowed_under_loop_bounds(
            revision_cycles=0,
            scope_review_rounds=0,
            limits=limits,
            verification=_clear_verification(),
            scope_review_result=_clear_blocker(),
            current_artifact_digest=DIGEST,
            findings=[],
            revise_at="blocker",
        )
        is True
    )


def test_prepare_limit_reached_retry_preserves_scope_budget() -> None:
    from tests.helpers import make_review_loop
    from top_down_planning.domain.reviews import (
        is_limit_reached_review_loop,
        is_review_respond_closed,
        is_terminal_review_loop,
        prepare_limit_reached_retry,
    )

    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=1,
        scope={"kind": "whole_plan"},
        status="blocked",
        lifecycle_status="limit_reached",
        active_stage="finding_verification",
        scope_review_rounds=15,
        revision_cycles=2,
        gate_agent_turns=3,
        exhausted_budget="scope_review",
        revise_at="blocker",
    )
    assert is_limit_reached_review_loop(loop) is True
    assert is_terminal_review_loop(loop) is True
    assert is_review_respond_closed(loop) is True

    revived = prepare_limit_reached_retry(loop)
    assert revived.scope_review_rounds == 15
    assert revived.revision_cycles == 2
    assert revived.gate_agent_turns == 0
    assert revived.lifecycle_status == "findings_closed"
    assert revived.status == "approved"
    assert revived.exhausted_budget is None
    assert is_limit_reached_review_loop(revived) is False
    assert is_terminal_review_loop(revived) is False


def test_limit_reached_loop_is_terminal_for_conflict_detection() -> None:
    from tests.helpers import make_review_loop
    from top_down_planning.domain.reviews import (
        find_conflicting_active_review_loops,
        is_terminal_review_loop,
    )

    limit_reached = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess-wp",
        target_revision=0,
        scope={"kind": "whole_plan"},
        status="blocked",
        lifecycle_status="limit_reached",
        exhausted_budget="scope_review",
        revise_at="blocker",
    )
    focused = make_review_loop(
        id="review-focused-plan-01",
        type="focused_plan",
        reviewer_session_id="sess-fp",
        target_revision=0,
        scope={"kind": "focused_plan", "item_ids": ["item-a"]},
        status="changes_requested",
        revise_at="blocker",
    )
    assert is_terminal_review_loop(limit_reached) is True
    assert find_conflicting_active_review_loops(
        [limit_reached.to_dict(), focused.to_dict()]
    ) == []


def test_prepare_limit_reached_retry_preserves_revision_budget() -> None:
    from tests.helpers import make_review_loop
    from top_down_planning.domain.reviews import prepare_limit_reached_retry

    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=1,
        scope={"kind": "whole_plan"},
        status="blocked",
        lifecycle_status="limit_reached",
        active_stage="finding_verification",
        scope_review_rounds=3,
        revision_cycles=5,
        exhausted_budget="verification_revision",
        revise_at="blocker",
        findings=[
            {
                "id": "finding-1",
                "severity": "blocker",
                "category": "correctness",
                "target_refs": ["item-a"],
                "issue": "open",
                "recommended_change": "fix",
                "status": "unresolved",
            }
        ],
    )
    revived = prepare_limit_reached_retry(loop)
    assert revived.revision_cycles == 5
    assert revived.scope_review_rounds == 3
    assert revived.lifecycle_status == "revision_in_progress"
    assert revived.status == "pending"
    assert revived.exhausted_budget is None