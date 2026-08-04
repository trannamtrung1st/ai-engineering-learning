"""Hard-cutover payload contracts: lean shapes, rejection of legacy fields."""

from __future__ import annotations

from pathlib import Path

import pytest

from core_tools.schema import validate_against_schema
from top_down_planning.agent_tool.errors import RequestError
from top_down_planning.agent_tool.plan_service import PlanAgentService
from top_down_planning.agent_tool.request_schema import validate_agent_request
from top_down_planning.domain.review_loop_factory import new_whole_plan_review_loop
from top_down_planning.orchestrator.phases import PLANNING
from top_down_planning.orchestrator.whole_plan_review import build_whole_plan_review_package
from top_down_planning.persistence import FileRunStore
from top_down_planning.schema_docs import PUBLIC_EXAMPLES, show_example, show_schema
from tests.helpers import (
    create_run_kwargs,
    ensure_plan_work_scope_contracts,
    grant_capability,
    mandatory_initial_respond_request,
    minimal_resolved_config,
    plan_root_item,
    save_review_payload,
)
from top_down_planning.domain.models import Plan, PlanItem


def test_review_respond_rejects_nested_attestation_identity() -> None:
    schema = show_schema("review-respond")
    payload = dict(show_example("review-respond-family-discovery")["payload"])
    payload["audit_attestation"] = {
        "artifact_revision": payload["target_revision"],
        "artifact_digest": payload["target_digest"],
        "passes": payload["audit_attestation"]["passes"],
    }
    issues = validate_against_schema(payload, schema)
    assert issues


def test_review_respond_rejects_artifact_digest_alias() -> None:
    payload = dict(show_example("review-respond-family-discovery")["payload"])
    payload["artifact_digest"] = payload.pop("target_digest")
    with pytest.raises(RequestError, match=r"oneOf|target_digest|artifact_digest"):
        validate_agent_request("review_respond", payload)


def test_record_actions_rejects_per_action_identity_fields() -> None:
    payload = dict(show_example("review-record-finding-actions")["payload"])
    payload["finding_actions"][0]["artifact_revision"] = payload["target_revision"]
    with pytest.raises(RequestError, match="unexpected properties"):
        validate_agent_request("review_record_finding_actions", payload)


def test_plan_apply_response_contract_is_compact(tmp_path: Path) -> None:
    from tests.unit.test_agent_plan_tool import _sample_plan

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000001-000001"
    store.create_run(
        run_id,
        plan=_sample_plan().to_dict(),
        **create_run_kwargs(store.root, resolved_config=minimal_resolved_config()),
        phase=PLANNING,
    )
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    service = PlanAgentService(store, run_id)
    result = service.apply(
        {
            "base_revision": 0,
            "operations": [
                {
                    "op": "update_item",
                    "item_id": "item-root",
                    "patch": {"title": "Updated root"},
                }
            ],
        },
        capability_token=token,
    )
    assert "changed_subtree" not in result
    assert "planning_budget" not in result
    assert "revision" in result
    assert "changed_item_ids" in result


def test_whole_plan_package_has_single_rubric_copy(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000301-000301"
    config = minimal_resolved_config()
    root = plan_root_item(title="Deliver", outcome="Deliver.")
    api = PlanItem(
        id="item-api",
        parent_id="item-root",
        order_key="0000000000",
        title="API",
        outcome="API exists.",
        acceptance=["API behavior is verifiable."],
        kind="work",
    )
    plan = ensure_plan_work_scope_contracts(
        Plan(
            id=f"plan-{run_id}",
            revision=0,
            output_goal="Deliver.",
            items={"item-root": root, "item-api": api},
        )
    )
    store.create_run(
        run_id,
        plan=plan.to_dict(),
        **create_run_kwargs(store.root, resolved_config=config),
    )
    loop = new_whole_plan_review_loop(
        loop_id="review-whole-plan-01",
        target_revision=0,
        config=config,
    )
    package = build_whole_plan_review_package(
        run_id,
        store.load_run(run_id),
        config,
        plan,
        loop,
    )
    assert "rubric_items" in package
    assert "required_audit_passes" in package
    assert "digests" not in package
    assert "target_digest" in package
    assert "rubric_items" not in package.get("analysis_context", {})
    assert "audit_passes" not in package.get("analysis_context", {})


def test_mandatory_discovery_helper_emits_lean_sweeps(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    run_id = "run-20260101T000401-000401"
    config = minimal_resolved_config()
    root = plan_root_item(title="Deliver", outcome="Deliver.")
    plan = ensure_plan_work_scope_contracts(
        Plan(
            id=f"plan-{run_id}",
            revision=1,
            output_goal="Deliver.",
            items={"item-root": root},
        )
    )
    store.create_run(
        run_id,
        plan=plan.to_dict(),
        **create_run_kwargs(store.root, resolved_config=config),
    )
    loop_id = "review-whole-plan-01"
    save_review_payload(
        store,
        run_id,
        {
            "id": loop_id,
            "type": "whole_plan",
            "status": "open",
            "target_revision": 1,
            "review_record_schema_version": 2,
            "review_contract_version": 2,
            "finding_set_id": f"{loop_id}-fs-01",
            "active_stage": "initial_review",
            "lifecycle_status": "discovery_pending",
            "scope": {"kind": "whole_plan"},
        },
    )
    payload = mandatory_initial_respond_request(
        store,
        run_id,
        loop_id=loop_id,
        target_revision=1,
        review_type="whole_plan",
        decision="changes_requested",
        findings=[
            {
                "id": "sf-001",
                "severity": "major",
                "category": "correctness",
                "issue": "Acceptance depends on later capabilities.",
                "recommended_change": "Move checks to owning stories.",
            }
        ],
    )
    sweep = payload["finding_families"][0]["discovery_sweep"]
    assert "artifact_revision" not in sweep
    assert "artifact_digest" not in sweep
    assert "passes" in payload["audit_attestation"]
    assert "artifact_revision" not in payload["audit_attestation"]


def test_all_review_respond_examples_in_public_catalog() -> None:
    schema = show_schema("review-respond")
    for name in PUBLIC_EXAMPLES:
        if not name.startswith("review-respond"):
            continue
        example = show_example(name)
        issues = validate_against_schema(example["payload"], schema)
        assert issues == [], (name, issues)
