"""Integration test for whole-plan finding family repair in one revision cycle."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.agent_tool import PlanAgentService, ReviewAgentService
from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.domain.artifact_refs import digest_field_value
from top_down_planning.domain.mandatory_audit_passes import WHOLE_PLAN_AUDIT_PASS_IDS
from top_down_planning.domain.finding_families import compute_family_fingerprint
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID
from top_down_planning.orchestrator.review_analysis_context import rubric_items_with_ids
from top_down_planning.persistence.file_store import FileRunStore
from top_down_planning.orchestrator.phases import PLANNING
from tests.helpers import (
    create_run_kwargs,
    enter_mandatory_verification_pending,
    grant_capability,
    mandatory_plan_digest,
    mandatory_scope_review_respond_request,
    minimal_resolved_config,
    prepare_loop_for_scope_review_respond,
)


def test_whole_plan_review_package_includes_rendered_protocol(tmp_path: Path) -> None:
    from top_down_planning.orchestrator.whole_plan_review import (
        build_whole_plan_review_package,
    )
    from tests.helpers import make_review_loop

    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T120001-abcdef"
    config = minimal_resolved_config()
    root = PlanItem(
        id=PLAN_ROOT_ITEM_ID,
        parent_id=None,
        order_key="0000000000",
        title="Deliver",
        outcome="Deliver the output.",
        kind="aggregate",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the output.",
        items={PLAN_ROOT_ITEM_ID: root},
    )
    store.create_run(run_id, plan=plan, **create_run_kwargs(tmp_path, resolved_config=config))
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "whole_plan"},
        finding_set_id="review-whole-plan-01-fs-01",
    )
    package = build_whole_plan_review_package(
        run_id,
        store.load_run(run_id),
        config,
        store.load_plan_model(run_id),
        loop,
    )
    protocol = package["protocol_instructions"]
    assert isinstance(protocol, str)
    assert "tdp agent review respond" in protocol.lower()
    assert package["initial_review_guidance"] == [
        "Follow protocol_instructions for mandatory whole_* initial_review behavior."
    ]


def _audit_attestation(*, target_revision: int, digest: str) -> dict:
    rubric_items = rubric_items_with_ids(
        [str(item) for item in DEFAULT_CONFIG["review"]["whole_plan"]["rubric"]]
    )
    rubric_ids = [item["id"] for item in rubric_items]
    return {
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
    }


def test_family_fix_records_owner_sweep(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T120000-abcdef"
    config = minimal_resolved_config()
    root = PlanItem(
        id=PLAN_ROOT_ITEM_ID,
        parent_id=None,
        order_key="0000000000",
        title="Deliver",
        outcome="Deliver the output.",
        kind="aggregate",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the output.",
        items={PLAN_ROOT_ITEM_ID: root},
    )
    store.create_run(run_id, plan=plan, **create_run_kwargs(tmp_path, resolved_config=config))

    plan = store.load_plan_model(run_id)
    plan.revision = int(store.load_plan(run_id)["revision"])
    for item_id, acceptance in (
        ("item-a", "Reset control must work end-to-end"),
        ("item-b", "Uses Reset control in recovery flow"),
        ("item-c", "Reset control banner must show"),
    ):
        plan.items[item_id] = PlanItem(
            id=item_id,
            parent_id=PLAN_ROOT_ITEM_ID,
            order_key=f"000000000{item_id[-1]}",
            title=item_id,
            outcome=f"Outcome for {item_id}",
            kind="work",
            acceptance=[acceptance],
        )
    next_plan = plan.to_dict()
    next_plan["revision"] = plan.revision + 1
    store.save_plan(run_id, next_plan, plan.revision)
    plan = store.load_plan_model(run_id)

    from top_down_planning.domain.review_loop_factory import new_whole_plan_review_loop

    loop = new_whole_plan_review_loop(
        loop_id="review-whole-plan-01",
        target_revision=int(plan.revision),
        config=config,
    )
    loop, finding_set_id = __import__(
        "top_down_planning.domain.reviews",
        fromlist=["allocate_discovery_finding_set_id"],
    ).allocate_discovery_finding_set_id(loop)
    store.save_review(run_id, loop.to_dict())

    loop_id = loop.id
    target_revision = int(store.load_plan(run_id)["revision"])
    digest = mandatory_plan_digest(store, run_id)
    fingerprint = compute_family_fingerprint(
        rule_id="dependency.acceptance_capability_available",
        subject_key="reset-control",
        scope_kind="active-plan",
    )
    findings = []
    for index, (item_id, acceptance) in enumerate(
        (
            ("item-a", "Reset control must work end-to-end"),
            ("item-b", "Uses Reset control in recovery flow"),
            ("item-c", "Reset control banner must show"),
        ),
        start=1,
    ):
        findings.append(
            {
                "id": f"sf-{index:03d}",
                "family_id": "family-reset",
                "severity": "blocker",
                "category": "architecture",
                "target_refs": [item_id],
                "issue": "Reset referenced before dependency exists",
                "recommended_change": "Normalize Reset references",
                "instance_ref": {
                    "kind": "plan_item_field",
                    "item_id": item_id,
                    "field": "acceptance",
                    "value_digest": digest_field_value(acceptance),
                    "duplicate_ordinal": 0,
                },
            }
        )

    discovery = {
        "loop_id": loop_id,
        "target_revision": target_revision,
        "stage": "initial_review",
        "finding_set_id": finding_set_id,
        "reported_findings": findings,
        "review_completed": True,
        "summary": "Three Reset instances found",
        "target_digest": digest,
        "audit_attestation": _audit_attestation(
            target_revision=target_revision,
            digest=digest,
        ),
        "finding_families": [
            {
                "id": "family-reset",
                "rule_id": "dependency.acceptance_capability_available",
                "subject_key": "reset-control",
                "scope_kind": "active-plan",
                "title": "Reset dependency closure",
                "seed_finding_id": "sf-001",
                "confirmed_finding_ids": ["sf-001", "sf-002", "sf-003"],
                "candidate_refs": [],
                "recommended_change": "Normalize Reset references",
                "discovery_sweep": {
                    "searched_refs": ["active-items:*"],
                    "search_dimensions": ["acceptance"],
                    "completed": True,
                    "summary": "Searched all active acceptance for Reset references",
                },
            }
        ],
    }

    token = grant_capability(
        store, run_id, role="reviewer", loop_id=loop_id, phase=PLANNING
    )
    ReviewAgentService(store, run_id).respond(discovery, capability_token=token)

    PlanAgentService(store, run_id).apply(
        {
            "base_revision": target_revision,
            "operations": [
                {
                    "op": "update_item",
                    "item_id": item_id,
                    "patch": {"acceptance": [f"Reserved slot only on {item_id}"]},
                }
                for item_id in ("item-a", "item-b", "item-c")
            ],
        },
        capability_token=grant_capability(store, run_id, role="planner", phase=PLANNING),
    )
    new_revision = int(store.load_plan(run_id)["revision"])
    new_digest = mandatory_plan_digest(store, run_id)

    ReviewAgentService(store, run_id).record_finding_actions(
        {
            "loop_id": loop_id,
            "target_revision": new_revision,
            "target_digest": new_digest,
            "finding_set_id": finding_set_id,
            "family_fixes": [
                {
                    "family_id": "family-reset",
                    "target_finding_ids": [],
                    "rationale": "Normalized all Reset references",
                    "changed_refs": ["item-a", "item-b", "item-c"],
                    "owner_sweep": {
                        "searched_refs": ["active-items:*"],
                        "search_dimensions": ["acceptance"],
                        "additional_fixed_refs": [],
                        "remaining_instance_refs": [],
                        "completed": True,
                        "summary": "No concrete Reset references remain",
                    },
                }
            ],
            "finding_actions": [],
        },
        capability_token=grant_capability(store, run_id, role="planner", phase=PLANNING),
    )

    loop_payload = store.load_review(run_id, loop_id)
    assert any(
        sweep.get("stage") == "owner_fix"
        for sweep in loop_payload.get("family_sweeps", [])
    )
    assert len(loop_payload.get("finding_families", [])) == 1

    enter_mandatory_verification_pending(
        store,
        run_id,
        loop_id,
        target_revision=new_revision,
        finding_set_id=finding_set_id,
    )

    finding_results = [
        {
            "finding_id": finding_id,
            "disposition": "resolved",
            "evidence": ["Normalized Reset references"],
            "direct_side_effects": [],
        }
        for finding_id in ("sf-001", "sf-002", "sf-003")
    ]
    verification = {
        "loop_id": loop_id,
        "target_revision": new_revision,
        "stage": "finding_verification",
        "finding_set_id": finding_set_id,
        "decision": "verified",
        "target_digest": new_digest,
        "finding_results": finding_results,
        "family_results": [
            {
                "family_id": "family-reset",
                "disposition": "closed",
                "verification_sweep": {
                    "searched_refs": ["active-items:*"],
                    "search_dimensions": ["acceptance"],
                    "remaining_instance_refs": [],
                    "completed": True,
                    "summary": "No remaining Reset instances",
                },
                "remaining_instance_findings": [],
            }
        ],
        "new_direct_side_effect_findings": [],
        "summary": "Families verified",
    }
    ReviewAgentService(store, run_id).respond(
        verification,
        capability_token=grant_capability(
            store, run_id, role="reviewer", loop_id=loop_id, phase=PLANNING
        ),
    )
    loop_payload = store.load_review(run_id, loop_id)
    assert any(
        sweep.get("stage") == "verification"
        for sweep in loop_payload.get("family_sweeps", [])
    )

    prepare_loop_for_scope_review_respond(
        store,
        run_id,
        loop_id,
        target_revision=new_revision,
    )
    ReviewAgentService(store, run_id).respond(
        mandatory_scope_review_respond_request(
            store,
            run_id,
            loop_id=loop_id,
            target_revision=new_revision,
            review_type="whole_plan",
        ),
        capability_token=grant_capability(
            store, run_id, role="reviewer", loop_id=loop_id, phase=PLANNING
        ),
    )
    loop_payload = store.load_review(run_id, loop_id)
    assert loop_payload.get("status") == "approved"
    scope_result = loop_payload.get("scope_review_result") or {}
    assert scope_result.get("decision") == "approved"
    assert scope_result.get("stage") == "scope_review"


def test_partial_family_fix_surfaces_remaining_instance(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T120001-abcdef"
    config = minimal_resolved_config()
    root = PlanItem(
        id=PLAN_ROOT_ITEM_ID,
        parent_id=None,
        order_key="0000000000",
        title="Deliver",
        outcome="Deliver the output.",
        kind="aggregate",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the output.",
        items={PLAN_ROOT_ITEM_ID: root},
    )
    store.create_run(run_id, plan=plan, **create_run_kwargs(tmp_path, resolved_config=config))

    plan = store.load_plan_model(run_id)
    plan.revision = int(store.load_plan(run_id)["revision"])
    for item_id, acceptance in (
        ("item-a", "Reset control must work end-to-end"),
        ("item-b", "Uses Reset control in recovery flow"),
        ("item-c", "Reset control banner must show"),
    ):
        plan.items[item_id] = PlanItem(
            id=item_id,
            parent_id=PLAN_ROOT_ITEM_ID,
            order_key=f"000000000{item_id[-1]}",
            title=item_id,
            outcome=f"Outcome for {item_id}",
            kind="work",
            acceptance=[acceptance],
        )
    next_plan = plan.to_dict()
    next_plan["revision"] = plan.revision + 1
    store.save_plan(run_id, next_plan, plan.revision)

    from top_down_planning.domain.review_loop_factory import new_whole_plan_review_loop

    loop = new_whole_plan_review_loop(
        loop_id="review-whole-plan-02",
        target_revision=int(store.load_plan(run_id)["revision"]),
        config=config,
    )
    loop, finding_set_id = __import__(
        "top_down_planning.domain.reviews",
        fromlist=["allocate_discovery_finding_set_id"],
    ).allocate_discovery_finding_set_id(loop)
    store.save_review(run_id, loop.to_dict())

    loop_id = loop.id
    target_revision = int(store.load_plan(run_id)["revision"])
    digest = mandatory_plan_digest(store, run_id)
    fingerprint = compute_family_fingerprint(
        rule_id="dependency.acceptance_capability_available",
        subject_key="reset-control",
        scope_kind="active-plan",
    )
    findings = []
    for index, (item_id, acceptance) in enumerate(
        (
            ("item-a", "Reset control must work end-to-end"),
            ("item-b", "Uses Reset control in recovery flow"),
            ("item-c", "Reset control banner must show"),
        ),
        start=1,
    ):
        findings.append(
            {
                "id": f"sf-{index:03d}",
                "family_id": "family-reset",
                "severity": "blocker",
                "category": "architecture",
                "target_refs": [item_id],
                "issue": "Reset referenced before dependency exists",
                "recommended_change": "Normalize Reset references",
                "instance_ref": {
                    "kind": "plan_item_field",
                    "item_id": item_id,
                    "field": "acceptance",
                    "value_digest": digest_field_value(acceptance),
                    "duplicate_ordinal": 0,
                },
            }
        )

    ReviewAgentService(store, run_id).respond(
        {
            "loop_id": loop_id,
            "target_revision": target_revision,
            "stage": "initial_review",
            "finding_set_id": finding_set_id,
            "reported_findings": findings,
            "review_completed": True,
            "summary": "Three Reset instances found",
            "target_digest": digest,
            "audit_attestation": _audit_attestation(
                target_revision=target_revision,
                digest=digest,
            ),
            "finding_families": [
                {
                    "id": "family-reset",
                    "rule_id": "dependency.acceptance_capability_available",
                    "subject_key": "reset-control",
                    "scope_kind": "active-plan",
                    "title": "Reset dependency closure",
                    "seed_finding_id": "sf-001",
                    "confirmed_finding_ids": ["sf-001", "sf-002", "sf-003"],
                    "candidate_refs": [],
                    "recommended_change": "Normalize Reset references",
                    "discovery_sweep": {
                        "searched_refs": ["active-items:*"],
                        "search_dimensions": ["acceptance"],
                        "completed": True,
                        "summary": "Searched all active acceptance for Reset references",
                    },
                }
            ],
        },
        capability_token=grant_capability(
            store, run_id, role="reviewer", loop_id=loop_id, phase=PLANNING
        ),
    )

    PlanAgentService(store, run_id).apply(
        {
            "base_revision": target_revision,
            "operations": [
                {
                    "op": "update_item",
                    "item_id": item_id,
                    "patch": {"acceptance": [f"Reserved slot only on {item_id}"]},
                }
                for item_id in ("item-a", "item-b")
            ],
        },
        capability_token=grant_capability(store, run_id, role="planner", phase=PLANNING),
    )
    new_revision = int(store.load_plan(run_id)["revision"])
    new_digest = mandatory_plan_digest(store, run_id)

    ReviewAgentService(store, run_id).record_finding_actions(
        {
            "loop_id": loop_id,
            "target_revision": new_revision,
            "target_digest": new_digest,
            "finding_set_id": finding_set_id,
            "family_fixes": [
                {
                    "family_id": "family-reset",
                    "target_finding_ids": [],
                    "rationale": "Claimed full family fix",
                    "changed_refs": ["item-a", "item-b"],
                    "owner_sweep": {
                        "searched_refs": ["active-items:*"],
                        "search_dimensions": ["acceptance"],
                        "additional_fixed_refs": [],
                        "remaining_instance_refs": [],
                        "completed": True,
                        "summary": "Claimed complete",
                    },
                }
            ],
            "finding_actions": [],
        },
        capability_token=grant_capability(store, run_id, role="planner", phase=PLANNING),
    )

    enter_mandatory_verification_pending(
        store,
        run_id,
        loop_id,
        target_revision=new_revision,
    )

    from top_down_planning.agent_tool.review_service import RequestError

    with pytest.raises(RequestError, match="verified rejected|disposition closed"):
        ReviewAgentService(store, run_id).respond(
            {
                "loop_id": loop_id,
                "target_revision": new_revision,
                "stage": "finding_verification",
                "finding_set_id": finding_set_id,
                "decision": "verified",
                "target_digest": new_digest,
                "finding_results": [
                    {
                        "finding_id": finding_id,
                        "disposition": "resolved",
                        "evidence": ["Fixed"],
                        "direct_side_effects": [],
                    }
                    for finding_id in ("sf-001", "sf-002", "sf-003")
                ],
                "family_results": [
                    {
                        "family_id": "family-reset",
                        "disposition": "open",
                        "verification_sweep": {
                            "searched_refs": ["active-items:*"],
                            "search_dimensions": ["acceptance"],
                            "remaining_instance_refs": [
                                {
                                    "kind": "plan_item_field",
                                    "item_id": "item-c",
                                    "field": "acceptance",
                                    "value_digest": digest_field_value(
                                        "Reset control banner must show"
                                    ),
                                    "duplicate_ordinal": 0,
                                }
                            ],
                            "completed": True,
                            "summary": "Remaining Reset on item-c",
                        },
                        "remaining_instance_findings": [
                            {
                                "id": "sf-004",
                                "family_id": "family-reset",
                                "severity": "blocker",
                                "category": "architecture",
                                "target_refs": ["item-c"],
                                "issue": "Reset still present",
                                "recommended_change": "Normalize Reset references",
                                "instance_ref": {
                                    "kind": "plan_item_field",
                                    "item_id": "item-c",
                                    "field": "acceptance",
                                    "value_digest": digest_field_value(
                                        "Reset control banner must show"
                                    ),
                                    "duplicate_ordinal": 0,
                                },
                            }
                        ],
                    }
                ],
                "new_direct_side_effect_findings": [],
                "summary": "Family still open",
            },
            capability_token=grant_capability(
                store, run_id, role="reviewer", loop_id=loop_id, phase=PLANNING
            ),
        )


def test_record_family_fix_rejects_stale_target_digest(tmp_path: Path) -> None:
    from top_down_planning.agent_tool.errors import RequestError
    from tests.helpers import make_review_loop, save_review_payload

    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T130001-abcdef"
    root = PlanItem(
        id=PLAN_ROOT_ITEM_ID,
        parent_id=None,
        order_key="0000000000",
        title="Deliver",
        outcome="Deliver the output.",
        kind="aggregate",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the output.",
        items={PLAN_ROOT_ITEM_ID: root},
    )
    store.create_run(run_id, plan=plan, **create_run_kwargs(tmp_path))
    loop_id = "review-whole-plan-01"
    save_review_payload(
        store,
        run_id,
        make_review_loop(
            id=loop_id,
            type="whole_plan",
            reviewer_session_id="sess",
            target_revision=0,
            scope={"kind": "whole_plan"},
            finding_set_id="review-whole-plan-01-fs-01",
            review_record_schema_version=2,
            review_contract_version=2,
            finding_families=[
                {
                    "id": "family-reset",
                    "rule_id": "dependency.acceptance_capability_available",
                    "subject_key": "reset-control",
                    "scope_kind": "active-plan",
                    "title": "Reset dependency closure",
                    "seed_finding_id": "sf-001",
                    "confirmed_finding_ids": ["sf-001"],
                    "candidate_refs": [],
                    "recommended_change": "Normalize Reset references",
                }
            ],
            findings=[
                {
                    "id": "sf-001",
                    "severity": "blocker",
                    "category": "architecture",
                    "target_refs": ["item-root"],
                    "issue": "Reset still present",
                    "recommended_change": "Normalize Reset references",
                    "family_id": "family-reset",
                }
            ],
            finding_ids_by_set={"review-whole-plan-01-fs-01": ["sf-001"]},
        ).to_dict(),
    )

    with pytest.raises(RequestError, match="target_digest does not match current plan digest"):
        ReviewAgentService(store, run_id).record_finding_actions(
            {
                "loop_id": loop_id,
                "target_revision": 0,
                "target_digest": "stale-plan-digest",
                "finding_set_id": "review-whole-plan-01-fs-01",
                "family_fixes": [
                    {
                        "family_id": "family-reset",
                        "target_finding_ids": [],
                        "rationale": "Normalized Reset references",
                        "changed_refs": ["item-root"],
                        "owner_sweep": {
                            "searched_refs": ["active-items:*"],
                            "search_dimensions": ["acceptance"],
                            "additional_fixed_refs": [],
                            "remaining_instance_refs": [],
                            "completed": True,
                            "summary": "No concrete Reset references remain",
                        },
                    }
                ],
                "finding_actions": [],
            },
            capability_token=grant_capability(
                store, run_id, role="planner", phase=PLANNING
            ),
        )


def test_record_family_fix_rebinds_owner_sweep_without_duplicate_actions(
    tmp_path: Path,
) -> None:
    from tests.helpers import make_review_loop, save_review_payload

    store = FileRunStore(tmp_path / "runs")
    run_id = "run-20260101T130002-abcdef"
    root = PlanItem(
        id=PLAN_ROOT_ITEM_ID,
        parent_id=None,
        order_key="0000000000",
        title="Deliver",
        outcome="Deliver the output.",
        kind="aggregate",
    )
    plan = Plan(
        id=f"plan-{run_id}",
        revision=0,
        output_goal="Deliver the output.",
        items={PLAN_ROOT_ITEM_ID: root},
    )
    store.create_run(run_id, plan=plan, **create_run_kwargs(tmp_path))
    loop_id = "review-whole-plan-01"
    finding_set_id = "review-whole-plan-01-fs-01"
    save_review_payload(
        store,
        run_id,
        make_review_loop(
            id=loop_id,
            type="whole_plan",
            reviewer_session_id="sess",
            target_revision=0,
            scope={"kind": "whole_plan"},
            finding_set_id=finding_set_id,
            review_record_schema_version=2,
            review_contract_version=2,
            finding_families=[
                {
                    "id": "family-reset",
                    "rule_id": "dependency.acceptance_capability_available",
                    "subject_key": "reset-control",
                    "scope_kind": "active-plan",
                    "title": "Reset dependency closure",
                    "seed_finding_id": "sf-001",
                    "confirmed_finding_ids": ["sf-001"],
                    "candidate_refs": [],
                    "recommended_change": "Normalize Reset references",
                }
            ],
            findings=[
                {
                    "id": "sf-001",
                    "severity": "blocker",
                    "category": "architecture",
                    "target_refs": [PLAN_ROOT_ITEM_ID],
                    "issue": "Reset still present",
                    "recommended_change": "Normalize Reset references",
                    "family_id": "family-reset",
                }
            ],
            finding_ids_by_set={finding_set_id: ["sf-001"]},
        ).to_dict(),
    )

    PlanAgentService(store, run_id).apply(
        {
            "base_revision": 0,
            "operations": [
                {
                    "op": "update_item",
                    "item_id": PLAN_ROOT_ITEM_ID,
                    "patch": {"acceptance": ["Reset normalized"]},
                }
            ],
        },
        capability_token=grant_capability(store, run_id, role="planner", phase=PLANNING),
    )
    revision_1 = int(store.load_plan(run_id)["revision"])
    digest_1 = mandatory_plan_digest(store, run_id)

    owner_fix_request = {
        "loop_id": loop_id,
        "target_revision": revision_1,
        "target_digest": digest_1,
        "finding_set_id": finding_set_id,
        "family_fixes": [
            {
                "family_id": "family-reset",
                "target_finding_ids": [],
                "rationale": "Normalized Reset references",
                "changed_refs": [PLAN_ROOT_ITEM_ID],
                "owner_sweep": {
                    "searched_refs": ["active-items:*"],
                    "search_dimensions": ["acceptance"],
                    "additional_fixed_refs": [],
                    "remaining_instance_refs": [],
                    "completed": True,
                    "summary": "No concrete Reset references remain",
                },
            }
        ],
        "finding_actions": [],
    }
    planner_token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    first = ReviewAgentService(store, run_id).record_finding_actions(
        owner_fix_request,
        capability_token=planner_token,
    )
    assert first["recorded_actions"]

    PlanAgentService(store, run_id).apply(
        {
            "base_revision": revision_1,
            "operations": [
                {
                    "op": "update_item",
                    "item_id": PLAN_ROOT_ITEM_ID,
                    "patch": {"acceptance": ["Reset normalized again"]},
                }
            ],
        },
        capability_token=planner_token,
    )
    revision_2 = int(store.load_plan(run_id)["revision"])
    digest_2 = mandatory_plan_digest(store, run_id)

    second = ReviewAgentService(store, run_id).record_finding_actions(
        {
            **owner_fix_request,
            "target_revision": revision_2,
            "target_digest": digest_2,
            "family_fixes": [
                {
                    **owner_fix_request["family_fixes"][0],
                    "rationale": "Rebound sweep after plan revision bump.",
                }
            ],
        },
        capability_token=planner_token,
    )
    assert second["recorded_actions"] == []

    loop_payload = store.load_review(run_id, loop_id)
    owner_sweeps = [
        sweep
        for sweep in loop_payload.get("family_sweeps", [])
        if sweep.get("stage") == "owner_fix"
    ]
    assert len(owner_sweeps) == 2
    assert owner_sweeps[-1]["artifact_revision"] == revision_2
    assert owner_sweeps[-1]["artifact_digest"] == digest_2
    assert len(loop_payload.get("finding_actions", [])) == 1
