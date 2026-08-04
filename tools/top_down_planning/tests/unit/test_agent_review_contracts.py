"""Agent review contracts, prompts, and package freshness for mandatory review gates."""

from __future__ import annotations

from pathlib import Path

import pytest

from dataclasses import replace

from core_tools.schema import validate_against_schema
from top_down_planning.agent_tool import RequestError, ReviewAgentService
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.reviews import (
    ReviewFinding,
    ReviewLoop,
    ScopeReviewResult,
    merge_scope_review_findings,
    merge_verification_findings,
    mandatory_stage_respond_decision,
    validate_mandatory_stage_decision,
)
from top_down_planning.orchestrator.mandatory_review_stages import (
    stage_package_fields,
    verification_recheck_request,
)
from top_down_planning.orchestrator.phases import WHOLE_PLAN_REVIEW
from top_down_planning.orchestrator.reviewer_session import (
    build_reviewer_protocol_instructions,
)
from top_down_planning.orchestrator.whole_plan_review import build_whole_plan_review_package
from top_down_planning.persistence import FileRunStore
from top_down_planning.schema_docs import PUBLIC_EXAMPLES, show_example, show_schema
from tests.helpers import (
    make_review_loop,
    save_review_payload,
    create_run_kwargs,
    grant_capability,
    mandatory_scope_review_respond_request,
    mandatory_plan_digest,
    minimal_resolved_config,
)

from top_down_planning.prompts.contexts import (
    FORBIDDEN_SCOPE_REVIEW_STAGE_LABELS,
    _format_forbidden_scope_review_phrase,
)
def test_review_respond_schema_accepts_stage_contracts() -> None:
    schema = show_schema("review-respond")
    assert "oneOf" in schema
    branches = schema["oneOf"]
    verification_branch = next(
        branch
        for branch in branches
        if branch.get("title") == "MandatoryFindingVerificationRespond"
    )
    disposition = verification_branch["properties"]["finding_results"]["items"][
        "properties"
    ]["disposition"]
    assert "partially_resolved" in disposition["enum"]

    for name in (
        "review-respond",
        "review-respond-focused-with-instance-ref",
        "review-respond-family-discovery-focused-plan",
        "review-respond-family-discovery-focused-output",
        "review-respond-verification",
        "review-respond-scope",
        "review-respond-family-discovery",
        "review-respond-family-verification",
    ):
        assert name in PUBLIC_EXAMPLES
        example = show_example(name)
        issues = validate_against_schema(example["payload"], schema)
        assert issues == [], (name, issues)


def test_focused_verification_example_uses_focused_output_loop() -> None:
    assert "review-respond-verification" in PUBLIC_EXAMPLES
    example = show_example("review-respond-verification")
    assert example["payload"]["loop_id"] == "review-focused-output-01"
    assert "focused" in example["description"].lower()


def test_scope_example_is_mandatory_whole_plan() -> None:
    scope = show_example("review-respond-scope")
    assert scope["payload"]["loop_id"] == "review-whole-plan-01"
    assert "audit_attestation" in scope["payload"]


def test_whole_plan_v2_respond_contract_requires_family_fields() -> None:
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=1,
        scope={"kind": "whole_plan"},
        review_record_schema_version=2,
        review_contract_version=2,
        finding_set_id="review-whole-plan-01-fs-01",
    )
    scope_fields = stage_package_fields(
        replace(loop, active_stage="scope_review")
    )
    required = scope_fields["respond_contract"]["required_fields"]
    assert "audit_attestation" in required
    assert "finding_families" in required
    assert "scope_id" not in required

    initial_fields = stage_package_fields(
        replace(loop, active_stage="initial_review")
    )
    assert "audit_attestation" in initial_fields["respond_contract"]["required_fields"]

    verification_fields = stage_package_fields(
        replace(loop, active_stage="finding_verification")
    )
    assert "family_results" in verification_fields["respond_contract"]["required_fields"]
    protocol = build_reviewer_protocol_instructions(
        stage="finding_verification",
        review_type="whole_plan",
    ).lower()
    assert "family_results" in protocol
    assert "verification_sweep" in protocol

    initial_fields = stage_package_fields(
        replace(loop, active_stage="initial_review")
    )
    assert initial_fields["initial_review_guidance"] == [
        "Follow protocol_instructions for mandatory whole_* initial_review behavior."
    ]
    initial_protocol = build_reviewer_protocol_instructions(
        stage="initial_review",
        review_type="whole_plan",
    ).lower()
    assert "audit_attestation" in initial_protocol
    assert "discovery_sweep" in initial_protocol


def test_review_respond_schema_rejects_cross_stage_fields() -> None:
    schema = show_schema("review-respond")

    initial_with_verification_fields = {
        "loop_id": "review-whole-plan-01",
        "target_revision": 0,
        "stage": "initial_review",
        "decision": "changes_requested",
        "findings": [],
        "finding_results": [],
    }
    assert validate_against_schema(initial_with_verification_fields, schema)

    focused_with_stage = {
        "loop_id": "review-focused-plan-01",
        "target_revision": 0,
        "stage": "initial_review",
        "decision": "approved",
        "findings": [],
    }
    assert validate_against_schema(focused_with_stage, schema)

    initial_approved_without_digest = {
        "loop_id": "review-whole-plan-01",
        "target_revision": 0,
        "stage": "initial_review",
        "decision": "approved",
        "findings": [],
    }
    assert validate_against_schema(initial_approved_without_digest, schema)

    verification_with_findings = {
        "loop_id": "review-whole-plan-01",
        "target_revision": 1,
        "stage": "finding_verification",
        "decision": "verified",
        "target_digest": "plan-digest-abc",
        "finding_set_id": "fs-1",
        "finding_results": [],
        "new_direct_side_effect_findings": [],
        "summary": "ok",
        "findings": [],
    }
    assert validate_against_schema(verification_with_findings, schema)


def test_stage_decision_validation_and_finding_resolution() -> None:
    assert validate_mandatory_stage_decision("finding_verification", "verified") == "verified"
    with pytest.raises(ValueError, match="unknown mandatory review stage"):
        validate_mandatory_stage_decision("scope_review", "approved")
    with pytest.raises(ValueError, match="finding_verification decisions"):
        validate_mandatory_stage_decision("finding_verification", "approved")

    verification_loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=1,
        scope={"kind": "whole_plan"},
        findings=[
            ReviewFinding(
                id="finding-1",
                severity="blocker",
                category="other",
                target_refs=["item-root"],
                issue="Gap",
                recommended_change="Fix",
                status="unresolved",
            )
        ],
        lifecycle_status="verification_pending",
        active_stage="finding_verification",
        finding_set_id="fs-1",
        revise_at="blocker",
    )
    verification = merge_verification_findings(
        verification_loop,
        {
            "stage": "finding_verification",
            "finding_results": [
                {
                    "finding_id": "finding-1",
                    "disposition": "resolved",
                    "evidence": ["ok"],
                    "direct_side_effects": [],
                }
            ],
            "new_direct_side_effect_findings": [],
            "target_digest": "digest-1",
            "finding_set_id": "fs-1",
            "decision": "verified",
        },
    )[0]
    assert [finding.id for finding in verification] == ["finding-1"]
    assert verification[0].status == "resolved"
    assert verification[0].issue == "Gap"

    scope_loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=1,
        scope={"kind": "whole_plan"},
    )
    reported = [
        ReviewFinding(
            id="finding-new",
            severity="blocker",
            category="other",
            target_refs=["item-a"],
            issue="Coverage gap",
            recommended_change="Add leaf",
            status="unresolved",
        )
    ]
    merged = merge_scope_review_findings(scope_loop, reported)
    assert merged[0].id == "finding-new"
    assert mandatory_stage_respond_decision(
        make_review_loop(
            id="review-whole-plan-01",
            type="whole_plan",
            reviewer_session_id="sess",
            target_revision=1,
            scope={"kind": "whole_plan"},
            status="changes_requested",
            active_stage="scope_review",
            scope_review_result={
                "stage": "scope_review",
                "decision": "changes_requested",
                "target_digest": "digest-1",
                "scope_id": "whole_plan",
                "reported_findings": [],
                "summary": "",
            },
        )
    ) == "changes_requested"


def test_scope_review_package_omits_prior_finding_framing(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T003301-003301"
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        kind="aggregate",
    )
    leaf = PlanItem(
        id="item-api",
        parent_id="item-root",
        order_key="0000000000",
        title="API",
        outcome="API exists.",
        kind="work",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver.",
        items={"item-root": root, "item-api": leaf},
    )
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
        phase=WHOLE_PLAN_REVIEW,
    )
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "whole_plan"},
        lifecycle_status="scope_review_pending",
        active_stage="scope_review",
        finding_set_id="review-whole-plan-01-fs-01",
        findings=[
            ReviewFinding(
                id="old",
                severity="blocker",
                category="other",
                target_refs=["item-api"],
                issue="old",
                recommended_change="fix",
                status="resolved",
            )
        ],
        scope_review_rounds=1,
    )
    package = build_whole_plan_review_package(
        run_id,
        store.load_run(run_id),
        minimal_resolved_config(),
        plan,
        loop,
    )
    assert package["stage"] == "scope_review"
    assert package["freshness"]["omit_prior_finding_framing"] is True
    assert package["freshness"]["include_prior_findings"] is False
    assert "findings" not in package
    assert package["finding_set_id"] == "review-whole-plan-01-fs-01"
    protocol = package["protocol_instructions"].lower()
    assert "scope_review" in protocol
    assert "fresh discovery" in protocol
    assert (
        f"do not call this a {_format_forbidden_scope_review_phrase()}"
        in protocol
    )
    for label in FORBIDDEN_SCOPE_REVIEW_STAGE_LABELS:
        assert label in protocol
    assert package["respond_contract"]["stage"] == "scope_review"


def test_verification_package_and_recheck_include_finding_guidance() -> None:
    loop = make_review_loop(
        id="review-whole-output-01",
        type="whole_output",
        reviewer_session_id="sess",
        target_revision=2,
        scope={"kind": "whole_output"},
        lifecycle_status="verification_pending",
        active_stage="finding_verification",
        finding_set_id="fs-1",
        findings=[],
    )
    fields = stage_package_fields(loop)
    assert fields["stage"] == "finding_verification"
    assert "verification_guidance" in fields
    assert fields["respond_contract"]["decisions"] == [
        "verified",
        "needs_revision",
        "blocked",
    ]
    recheck = verification_recheck_request(
        phase="whole_output_review",
        loop=loop,
        target_revision=2,
    )
    assert recheck["stage"] == "finding_verification"
    assert "verification_targets" in recheck
    assert "history_ref" in recheck
    assert "findings" not in recheck
    protocol = recheck["protocol_instructions"].lower()
    assert "finding_verification" in protocol
    assert "direct" in protocol and "side effect" in protocol


def test_verification_protocol_avoids_forbidden_names() -> None:
    protocol = build_reviewer_protocol_instructions(stage="finding_verification").lower()
    assert "finding_verification" in protocol
    for banned in FORBIDDEN_SCOPE_REVIEW_STAGE_LABELS:
        assert banned not in protocol


def test_review_service_accepts_stage_payloads(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T003401-003401"
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        kind="aggregate",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=1,
        output_goal="Deliver.",
        items={"item-root": root},
    )
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
        phase=WHOLE_PLAN_REVIEW,
    )
    save_review_payload(store, run_id, {
            "id": "review-whole-plan-01",
            "type": "whole_plan",
            "revise_at": "blocker",
            "reviewer_session_id": "stub-session-reviewer",
            "target_revision": 1,
            "scope": {"kind": "whole_plan"},
            "status": "pending",
            "findings": [],
            "revision_cycles": 1,
            "lifecycle_status": "verification_pending",
            "active_stage": "finding_verification",
            "finding_set_id": "fs-1",
        },
    )
    service = ReviewAgentService(store, run_id)
    token = grant_capability(
        store,
        run_id,
        role="reviewer",
        phase=WHOLE_PLAN_REVIEW,
        session_kind="reviewer",
        session_id="stub-session-reviewer",
        loop_id="review-whole-plan-01",
    )
    result = service.respond(
        {
            "loop_id": "review-whole-plan-01",
            "target_revision": 1,
            "stage": "finding_verification",
            "decision": "verified",
            "finding_set_id": "fs-1",
            "finding_results": [
                {
                    "finding_id": "finding-1",
                    "disposition": "resolved",
                    "evidence": ["done"],
                    "direct_side_effects": [],
                }
            ],
            "family_results": [],
            "new_direct_side_effect_findings": [],
            "target_digest": mandatory_plan_digest(store, run_id),
            "summary": "Closed.",
        },
        capability_token=token,
    )
    assert result["ok"] is True
    assert result["decision"] == "verified"
    assert result["stage"] == "finding_verification"
    assert result["status"] == "verified"

    save_review_payload(store, run_id, {
            "id": "review-whole-plan-01",
            "type": "whole_plan",
            "revise_at": "blocker",
            "reviewer_session_id": "stub-session-reviewer",
            "target_revision": 1,
            "scope": {"kind": "whole_plan"},
            "status": "pending",
            "findings": [],
            "revision_cycles": 1,
            "lifecycle_status": "scope_review_pending",
            "active_stage": "scope_review",
            "scope_review_rounds": 1,
        },
    )
    token = grant_capability(
        store,
        run_id,
        role="reviewer",
        phase=WHOLE_PLAN_REVIEW,
        session_kind="reviewer",
        session_id="stub-session-reviewer",
        loop_id="review-whole-plan-01",
    )
    with pytest.raises(RequestError, match="does not match loop active_stage"):
        service.respond(
            {
                "loop_id": "review-whole-plan-01",
                "target_revision": 1,
                "stage": "finding_verification",
                "decision": "verified",
                "target_digest": mandatory_plan_digest(store, run_id),
                "finding_set_id": "fs-1",
                "finding_results": [],
                "new_direct_side_effect_findings": [],
                "summary": "Stage mismatch probe.",
            },
            capability_token=token,
        )


def test_mandatory_respond_requires_stage(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T003501-003501"
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        kind="aggregate",
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
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
        phase=WHOLE_PLAN_REVIEW,
    )
    save_review_payload(store, run_id, {
            "id": "review-whole-plan-01",
            "type": "whole_plan",
            "revise_at": "blocker",
            "reviewer_session_id": "stub-session-reviewer",
            "target_revision": 0,
            "scope": {"kind": "whole_plan"},
            "status": "pending",
            "findings": [],
            "lifecycle_status": "review_pending",
        },
    )
    service = ReviewAgentService(store, run_id)
    token = grant_capability(
        store,
        run_id,
        role="reviewer",
        phase=WHOLE_PLAN_REVIEW,
        session_kind="reviewer",
        session_id="stub-session-reviewer",
        loop_id="review-whole-plan-01",
    )
    with pytest.raises(RequestError, match="oneOf|requires stage"):
        service.respond(
            {
                "loop_id": "review-whole-plan-01",
                "target_revision": 0,
                "decision": "approved",
                "findings": [],
                "target_digest": mandatory_plan_digest(store, run_id),
            },
            capability_token=token,
        )


def test_review_service_rejects_respond_after_gate_approve(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T003601-003601"
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        kind="aggregate",
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
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
        phase=WHOLE_PLAN_REVIEW,
    )
    digest = mandatory_plan_digest(store, run_id)
    save_review_payload(store, run_id, {
            "id": "review-whole-plan-01",
            "type": "whole_plan",
            "revise_at": "blocker",
            "reviewer_session_id": "stub-session-reviewer",
            "target_revision": 0,
            "scope": {"kind": "whole_plan"},
            "status": "approved",
            "findings": [],
            "lifecycle_status": "scope_review_pending",
            "active_stage": "scope_review",
            "scope_review_rounds": 1,
            "scope_review_result": {
                "stage": "scope_review",
                "decision": "approved",
                "target_digest": digest,
                "scope_id": "whole_plan",
                "reported_findings": [],
                "acceptance_criteria_checked": ["Core Invariant"],
                "summary": "Clear.",
            },
        },
    )
    service = ReviewAgentService(store, run_id)
    token = grant_capability(
        store,
        run_id,
        role="reviewer",
        phase=WHOLE_PLAN_REVIEW,
        session_kind="reviewer",
        session_id="stub-session-reviewer",
        loop_id="review-whole-plan-01",
    )
    with pytest.raises(RequestError, match="already terminal"):
        service.respond(
            mandatory_scope_review_respond_request(
                store,
                run_id,
                loop_id="review-whole-plan-01",
                target_revision=0,
                review_type="whole_plan",
            ),
            capability_token=token,
        )


def test_discovery_request_error_includes_rubric_hint() -> None:
    from top_down_planning.agent_tool.review_service import _value_error_as_request_error

    err = _value_error_as_request_error(
        ValueError("audit attestation rubric_item_ids union mismatch")
    )
    assert err.hint is not None
    assert "rubric_items" in err.hint
    assert "union" in err.hint.lower()
    assert "hint" in err.to_dict()


def test_discovery_request_error_includes_rule_id_hint() -> None:
    from top_down_planning.agent_tool.review_service import _value_error_as_request_error

    err = _value_error_as_request_error(
        ValueError("rule_id 'bad' must be a built-in rule or match custom.<slug>")
    )
    assert err.hint is not None
    assert "rule_id" in err.hint.lower()
    assert "hint" in err.to_dict()


def test_review_respond_invalid_rule_id_includes_hint(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T003501-003501"
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        kind="aggregate",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=1,
        output_goal="Deliver.",
        items={"item-root": root},
    )
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
        phase=WHOLE_PLAN_REVIEW,
    )
    save_review_payload(
        store,
        run_id,
        {
            "id": "review-whole-plan-01",
            "type": "whole_plan",
            "review_contract_version": 2,
            "revise_at": "blocker",
            "reviewer_session_id": "stub-session-reviewer",
            "target_revision": 1,
            "scope": {"kind": "whole_plan"},
            "status": "pending",
            "findings": [],
            "revision_cycles": 0,
            "lifecycle_status": "review_pending",
            "active_stage": "initial_review",
            "finding_set_id": "review-whole-plan-01-fs-01",
        },
    )
    service = ReviewAgentService(store, run_id)
    token = grant_capability(
        store,
        run_id,
        role="reviewer",
        phase=WHOLE_PLAN_REVIEW,
        session_kind="reviewer",
        session_id="stub-session-reviewer",
        loop_id="review-whole-plan-01",
    )
    payload = dict(show_example("review-respond-family-discovery")["payload"])
    payload["finding_families"][0]["rule_id"] = "invalid.rule"
    with pytest.raises(RequestError) as exc_info:
        service.respond(payload, capability_token=token)
    assert "must be a built-in rule" in str(exc_info.value)
    assert exc_info.value.hint is not None
    assert "rule_id" in exc_info.value.hint.lower()
