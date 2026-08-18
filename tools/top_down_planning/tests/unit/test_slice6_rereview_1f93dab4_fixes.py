"""Slice 6 remediations against commit 1f93dab4 (007A/B, 008, 012)."""

from __future__ import annotations

from typing import Any, get_type_hints

import pytest

from core_tools.schema import validate_against_schema
from top_down_planning.agent_tool import (
    PlanAgentService,
    ProductionAgentService,
    ReviewAgentService,
    RevisionConflictError,
    RunAgentService,
)
from top_down_planning.agent_tool.artifacts import validate_production_evidence_integrity
from top_down_planning.orchestrator.phases import PLANNING, PRODUCTION
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.digests import compute_plan_digest
from top_down_planning.schema_docs import PUBLIC_SCHEMAS, SCHEMAS
from tests.helpers import (
    grant_capability,
    make_review_loop,
    mandatory_initial_respond_request,
    mandatory_plan_digest,
    save_review_payload,
)
from tests.unit.test_slice6_agent_tool_fixes import (
    _batch_apply_request,
    _create_planning_run,
    _create_production_run,
)


_MUTATION_RESPONSE_SCHEMAS = (
    "plan-apply-response",
    "production-apply-response",
    "production-amendment-response",
    "production-completion-response",
    "production-blocker-response",
    "review-respond-response",
    "review-record-finding-actions-response",
    "focused-review-request-response",
    "agent-error",
)


def _assert_caller_vs_current_conflict(
    exc: RevisionConflictError,
    *,
    caller_revision: int,
    current_revision: int,
) -> None:
    assert exc.code == "revision_conflict"
    assert exc.expected == caller_revision
    assert exc.actual == current_revision
    payload = exc.to_dict()
    assert payload["code"] == "revision_conflict"
    assert payload["expected_revision"] == caller_revision
    assert payload["actual_revision"] == current_revision
    assert payload.get("action")


def _pending_whole_plan_loop(loop_id: str = "review-whole-plan-01") -> dict[str, Any]:
    return make_review_loop(
        id=loop_id,
        type="whole_plan",
        reviewer_session_id="stub-session-reviewer",
        target_revision=0,
        scope={"kind": "whole_plan"},
        finding_set_id=f"{loop_id}-fs-01",
        review_record_schema_version=2,
        review_contract_version=2,
    ).to_dict()


def _optional_focused_loop(loop_id: str = "review-focused-plan-01") -> dict[str, Any]:
    return make_review_loop(
        id=loop_id,
        type="focused_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "focused_plan", "item_ids": ["item-api"]},
        revise_at="blocker",
        finding_set_id="fs-01",
        findings=[
            {
                "id": "finding-opt",
                "severity": "minor",
                "category": "correctness",
                "target_refs": ["item-api"],
                "issue": "Optional note",
                "recommended_change": "Consider",
                "status": "unresolved",
            }
        ],
        finding_ids_by_set={"fs-01": ["finding-opt"]},
    ).to_dict()


def test_review_respond_stale_current_artifact_revision_is_revision_conflict(
    tmp_path,
) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T080001-080001"
    _create_planning_run(store, run_id)
    loop_id = "review-whole-plan-01"
    save_review_payload(store, run_id, _pending_whole_plan_loop(loop_id))
    planner = grant_capability(store, run_id, role="planner", phase=PLANNING)
    PlanAgentService(store, run_id).apply(
        {
            "base_revision": 0,
            "operations": [
                {
                    "op": "update_item",
                    "item_id": "item-api",
                    "patch": {"title": "API after bump"},
                }
            ],
        },
        capability_token=planner,
    )
    current_revision = int(store.load_plan(run_id)["revision"])
    assert current_revision == 1
    reviewer = grant_capability(
        store,
        run_id,
        role="reviewer",
        phase=PLANNING,
        session_kind="reviewer",
        session_id="stub-session-reviewer",
        loop_id=loop_id,
    )

    with pytest.raises(RevisionConflictError) as excinfo:
        ReviewAgentService(store, run_id).respond(
            mandatory_initial_respond_request(
                store,
                run_id,
                loop_id=loop_id,
                target_revision=0,
                review_type="whole_plan",
            ),
            capability_token=reviewer,
        )
    _assert_caller_vs_current_conflict(
        excinfo.value,
        caller_revision=0,
        current_revision=current_revision,
    )


def test_record_actions_stale_revision_expected_is_caller_token(tmp_path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T080002-080002"
    _create_planning_run(store, run_id)
    loop_id = "review-focused-plan-01"
    save_review_payload(store, run_id, _optional_focused_loop(loop_id))
    planner = grant_capability(store, run_id, role="planner", phase=PLANNING)
    PlanAgentService(store, run_id).apply(
        {
            "base_revision": 0,
            "operations": [
                {
                    "op": "update_item",
                    "item_id": "item-api",
                    "patch": {"title": "API bumped"},
                }
            ],
        },
        capability_token=planner,
    )
    current_revision = int(store.load_plan(run_id)["revision"])
    assert current_revision == 1

    with pytest.raises(RevisionConflictError) as excinfo:
        ReviewAgentService(store, run_id).record_finding_actions(
            {
                "loop_id": loop_id,
                "target_revision": 0,
                "target_digest": mandatory_plan_digest(store, run_id),
                "finding_set_id": "fs-01",
                "finding_actions": [
                    {
                        "finding_id": "finding-opt",
                        "action": "accept_as_is",
                        "actor_role": "planner",
                        "rationale": "Accept",
                    }
                ],
            },
            capability_token=planner,
        )
    _assert_caller_vs_current_conflict(
        excinfo.value,
        caller_revision=0,
        current_revision=current_revision,
    )


def test_focused_request_stale_revision_expected_is_caller_token(tmp_path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T080003-080003"
    _create_planning_run(store, run_id)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    stale_revision = 0
    stale_digest = compute_plan_digest(store.load_plan_model(run_id))
    PlanAgentService(store, run_id).apply(
        {
            "base_revision": 0,
            "operations": [
                {
                    "op": "update_item",
                    "item_id": "item-api",
                    "patch": {"title": "API v2"},
                }
            ],
        },
        capability_token=token,
    )
    current_revision = int(store.load_plan(run_id)["revision"])

    with pytest.raises(RevisionConflictError) as excinfo:
        ReviewAgentService(store, run_id).request(
            {
                "type": "focused_plan",
                "scope": {"item_ids": ["item-api"]},
                "target_revision": stale_revision,
                "target_digest": stale_digest,
            },
            capability_token=token,
        )
    _assert_caller_vs_current_conflict(
        excinfo.value,
        caller_revision=stale_revision,
        current_revision=current_revision,
    )


def test_mutation_response_schemas_forbid_unknown_top_level_keys() -> None:
    for name in _MUTATION_RESPONSE_SCHEMAS:
        assert name in PUBLIC_SCHEMAS
        assert SCHEMAS[name].get("additionalProperties") is False


def test_every_public_agent_verb_output_matches_published_schema(tmp_path) -> None:
    store = FileRunStore(tmp_path)
    planning_id = "run-20260101T080010-080010"
    _create_planning_run(store, planning_id)
    planner = grant_capability(store, planning_id, role="planner", phase=PLANNING)
    plan_service = PlanAgentService(store, planning_id)
    digest = compute_plan_digest(store.load_plan_model(planning_id))
    review_service = ReviewAgentService(store, planning_id)
    focused = review_service.request(
        {
            "type": "focused_plan",
            "scope": {"item_ids": ["item-api"]},
            "target_revision": 0,
            "target_digest": digest,
        },
        capability_token=planner,
    )
    save_review_payload(store, planning_id, _optional_focused_loop("review-focused-plan-02"))
    recorded = review_service.record_finding_actions(
        {
            "loop_id": "review-focused-plan-02",
            "target_revision": 0,
            "target_digest": digest,
            "finding_set_id": "fs-01",
            "finding_actions": [
                {
                    "finding_id": "finding-opt",
                    "action": "accept_as_is",
                    "actor_role": "planner",
                    "rationale": "Accept",
                }
            ],
        },
        capability_token=planner,
    )
    save_review_payload(store, planning_id, _pending_whole_plan_loop())
    reviewer = grant_capability(
        store,
        planning_id,
        role="reviewer",
        phase=PLANNING,
        session_kind="reviewer",
        session_id="stub-session-reviewer",
        loop_id="review-whole-plan-01",
    )
    responded = review_service.respond(
        mandatory_initial_respond_request(
            store,
            planning_id,
            loop_id="review-whole-plan-01",
            target_revision=0,
            review_type="whole_plan",
        ),
        capability_token=reviewer,
    )

    production_id = "run-20260101T080011-080011"
    _create_production_run(store, production_id)
    producer = grant_capability(store, production_id, role="producer", phase=PRODUCTION)
    production = ProductionAgentService(store, production_id)
    applied = production.apply(
        _batch_apply_request(
            plan_items=["item-api"],
            dispositions={"item-api": {"disposition": "completed"}},
        ),
        capability_token=producer,
    )
    after_first = int(store.load_production(production_id)["revision"])
    production.apply(
        _batch_apply_request(
            plan_items=["item-ui"],
            dispositions={"item-ui": {"disposition": "completed"}},
            production_revision=after_first,
        ),
        capability_token=producer,
    )
    after_both = int(store.load_production(production_id)["revision"])
    completion = production.submit_completion(
        {
            "production_revision": after_both,
            "goal_assessment": "Goal met.",
        },
        capability_token=producer,
    )

    blocked_id = "run-20260101T080012-080012"
    _create_production_run(store, blocked_id)
    blocked_token = grant_capability(store, blocked_id, role="producer", phase=PRODUCTION)
    blocked_service = ProductionAgentService(store, blocked_id)
    blocker = blocked_service.report_blocked(
        {
            "production_revision": 0,
            "evidence": "Upstream unavailable.",
        },
        capability_token=blocked_token,
    )

    amendment_id = "run-20260101T080013-080013"
    _create_production_run(store, amendment_id)
    amendment_token = grant_capability(store, amendment_id, role="producer", phase=PRODUCTION)
    amendment = ProductionAgentService(store, amendment_id).request_amendment(
        {
            "production_revision": 0,
            "evidence": "Need a missing branch.",
            "affected_refs": ["item-root"],
        },
        capability_token=amendment_token,
    )

    pairs = [
        (plan_service.snapshot(), "plan-snapshot-response"),
        (plan_service.check(), "plan-check-response"),
        (
            plan_service.apply(
                {
                    "base_revision": int(store.load_plan(planning_id)["revision"]),
                    "operations": [
                        {
                            "op": "update_item",
                            "item_id": "item-ui",
                            "patch": {"title": "UI applied"},
                        }
                    ],
                },
                capability_token=planner,
            ),
            "plan-apply-response",
        ),
        (production.snapshot(), "production-snapshot-response"),
        (production.check(), "production-check-response"),
        (applied, "production-apply-response"),
        (amendment, "production-amendment-response"),
        (completion, "production-completion-response"),
        (blocker, "production-blocker-response"),
        (focused, "focused-review-request-response"),
        (responded, "review-respond-response"),
        (recorded, "review-record-finding-actions-response"),
        (RunAgentService(store, planning_id).status(), "run-status-response"),
        (
            {
                "ok": False,
                "error": RevisionConflictError(
                    "stale",
                    expected=0,
                    actual=1,
                    action="Refresh snapshot.",
                ).to_dict(),
            },
            "agent-error",
        ),
    ]
    for payload, schema_name in pairs:
        issues = validate_against_schema(payload, SCHEMAS[schema_name])
        assert issues == [], f"{schema_name}: {issues}"


def test_artifact_helpers_export_runtime_any_for_type_hints() -> None:
    hints = get_type_hints(validate_production_evidence_integrity)
    assert hints["production"] == dict[str, Any]
