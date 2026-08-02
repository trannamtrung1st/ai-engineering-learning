"""Focused review optional finding families (v1.5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from top_down_planning.agent_tool import RequestError, ReviewAgentService
from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.persistence import FileRunStore
from tests.helpers import create_run_kwargs, grant_capability, respond_review, save_review_payload
from top_down_planning.orchestrator.phases import PLANNING
from tests.unit.test_focused_review import (
    _create_planning_run,
    _focused_plan_request,
    _review_respond_request,
    request_focused_review,
)


def test_focused_family_discovery_persists_families(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_planning_run(store)
    run_id = "run-20260101T000401-000401"
    request_focused_review(
        store,
        run_id,
        _focused_plan_request(["item-api"]),
    )()

    respond_review(
        store,
        run_id,
        {
            "loop_id": "review-focused-plan-01",
            "target_revision": 0,
            "finding_set_id": "review-focused-plan-01-fs-01",
            "target_digest": store.load_run(run_id)["digests"]["plan"],
            "finding_families": [
                {
                    "id": "family-001",
                    "rule_id": "dependency.acceptance_capability_available",
                    "subject_key": "item-api acceptance",
                    "scope_kind": "focused-plan",
                    "title": "Acceptance gaps",
                    "seed_finding_id": "finding-001",
                    "confirmed_finding_ids": ["finding-001"],
                    "candidate_refs": [],
                    "recommended_change": "Add measurable checks.",
                    "discovery_sweep": {
                        "artifact_revision": 0,
                        "artifact_digest": store.load_run(run_id)["digests"]["plan"],
                        "searched_refs": ["active-items:*"],
                        "search_dimensions": ["acceptance"],
                        "completed": True,
                        "summary": "done",
                    },
                }
            ],
            "reported_findings": [
                {
                    "id": "finding-001",
                    "family_id": "family-001",
                    "instance_ref": {
                        "kind": "plan_item_field",
                        "item_id": "item-api",
                        "field": "acceptance",
                        "value_digest": "abc123",
                    },
                    "severity": "blocker",
                    "category": "acceptance",
                    "target_refs": ["item-api"],
                    "issue": "Not testable.",
                    "recommended_change": "Fix acceptance.",
                    "status": "unresolved",
                }
            ],
            "review_completed": True,
            "summary": "family discovery",
        },
        phase="planning",
        loop_id="review-focused-plan-01",
    )()

    loop = ReviewLoop.from_dict(
        store.load_review(run_id, "review-focused-plan-01")
    )
    assert len(loop.finding_families) == 1
    assert loop.finding_families[0].scope_kind == "focused-plan"


def test_focused_family_discovery_rejects_out_of_scope_instance_ref(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    _create_planning_run(store)
    run_id = "run-20260101T000401-000401"
    request_focused_review(
        store,
        run_id,
        _focused_plan_request(["item-api"]),
    )()

    with pytest.raises(RequestError, match="outside declared scope"):
        respond_review(
            store,
            run_id,
            _review_respond_request(
                store,
                run_id,
                loop_id="review-focused-plan-01",
                decision="changes_requested",
                findings=[
                    {
                        "id": "finding-001",
                        "severity": "blocker",
                        "category": "acceptance",
                        "target_refs": ["item-api"],
                        "instance_ref": {
                            "kind": "plan_item_field",
                            "item_id": "item-other",
                            "field": "acceptance",
                            "value_digest": "abc123",
                        },
                        "issue": "Gap.",
                        "recommended_change": "Fix.",
                        "status": "unresolved",
                    }
                ],
            ),
            phase="planning",
            loop_id="review-focused-plan-01",
        )()


def test_focused_family_discovery_rejects_stale_target_digest(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    _create_planning_run(store)
    run_id = "run-20260101T000401-000401"
    request_focused_review(
        store,
        run_id,
        _focused_plan_request(["item-api"]),
    )()

    with pytest.raises(RequestError, match="target_digest does not match"):
        respond_review(
            store,
            run_id,
            {
                "loop_id": "review-focused-plan-01",
                "target_revision": 0,
                "finding_set_id": "review-focused-plan-01-fs-01",
                "target_digest": "stale-plan-digest",
                "finding_families": [
                    {
                        "id": "family-001",
                        "rule_id": "dependency.acceptance_capability_available",
                        "subject_key": "item-api acceptance",
                        "scope_kind": "focused-plan",
                        "title": "Acceptance gaps",
                        "seed_finding_id": "finding-001",
                        "confirmed_finding_ids": ["finding-001"],
                        "candidate_refs": [],
                        "recommended_change": "Add measurable checks.",
                        "discovery_sweep": {
                            "artifact_revision": 0,
                            "artifact_digest": "stale-plan-digest",
                            "searched_refs": ["active-items:*"],
                            "search_dimensions": ["acceptance"],
                            "completed": True,
                            "summary": "done",
                        },
                    }
                ],
                "reported_findings": [
                    {
                        "id": "finding-001",
                        "family_id": "family-001",
                        "instance_ref": {
                            "kind": "plan_item_field",
                            "item_id": "item-api",
                            "field": "acceptance",
                            "value_digest": "abc123",
                        },
                        "severity": "blocker",
                        "category": "acceptance",
                        "target_refs": ["item-api"],
                        "issue": "Not testable.",
                        "recommended_change": "Fix acceptance.",
                        "status": "unresolved",
                    }
                ],
                "review_completed": True,
                "summary": "family discovery",
            },
            phase="planning",
            loop_id="review-focused-plan-01",
        )()


def test_focused_family_discovery_rejects_out_of_scope_candidate_ref(
    tmp_path: Path,
) -> None:
    store = FileRunStore(tmp_path)
    _create_planning_run(store)
    run_id = "run-20260101T000401-000401"
    plan_digest = store.load_run(run_id)["digests"]["plan"]
    request_focused_review(
        store,
        run_id,
        _focused_plan_request(["item-api"]),
    )()

    with pytest.raises(RequestError, match="outside declared scope"):
        respond_review(
            store,
            run_id,
            {
                "loop_id": "review-focused-plan-01",
                "target_revision": 0,
                "finding_set_id": "review-focused-plan-01-fs-01",
                "target_digest": plan_digest,
                "finding_families": [
                    {
                        "id": "family-001",
                        "rule_id": "dependency.acceptance_capability_available",
                        "subject_key": "item-api acceptance",
                        "scope_kind": "focused-plan",
                        "title": "Acceptance gaps",
                        "seed_finding_id": "finding-001",
                        "confirmed_finding_ids": ["finding-001"],
                        "candidate_refs": [
                            {
                                "kind": "plan_item_field",
                                "item_id": "item-other",
                                "field": "acceptance",
                                "value_digest": "abc123",
                            }
                        ],
                        "recommended_change": "Add measurable checks.",
                        "discovery_sweep": {
                            "artifact_revision": 0,
                            "artifact_digest": plan_digest,
                            "searched_refs": ["active-items:*"],
                            "search_dimensions": ["acceptance"],
                            "completed": True,
                            "summary": "done",
                        },
                    }
                ],
                "reported_findings": [
                    {
                        "id": "finding-001",
                        "family_id": "family-001",
                        "instance_ref": {
                            "kind": "plan_item_field",
                            "item_id": "item-api",
                            "field": "acceptance",
                            "value_digest": "abc123",
                        },
                        "severity": "blocker",
                        "category": "acceptance",
                        "target_refs": ["item-api"],
                        "issue": "Not testable.",
                        "recommended_change": "Fix acceptance.",
                        "status": "unresolved",
                    }
                ],
                "review_completed": True,
                "summary": "family discovery",
            },
            phase="planning",
            loop_id="review-focused-plan-01",
        )()


def test_focused_verification_rejects_stale_target_digest(tmp_path: Path) -> None:
    from top_down_planning.domain.reviews import ReviewFinding
    from tests.helpers import make_review_loop, save_review_payload

    store = FileRunStore(tmp_path)
    _create_planning_run(store)
    run_id = "run-20260101T000401-000401"
    finding = ReviewFinding(
        id="finding-01",
        severity="blocker",
        category="acceptance",
        target_refs=["item-api"],
        issue="Gap.",
        recommended_change="Fix.",
        status="unresolved",
    )
    loop = make_review_loop(
        id="review-focused-plan-01",
        type="focused_plan",
        reviewer_session_id="sess-reviewer",
        target_revision=0,
        scope={"kind": "focused_plan", "item_ids": ["item-api"]},
        finding_set_id="review-focused-plan-01-fs-01",
        findings=[finding],
        status="changes_requested",
        active_stage="finding_verification",
        review_contract_version=1,
    )
    save_review_payload(store, run_id, loop.to_dict())

    with pytest.raises(RequestError, match="target_digest does not match"):
        respond_review(
            store,
            run_id,
            {
                "loop_id": "review-focused-plan-01",
                "target_revision": 0,
                "stage": "finding_verification",
                "decision": "verified",
                "finding_set_id": "review-focused-plan-01-fs-01",
                "finding_results": [
                    {
                        "finding_id": "finding-01",
                        "disposition": "resolved",
                        "evidence": ["fixed"],
                        "direct_side_effects": [],
                    }
                ],
                "new_direct_side_effect_findings": [],
                "target_digest": "stale-plan-digest",
                "summary": "verification",
            },
            phase=PLANNING,
            loop_id="review-focused-plan-01",
        )()


def test_focused_verification_rejects_out_of_scope_side_effect_finding(
    tmp_path: Path,
) -> None:
    from tests.helpers import make_review_loop, mandatory_plan_digest, save_review_payload
    from top_down_planning.domain.reviews import ReviewFinding

    store = FileRunStore(tmp_path)
    _create_planning_run(store)
    run_id = "run-20260101T000401-000401"
    finding = ReviewFinding(
        id="finding-01",
        severity="blocker",
        category="acceptance",
        target_refs=["item-api"],
        issue="Gap.",
        recommended_change="Fix.",
        status="unresolved",
    )
    loop = make_review_loop(
        id="review-focused-plan-01",
        type="focused_plan",
        reviewer_session_id="sess-reviewer",
        target_revision=0,
        scope={"kind": "focused_plan", "item_ids": ["item-api"]},
        finding_set_id="review-focused-plan-01-fs-01",
        findings=[finding],
        status="changes_requested",
        active_stage="finding_verification",
        review_contract_version=1,
    )
    save_review_payload(store, run_id, loop.to_dict())

    with pytest.raises(RequestError, match="outside declared scope"):
        respond_review(
            store,
            run_id,
            {
                "loop_id": "review-focused-plan-01",
                "target_revision": 0,
                "stage": "finding_verification",
                "decision": "needs_revision",
                "finding_set_id": "review-focused-plan-01-fs-01",
                "finding_results": [
                    {
                        "finding_id": "finding-01",
                        "disposition": "unresolved",
                        "evidence": ["still open"],
                        "direct_side_effects": [],
                    }
                ],
                "new_direct_side_effect_findings": [
                    {
                        "id": "finding-side",
                        "severity": "minor",
                        "category": "acceptance",
                        "target_refs": ["item-other"],
                        "issue": "Out of scope.",
                        "recommended_change": "Ignore.",
                        "status": "unresolved",
                    }
                ],
                "target_digest": mandatory_plan_digest(store, run_id),
                "summary": "verification",
            },
            phase=PLANNING,
            loop_id="review-focused-plan-01",
        )()


def test_flat_focused_discovery_unchanged_without_families(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_planning_run(store)
    run_id = "run-20260101T000401-000401"
    request_focused_review(
        store,
        run_id,
        _focused_plan_request(["item-api"]),
    )()

    respond_review(
        store,
        run_id,
        _review_respond_request(
            store,
            run_id,
            loop_id="review-focused-plan-01",
            decision="approved",
            findings=[],
        ),
        phase="planning",
        loop_id="review-focused-plan-01",
    )()

    loop = ReviewLoop.from_dict(
        store.load_review(run_id, "review-focused-plan-01")
    )
    assert loop.finding_families == []
    assert loop.status == "approved"


def test_focused_verification_recheck_includes_active_families() -> None:
    from top_down_planning.domain.finding_families import (
        FindingFamily,
        compute_family_fingerprint,
    )
    from top_down_planning.domain.reviews import ReviewFinding
    from top_down_planning.orchestrator.mandatory_review_stages import (
        verification_recheck_request,
    )
    from tests.helpers import make_review_loop

    finding = ReviewFinding(
        id="finding-001",
        severity="blocker",
        category="acceptance",
        target_refs=["item-api"],
        issue="Gap.",
        recommended_change="Fix.",
        family_id="family-001",
        status="unresolved",
    )
    family = FindingFamily(
        id="family-001",
        finding_set_id="set-1",
        rule_id="dependency.acceptance_capability_available",
        subject_key="item-api acceptance",
        scope_kind="focused-plan",
        family_fingerprint=compute_family_fingerprint(
            rule_id="dependency.acceptance_capability_available",
            subject_key="item-api acceptance",
            scope_kind="focused-plan",
        ),
        title="Acceptance gaps",
        seed_finding_id="finding-001",
        confirmed_finding_ids=["finding-001"],
        candidate_refs=[],
        recommended_change="Fix acceptance.",
    )
    loop = make_review_loop(
        id="review-focused-plan-01",
        type="focused_plan",
        reviewer_session_id="sess",
        target_revision=1,
        scope={"kind": "focused_plan", "item_ids": ["item-api"]},
        finding_set_id="set-1",
        findings=[finding],
        finding_families=[family.to_dict()],
        finding_ids_by_set={"set-1": ["finding-001"]},
        active_stage="finding_verification",
        review_contract_version=1,
    )

    recheck = verification_recheck_request(
        phase="planning",
        loop=loop,
        target_revision=1,
        artifact_digest="plan-digest-abc",
    )

    assert "active_families" in recheck
    assert recheck["active_families"]["families"][0]["id"] == "family-001"


def test_focused_review_rejects_family_fixes(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path)
    _create_planning_run(store)
    run_id = "run-20260101T000401-000401"
    request_focused_review(
        store,
        run_id,
        _focused_plan_request(["item-api"]),
    )()
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)
    service = ReviewAgentService(store, run_id)

    with pytest.raises(RequestError, match="family_fixes apply only to mandatory"):
        service.record_finding_actions(
            {
                "loop_id": "review-focused-plan-01",
                "family_fixes": [
                    {
                        "family_id": "family-001",
                        "owner_sweep": {
                            "completed": True,
                            "remaining_instance_refs": [],
                        },
                    }
                ],
            },
            capability_token=token,
        )
