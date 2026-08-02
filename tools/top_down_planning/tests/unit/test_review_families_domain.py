"""Domain tests for review families, versioning, and artifact refs."""

from __future__ import annotations

import pytest

from dataclasses import replace

from tests.helpers import make_review_loop

from top_down_planning.domain.artifact_refs import (
    PlanItemFieldRef,
    artifact_refs_equal,
    digest_field_value,
    parse_artifact_ref,
)
from top_down_planning.domain.digest import digest_canonical_payload
from top_down_planning.domain.finding_families import (
    active_families,
    compute_effective_fix_target_ids,
    compute_family_fingerprint,
    derive_family_operational_status,
)
from top_down_planning.domain.review_loop_factory import (
    new_focused_review_loop,
    new_whole_output_review_loop,
    new_whole_plan_review_loop,
)
from top_down_planning.domain.reviews import (
    CURRENT_REVIEW_CONTRACT_VERSION,
    CURRENT_REVIEW_RECORD_SCHEMA_VERSION,
    LEGACY_REVIEW_CONTRACT_VERSION,
    LEGACY_REVIEW_RECORD_SCHEMA_VERSION,
    ReviewFinding,
    ReviewLoop,
    parse_review_version_fields,
    uses_finding_family_protocol,
)

_FAMILY_PROTOCOL_VERSIONS = {
    "review_record_schema_version": CURRENT_REVIEW_RECORD_SCHEMA_VERSION,
    "review_contract_version": CURRENT_REVIEW_CONTRACT_VERSION,
}


def test_parse_review_version_fields_defaults_to_legacy() -> None:
    record, contract = parse_review_version_fields({})
    assert record == LEGACY_REVIEW_RECORD_SCHEMA_VERSION
    assert contract == LEGACY_REVIEW_CONTRACT_VERSION


def test_parse_review_version_fields_accepts_legacy_alias() -> None:
    record, contract = parse_review_version_fields({"review_schema_version": 1})
    assert record == 1
    assert contract == 1


def test_parse_review_version_fields_rejects_disagreeing_alias() -> None:
    with pytest.raises(ValueError, match="disagree"):
        parse_review_version_fields(
            {"review_record_schema_version": 2, "review_schema_version": 1}
        )


def test_parse_review_version_fields_accepts_supported_versions() -> None:
    record, contract = parse_review_version_fields(
        {"review_record_schema_version": 2, "review_contract_version": 2}
    )
    assert record == 2
    assert contract == 2


def test_parse_review_version_fields_rejects_unsupported_versions() -> None:
    with pytest.raises(ValueError, match="review_record_schema_version"):
        parse_review_version_fields({"review_record_schema_version": 3})
    with pytest.raises(ValueError, match="review_contract_version"):
        parse_review_version_fields({"review_contract_version": 3})


def test_uses_finding_family_protocol_gates_on_contract_version() -> None:
    loop = make_review_loop(id="loop-1", type="whole_plan", **_FAMILY_PROTOCOL_VERSIONS)
    assert uses_finding_family_protocol(loop)
    legacy = make_review_loop(id="loop-2", type="whole_plan")
    assert not uses_finding_family_protocol(legacy)


def test_new_whole_plan_review_loop_sets_contract_v2() -> None:
    loop = new_whole_plan_review_loop(
        loop_id="review-whole-plan-01",
        target_revision=1,
        config={"review": {"whole_plan": {"revise_at": "blocker"}}},
    )
    assert loop.review_record_schema_version == CURRENT_REVIEW_RECORD_SCHEMA_VERSION
    assert loop.review_contract_version == CURRENT_REVIEW_CONTRACT_VERSION


def test_new_whole_output_review_loop_uses_contract_v1() -> None:
    loop = new_whole_output_review_loop(
        loop_id="review-whole-output-01",
        target_revision=1,
        config={"review": {"whole_output": {"revise_at": "blocker"}}},
    )
    assert loop.review_record_schema_version == CURRENT_REVIEW_RECORD_SCHEMA_VERSION
    assert loop.review_contract_version == 1


def test_new_focused_review_loop_uses_record_v2_contract_v1() -> None:
    loop = new_focused_review_loop(
        loop_id="review-focused-plan-01",
        review_type="focused_plan",
        target_revision=1,
        scope={"item_ids": ["item-a"]},
        config={"review": {"focused_plan": {"revise_at": "blocker"}}},
    )
    assert loop.review_record_schema_version == CURRENT_REVIEW_RECORD_SCHEMA_VERSION
    assert loop.review_contract_version == 1


def test_family_fingerprint_is_stable_for_builtin_rules() -> None:
    first = compute_family_fingerprint(
        rule_id="dependency.acceptance_capability_available",
        subject_key="Reset Control",
        scope_kind="active-plan",
    )
    second = compute_family_fingerprint(
        rule_id="dependency.acceptance_capability_available",
        subject_key="reset control",
        scope_kind="active-plan",
    )
    assert first == second


def test_artifact_ref_canonical_identity_uses_duplicate_ordinal() -> None:
    left = PlanItemFieldRef(
        kind="plan_item_field",
        item_id="item-a",
        field="acceptance",
        value_digest=digest_field_value("same"),
        duplicate_ordinal=0,
    )
    right = PlanItemFieldRef(
        kind="plan_item_field",
        item_id="item-a",
        field="acceptance",
        value_digest=digest_field_value("same"),
        duplicate_ordinal=1,
    )
    assert not artifact_refs_equal(left, right)
    round_trip = parse_artifact_ref(
        {
            "kind": "plan_item_field",
            "item_id": "item-a",
            "field": "acceptance",
            "value_digest": digest_field_value("same"),
            "duplicate_ordinal": 0,
        }
    )
    assert artifact_refs_equal(left, round_trip)


def test_effective_fix_target_ids_includes_required_open_members() -> None:
    finding_a = ReviewFinding(
        id="f-req",
        severity="blocker",
        category="correctness",
        target_refs=["item-a"],
        issue="x",
        recommended_change="y",
        family_id="family-1",
    )
    finding_b = ReviewFinding(
        id="f-opt",
        severity="minor",
        category="correctness",
        target_refs=["item-b"],
        issue="x",
        recommended_change="y",
        family_id="family-1",
    )
    from top_down_planning.domain.finding_families import FindingFamily

    family = FindingFamily(
        id="family-1",
        finding_set_id="set-1",
        rule_id="dependency.acceptance_capability_available",
        subject_key="reset",
        scope_kind="active-plan",
        family_fingerprint=compute_family_fingerprint(
            rule_id="dependency.acceptance_capability_available",
            subject_key="reset",
            scope_kind="active-plan",
        ),
        title="t",
        seed_finding_id="f-req",
        confirmed_finding_ids=["f-req", "f-opt"],
        candidate_refs=[],
        recommended_change="fix all",
    )
    loop = replace(
        make_review_loop(
            id="loop-1",
            type="whole_plan",
            finding_set_id="set-1",
            finding_ids_by_set={"set-1": ["f-req", "f-opt"]},
            **_FAMILY_PROTOCOL_VERSIONS,
        ),
        findings=[finding_a, finding_b],
        finding_families=[family],
    )
    effective = compute_effective_fix_target_ids(
        loop,
        "family-1",
        target_finding_ids=["f-opt"],
        challenged_required_ids=set(),
    )
    assert effective == ["f-opt", "f-req"]


def test_challenge_only_family_does_not_require_owner_sweep() -> None:
    finding = ReviewFinding(
        id="f-req",
        severity="major",
        category="correctness",
        target_refs=["item-a"],
        issue="x",
        recommended_change="y",
        family_id="family-1",
    )
    from top_down_planning.domain.finding_families import FindingFamily
    from top_down_planning.domain.reviews import FindingAction

    family = FindingFamily(
        id="family-1",
        finding_set_id="set-1",
        rule_id="dependency.acceptance_capability_available",
        subject_key="reset",
        scope_kind="active-plan",
        family_fingerprint=compute_family_fingerprint(
            rule_id="dependency.acceptance_capability_available",
            subject_key="reset",
            scope_kind="active-plan",
        ),
        title="t",
        seed_finding_id="f-req",
        confirmed_finding_ids=["f-req"],
        candidate_refs=[],
        recommended_change="challenge",
    )
    loop = make_review_loop(
        id="loop-1",
        type="whole_plan",
        finding_set_id="set-1",
        findings=[finding],
        finding_families=[family.to_dict()],
        finding_ids_by_set={"set-1": ["f-req"]},
        finding_actions=[
            FindingAction(
                finding_id="f-req",
                action="challenge",
                actor_role="planner",
                artifact_revision=2,
                finding_set_id="set-1",
                rationale="not applicable",
                proposed_disposition="invalid",
                challenge_reason="invalid",
            ).to_dict()
        ],
        **_FAMILY_PROTOCOL_VERSIONS,
    )
    status = derive_family_operational_status(loop, "family-1")
    assert status != "owner_sweep_pending"


def test_active_families_includes_family_pending_verification_sweep() -> None:
    from top_down_planning.domain.finding_families import FindingFamily

    finding = ReviewFinding(
        id="f-1",
        severity="blocker",
        category="correctness",
        target_refs=["item-a"],
        issue="x",
        recommended_change="y",
        family_id="family-1",
        status="resolved",
    )
    family = FindingFamily(
        id="family-1",
        finding_set_id="set-1",
        rule_id="dependency.acceptance_capability_available",
        subject_key="reset",
        scope_kind="active-plan",
        family_fingerprint=compute_family_fingerprint(
            rule_id="dependency.acceptance_capability_available",
            subject_key="reset",
            scope_kind="active-plan",
        ),
        title="t",
        seed_finding_id="f-1",
        confirmed_finding_ids=["f-1"],
        candidate_refs=[],
        recommended_change="fix",
    )
    loop = make_review_loop(
        id="loop-1",
        type="whole_plan",
        finding_set_id="set-1",
        findings=[finding],
        finding_families=[family.to_dict()],
        finding_ids_by_set={"set-1": ["f-1"]},
        finding_actions=[
            {
                "finding_id": "f-1",
                "action": "fix",
                "actor_role": "planner",
                "artifact_revision": 1,
                "finding_set_id": "set-1",
            }
        ],
        family_sweeps=[
            {
                "id": "sweep-owner-1",
                "family_id": "family-1",
                "actor_role": "planner",
                "stage": "owner_fix",
                "artifact_revision": 1,
                "artifact_digest": "digest-1",
                "finding_set_id": "set-1",
                "searched_refs": ["active-items:*"],
                "search_dimensions": ["acceptance"],
                "additional_fixed_refs": [],
                "remaining_instance_refs": [],
                "completed": True,
                "summary": "swept",
                "evidence": [],
            }
        ],
        **_FAMILY_PROTOCOL_VERSIONS,
    )
    assert active_families(loop, artifact_revision=1, artifact_digest="digest-1")


def test_active_families_excludes_fully_closed_family() -> None:
    from top_down_planning.domain.finding_families import FindingFamily

    finding = ReviewFinding(
        id="f-1",
        severity="blocker",
        category="correctness",
        target_refs=["item-a"],
        issue="x",
        recommended_change="y",
        family_id="family-1",
        status="resolved",
    )
    family = FindingFamily(
        id="family-1",
        finding_set_id="set-1",
        rule_id="dependency.acceptance_capability_available",
        subject_key="reset",
        scope_kind="active-plan",
        family_fingerprint=compute_family_fingerprint(
            rule_id="dependency.acceptance_capability_available",
            subject_key="reset",
            scope_kind="active-plan",
        ),
        title="t",
        seed_finding_id="f-1",
        confirmed_finding_ids=["f-1"],
        candidate_refs=[],
        recommended_change="fix",
    )
    loop = make_review_loop(
        id="loop-1",
        type="whole_plan",
        finding_set_id="set-1",
        findings=[finding],
        finding_families=[family.to_dict()],
        finding_ids_by_set={"set-1": ["f-1"]},
        finding_actions=[
            {
                "finding_id": "f-1",
                "action": "fix",
                "actor_role": "planner",
                "artifact_revision": 1,
                "finding_set_id": "set-1",
            }
        ],
        family_sweeps=[
            {
                "id": "sweep-owner-1",
                "family_id": "family-1",
                "actor_role": "planner",
                "stage": "owner_fix",
                "artifact_revision": 1,
                "artifact_digest": "digest-1",
                "finding_set_id": "set-1",
                "searched_refs": ["active-items:*"],
                "search_dimensions": ["acceptance"],
                "additional_fixed_refs": [],
                "remaining_instance_refs": [],
                "completed": True,
                "summary": "swept",
                "evidence": [],
            },
            {
                "id": "sweep-verify-1",
                "family_id": "family-1",
                "actor_role": "reviewer",
                "stage": "verification",
                "artifact_revision": 1,
                "artifact_digest": "digest-1",
                "finding_set_id": "set-1",
                "searched_refs": ["active-items:*"],
                "search_dimensions": ["acceptance"],
                "additional_fixed_refs": [],
                "remaining_instance_refs": [],
                "completed": True,
                "summary": "verified",
                "evidence": [],
            },
        ],
        **_FAMILY_PROTOCOL_VERSIONS,
    )
    assert active_families(loop, artifact_revision=1, artifact_digest="digest-1") == []


def test_active_families_includes_optional_open_fix_member() -> None:
    from top_down_planning.domain.finding_families import FindingFamily

    finding = ReviewFinding(
        id="f-opt",
        severity="minor",
        category="correctness",
        target_refs=["item-b"],
        issue="x",
        recommended_change="y",
        family_id="family-1",
    )
    family = FindingFamily(
        id="family-1",
        finding_set_id="set-1",
        rule_id="dependency.acceptance_capability_available",
        subject_key="reset",
        scope_kind="active-plan",
        family_fingerprint=compute_family_fingerprint(
            rule_id="dependency.acceptance_capability_available",
            subject_key="reset",
            scope_kind="active-plan",
        ),
        title="t",
        seed_finding_id="f-opt",
        confirmed_finding_ids=["f-opt"],
        candidate_refs=[],
        recommended_change="fix",
    )
    loop = make_review_loop(
        id="loop-1",
        type="whole_plan",
        finding_set_id="set-1",
        findings=[finding],
        finding_families=[family.to_dict()],
        finding_ids_by_set={"set-1": ["f-opt"]},
        finding_actions=[
            {
                "finding_id": "f-opt",
                "action": "fix",
                "actor_role": "planner",
                "artifact_revision": 1,
                "finding_set_id": "set-1",
            }
        ],
        **_FAMILY_PROTOCOL_VERSIONS,
    )
    assert active_families(loop)


def test_verified_rejects_without_verification_sweep() -> None:
    from top_down_planning.agent_tool.review_verification import (
        merge_whole_plan_verification,
    )
    from top_down_planning.domain.finding_families import FindingFamily

    finding = ReviewFinding(
        id="f-1",
        severity="blocker",
        category="correctness",
        target_refs=["item-a"],
        issue="x",
        recommended_change="y",
        family_id="family-1",
        status="resolved",
    )
    family = FindingFamily(
        id="family-1",
        finding_set_id="set-1",
        rule_id="dependency.acceptance_capability_available",
        subject_key="reset",
        scope_kind="active-plan",
        family_fingerprint=compute_family_fingerprint(
            rule_id="dependency.acceptance_capability_available",
            subject_key="reset",
            scope_kind="active-plan",
        ),
        title="t",
        seed_finding_id="f-1",
        confirmed_finding_ids=["f-1"],
        candidate_refs=[],
        recommended_change="fix",
    )
    loop = make_review_loop(
        id="loop-1",
        type="whole_plan",
        finding_set_id="set-1",
        findings=[finding],
        finding_families=[family.to_dict()],
        finding_ids_by_set={"set-1": ["f-1"]},
        finding_actions=[
            {
                "finding_id": "f-1",
                "action": "fix",
                "actor_role": "planner",
                "artifact_revision": 1,
                "finding_set_id": "set-1",
            }
        ],
        family_sweeps=[
            {
                "id": "sweep-owner-1",
                "family_id": "family-1",
                "actor_role": "planner",
                "stage": "owner_fix",
                "artifact_revision": 1,
                "artifact_digest": "digest-1",
                "finding_set_id": "set-1",
                "searched_refs": ["active-items:*"],
                "search_dimensions": ["acceptance"],
                "additional_fixed_refs": [],
                "remaining_instance_refs": [],
                "completed": True,
                "summary": "swept",
                "evidence": [],
            }
        ],
        **_FAMILY_PROTOCOL_VERSIONS,
    )
    with pytest.raises(ValueError, match="missing family_result"):
        merge_whole_plan_verification(
            loop,
            {
                "decision": "verified",
                "finding_set_id": "set-1",
                "target_digest": "digest-1",
                "finding_results": [
                    {
                        "finding_id": "f-1",
                        "disposition": "resolved",
                        "evidence": [],
                        "direct_side_effects": [],
                    }
                ],
                "family_results": [],
                "new_direct_side_effect_findings": [],
                "summary": "verified",
            },
            artifact_revision=1,
            artifact_digest="digest-1",
        )


def test_family_fix_idempotent_replay_ignores_current_revision() -> None:
    from top_down_planning.agent_tool.review_owner_actions import apply_family_fixes
    from top_down_planning.domain.finding_families import FindingFamily

    finding = ReviewFinding(
        id="f-1",
        severity="blocker",
        category="correctness",
        target_refs=["item-a"],
        issue="x",
        recommended_change="y",
        family_id="family-1",
    )
    family = FindingFamily(
        id="family-1",
        finding_set_id="set-1",
        rule_id="dependency.acceptance_capability_available",
        subject_key="reset",
        scope_kind="active-plan",
        family_fingerprint=compute_family_fingerprint(
            rule_id="dependency.acceptance_capability_available",
            subject_key="reset",
            scope_kind="active-plan",
        ),
        title="t",
        seed_finding_id="f-1",
        confirmed_finding_ids=["f-1"],
        candidate_refs=[],
        recommended_change="fix",
    )
    owner_sweep = {
        "artifact_revision": 1,
        "artifact_digest": "digest-1",
        "searched_refs": ["active-items:*"],
        "search_dimensions": ["acceptance"],
        "additional_fixed_refs": [],
        "remaining_instance_refs": [],
        "completed": True,
        "summary": "swept",
    }
    loop = make_review_loop(
        id="loop-1",
        type="whole_plan",
        finding_set_id="set-1",
        findings=[finding],
        finding_families=[family.to_dict()],
        finding_ids_by_set={"set-1": ["f-1"]},
        **_FAMILY_PROTOCOL_VERSIONS,
    )
    updated, _, _ = apply_family_fixes(
        loop,
        {
            "family_fixes": [
                {
                    "family_id": "family-1",
                    "target_finding_ids": [],
                    "rationale": "fixed",
                    "changed_refs": ["item-a"],
                    "owner_sweep": owner_sweep,
                }
            ],
            "finding_actions": [],
        },
        actor_role="planner",
        artifact_revision=1,
        artifact_digest="digest-1",
        current_artifact_revision=1,
    )
    replayed, actions, _ = apply_family_fixes(
        updated,
        {
            "family_fixes": [
                {
                    "family_id": "family-1",
                    "target_finding_ids": [],
                    "rationale": "fixed",
                    "changed_refs": ["item-a"],
                    "owner_sweep": owner_sweep,
                }
            ],
            "finding_actions": [],
        },
        actor_role="planner",
        artifact_revision=1,
        artifact_digest="digest-1",
        current_artifact_revision=2,
    )
    assert replayed is updated
    assert actions == []


def test_loop_round_trip_preserves_explicit_versions() -> None:
    loop = make_review_loop(
        id="loop-v2",
        type="focused_plan",
        review_record_schema_version=2,
        review_contract_version=1,
    )
    payload = loop.to_dict()
    restored = ReviewLoop.from_dict(payload)
    assert restored.review_record_schema_version == 2
    assert restored.review_contract_version == 1
    assert "review_schema_version" not in payload


def test_digest_canonical_payload_is_deterministic() -> None:
    assert digest_canonical_payload({"a": 1}) == digest_canonical_payload({"a": 1})


def test_completed_discovery_rejects_orphan_family_id() -> None:
    from top_down_planning.agent_tool.review_discovery import _parse_whole_plan_families

    loop = make_review_loop(
        id="loop-1",
        type="whole_plan",
        finding_set_id="set-1",
        **_FAMILY_PROTOCOL_VERSIONS,
    )
    with pytest.raises(ValueError, match="finding_families"):
        _parse_whole_plan_families(
            {
                "finding_families": [],
                "reported_findings": [
                    {
                        "id": "f-1",
                        "family_id": "family-missing",
                        "severity": "major",
                        "category": "correctness",
                        "target_refs": ["item-a"],
                        "issue": "x",
                        "recommended_change": "y",
                        "instance_ref": {
                            "kind": "plan_item_field",
                            "item_id": "item-a",
                            "field": "acceptance",
                            "value_digest": digest_field_value("x"),
                            "duplicate_ordinal": 0,
                        },
                    }
                ],
                "finding_set_id": "set-1",
                "review_completed": True,
            },
            loop=loop,
            finding_set_id="set-1",
            stage="initial_review",
            review_completed=True,
            artifact_revision=1,
            artifact_digest="digest-1",
        )


def test_completed_discovery_rejects_unknown_family_reference() -> None:
    from top_down_planning.agent_tool.review_discovery import _parse_whole_plan_families

    loop = make_review_loop(
        id="loop-1",
        type="whole_plan",
        finding_set_id="set-1",
        **_FAMILY_PROTOCOL_VERSIONS,
    )
    fingerprint = compute_family_fingerprint(
        rule_id="dependency.acceptance_capability_available",
        subject_key="reset",
        scope_kind="active-plan",
    )
    with pytest.raises(ValueError, match="unknown family_id"):
        _parse_whole_plan_families(
            {
                "finding_families": [
                    {
                        "id": "family-1",
                        "finding_set_id": "set-1",
                        "rule_id": "dependency.acceptance_capability_available",
                        "subject_key": "reset",
                        "scope_kind": "active-plan",
                        "family_fingerprint": fingerprint,
                        "title": "t",
                        "seed_finding_id": "f-1",
                        "confirmed_finding_ids": ["f-1"],
                        "candidate_refs": [],
                        "recommended_change": "fix",
                        "discovery_sweep": {
                            "artifact_revision": 1,
                            "artifact_digest": "digest-1",
                            "completed": True,
                            "searched_refs": ["active-items:*"],
                            "search_dimensions": ["acceptance"],
                            "summary": "searched",
                        },
                    }
                ],
                "reported_findings": [
                    {
                        "id": "f-1",
                        "family_id": "family-other",
                        "severity": "major",
                        "category": "correctness",
                        "target_refs": ["item-a"],
                        "issue": "x",
                        "recommended_change": "y",
                        "instance_ref": {
                            "kind": "plan_item_field",
                            "item_id": "item-a",
                            "field": "acceptance",
                            "value_digest": digest_field_value("x"),
                            "duplicate_ordinal": 0,
                        },
                    }
                ],
                "finding_set_id": "set-1",
                "review_completed": True,
            },
            loop=loop,
            finding_set_id="set-1",
            stage="initial_review",
            review_completed=True,
            artifact_revision=1,
            artifact_digest="digest-1",
        )


def test_discovery_sweep_rejects_remaining_instance_refs() -> None:
    from top_down_planning.agent_tool.review_discovery import _parse_whole_plan_families

    loop = make_review_loop(
        id="loop-1",
        type="whole_plan",
        finding_set_id="set-1",
        **_FAMILY_PROTOCOL_VERSIONS,
    )
    fingerprint = compute_family_fingerprint(
        rule_id="dependency.acceptance_capability_available",
        subject_key="reset",
        scope_kind="active-plan",
    )
    with pytest.raises(ValueError, match="remaining_instance_refs"):
        _parse_whole_plan_families(
            {
                "finding_families": [
                    {
                        "id": "family-1",
                        "finding_set_id": "set-1",
                        "rule_id": "dependency.acceptance_capability_available",
                        "subject_key": "reset",
                        "scope_kind": "active-plan",
                        "family_fingerprint": fingerprint,
                        "title": "t",
                        "seed_finding_id": "f-1",
                        "confirmed_finding_ids": ["f-1"],
                        "candidate_refs": [],
                        "recommended_change": "fix",
                        "discovery_sweep": {
                            "artifact_revision": 1,
                            "artifact_digest": "digest-1",
                            "completed": True,
                            "searched_refs": ["active-items:*"],
                            "search_dimensions": ["acceptance"],
                            "summary": "searched",
                            "remaining_instance_refs": [
                                {
                                    "kind": "plan_item_field",
                                    "item_id": "item-a",
                                    "field": "acceptance",
                                    "value_digest": digest_field_value("x"),
                                    "duplicate_ordinal": 0,
                                }
                            ],
                        },
                    }
                ],
                "reported_findings": [
                    {
                        "id": "f-1",
                        "family_id": "family-1",
                        "severity": "major",
                        "category": "correctness",
                        "target_refs": ["item-a"],
                        "issue": "x",
                        "recommended_change": "y",
                        "instance_ref": {
                            "kind": "plan_item_field",
                            "item_id": "item-a",
                            "field": "acceptance",
                            "value_digest": digest_field_value("x"),
                            "duplicate_ordinal": 0,
                        },
                    }
                ],
                "finding_set_id": "set-1",
                "review_completed": True,
            },
            loop=loop,
            finding_set_id="set-1",
            stage="initial_review",
            review_completed=True,
            artifact_revision=1,
            artifact_digest="digest-1",
        )


def test_verification_merge_returns_findings_with_remaining_instances() -> None:
    from top_down_planning.agent_tool.review_verification import (
        merge_whole_plan_verification,
    )
    from top_down_planning.domain.finding_families import FindingFamily

    finding = ReviewFinding(
        id="f-1",
        severity="blocker",
        category="correctness",
        target_refs=["item-a"],
        issue="x",
        recommended_change="y",
        family_id="family-1",
    )
    family = FindingFamily(
        id="family-1",
        finding_set_id="set-1",
        rule_id="dependency.acceptance_capability_available",
        subject_key="reset",
        scope_kind="active-plan",
        family_fingerprint=compute_family_fingerprint(
            rule_id="dependency.acceptance_capability_available",
            subject_key="reset",
            scope_kind="active-plan",
        ),
        title="t",
        seed_finding_id="f-1",
        confirmed_finding_ids=["f-1"],
        candidate_refs=[],
        recommended_change="fix",
    )
    loop = make_review_loop(
        id="loop-1",
        type="whole_plan",
        finding_set_id="set-1",
        findings=[finding],
        finding_families=[family.to_dict()],
        finding_ids_by_set={"set-1": ["f-1"]},
        finding_actions=[
            {
                "finding_id": "f-1",
                "action": "fix",
                "actor_role": "planner",
                "artifact_revision": 1,
                "finding_set_id": "set-1",
            }
        ],
        lifecycle_status="verification_pending",
        active_stage="finding_verification",
        **_FAMILY_PROTOCOL_VERSIONS,
    )
    loop = replace(
        loop,
        family_sweeps=[
            {
                "id": "sweep-owner-1",
                "family_id": "family-1",
                "actor_role": "planner",
                "stage": "owner_fix",
                "artifact_revision": 1,
                "artifact_digest": "digest-1",
                "finding_set_id": "set-1",
                "searched_refs": ["active-items:*"],
                "search_dimensions": ["acceptance"],
                "additional_fixed_refs": [],
                "remaining_instance_refs": [],
                "completed": True,
                "summary": "swept",
                "evidence": [],
            }
        ],
    )
    merged_findings, _, updated_loop, _ = merge_whole_plan_verification(
        loop,
        {
            "decision": "needs_revision",
            "finding_set_id": "set-1",
            "target_digest": "digest-1",
            "finding_results": [
                {
                    "finding_id": "f-1",
                    "disposition": "unresolved",
                    "evidence": [],
                    "direct_side_effects": [],
                }
            ],
            "family_results": [
                {
                    "family_id": "family-1",
                    "disposition": "open",
                    "verification_sweep": {
                        "artifact_revision": 1,
                        "artifact_digest": "digest-1",
                        "searched_refs": ["active-items:*"],
                        "search_dimensions": ["acceptance"],
                        "remaining_instance_refs": [],
                        "completed": True,
                        "summary": "still open",
                    },
                    "remaining_instance_findings": [
                        {
                            "id": "f-2",
                            "family_id": "family-1",
                            "severity": "blocker",
                            "category": "correctness",
                            "target_refs": ["item-b"],
                            "issue": "another instance",
                            "recommended_change": "fix",
                            "instance_ref": {
                                "kind": "plan_item_field",
                                "item_id": "item-b",
                                "field": "acceptance",
                                "value_digest": digest_field_value("another"),
                                "duplicate_ordinal": 0,
                            },
                        }
                    ],
                }
            ],
            "new_direct_side_effect_findings": [],
            "summary": "family still open",
        },
        artifact_revision=1,
        artifact_digest="digest-1",
    )
    assert any(finding.id == "f-2" for finding in merged_findings)
    assert any(finding.id == "f-2" for finding in updated_loop.findings)
    assert "f-2" in updated_loop.finding_ids_by_set["set-1"]


def _family_verification_loop() -> ReviewLoop:
    from top_down_planning.domain.finding_families import FindingFamily

    finding = ReviewFinding(
        id="f-1",
        severity="blocker",
        category="correctness",
        target_refs=["item-a"],
        issue="x",
        recommended_change="y",
        family_id="family-1",
        status="resolved",
    )
    family = FindingFamily(
        id="family-1",
        finding_set_id="set-1",
        rule_id="dependency.acceptance_capability_available",
        subject_key="reset",
        scope_kind="active-plan",
        family_fingerprint=compute_family_fingerprint(
            rule_id="dependency.acceptance_capability_available",
            subject_key="reset",
            scope_kind="active-plan",
        ),
        title="t",
        seed_finding_id="f-1",
        confirmed_finding_ids=["f-1"],
        candidate_refs=[],
        recommended_change="fix",
    )
    return make_review_loop(
        id="loop-1",
        type="whole_plan",
        finding_set_id="set-1",
        findings=[finding],
        finding_families=[family.to_dict()],
        finding_ids_by_set={"set-1": ["f-1"]},
        finding_actions=[
            {
                "finding_id": "f-1",
                "action": "fix",
                "actor_role": "planner",
                "artifact_revision": 1,
                "finding_set_id": "set-1",
            }
        ],
        family_sweeps=[
            {
                "id": "sweep-owner-1",
                "family_id": "family-1",
                "actor_role": "planner",
                "stage": "owner_fix",
                "artifact_revision": 1,
                "artifact_digest": "digest-1",
                "finding_set_id": "set-1",
                "searched_refs": ["active-items:*"],
                "search_dimensions": ["acceptance"],
                "additional_fixed_refs": [],
                "remaining_instance_refs": [],
                "completed": True,
                "summary": "swept",
                "evidence": [],
            }
        ],
        lifecycle_status="verification_pending",
        active_stage="finding_verification",
        **_FAMILY_PROTOCOL_VERSIONS,
    )


def test_verified_rejects_open_family_disposition() -> None:
    from top_down_planning.agent_tool.review_verification import (
        merge_whole_plan_verification,
    )

    with pytest.raises(ValueError, match="disposition closed"):
        merge_whole_plan_verification(
            _family_verification_loop(),
            {
                "decision": "verified",
                "finding_set_id": "set-1",
                "target_digest": "digest-1",
                "finding_results": [
                    {
                        "finding_id": "f-1",
                        "disposition": "resolved",
                        "evidence": [],
                        "direct_side_effects": [],
                    }
                ],
                "family_results": [
                    {
                        "family_id": "family-1",
                        "disposition": "open",
                        "verification_sweep": {
                            "artifact_revision": 1,
                            "artifact_digest": "digest-1",
                            "searched_refs": ["active-items:*"],
                            "search_dimensions": ["acceptance"],
                            "remaining_instance_refs": [],
                            "completed": True,
                            "summary": "still open",
                        },
                        "remaining_instance_findings": [],
                    }
                ],
                "new_direct_side_effect_findings": [],
                "summary": "verified",
            },
            artifact_revision=1,
            artifact_digest="digest-1",
        )


def test_family_findings_scopes_to_active_finding_set_membership() -> None:
    from top_down_planning.domain.finding_families import (
        FindingFamily,
        family_findings,
    )

    finding_in_set = ReviewFinding(
        id="f-in",
        severity="blocker",
        category="correctness",
        target_refs=["item-a"],
        issue="x",
        recommended_change="y",
        family_id="family-1",
    )
    finding_orphan = ReviewFinding(
        id="f-orphan",
        severity="blocker",
        category="correctness",
        target_refs=["item-b"],
        issue="x",
        recommended_change="y",
        family_id="family-1",
    )
    family = FindingFamily(
        id="family-1",
        finding_set_id="set-1",
        rule_id="dependency.acceptance_capability_available",
        subject_key="reset",
        scope_kind="active-plan",
        family_fingerprint=compute_family_fingerprint(
            rule_id="dependency.acceptance_capability_available",
            subject_key="reset",
            scope_kind="active-plan",
        ),
        title="t",
        seed_finding_id="f-in",
        confirmed_finding_ids=["f-in", "f-orphan"],
        candidate_refs=[],
        recommended_change="fix",
    )
    loop = make_review_loop(
        id="loop-1",
        type="whole_plan",
        finding_set_id="set-1",
        findings=[finding_in_set, finding_orphan],
        finding_families=[family.to_dict()],
        finding_ids_by_set={"set-1": ["f-in"]},
        **_FAMILY_PROTOCOL_VERSIONS,
    )
    scoped = family_findings(loop, "family-1", finding_set_id="set-1")
    assert [finding.id for finding in scoped] == ["f-in"]


def test_completed_owner_sweep_requires_search_metadata() -> None:
    from top_down_planning.agent_tool.review_owner_actions import apply_family_fixes
    from top_down_planning.domain.finding_families import FindingFamily

    finding = ReviewFinding(
        id="f-1",
        severity="blocker",
        category="correctness",
        target_refs=["item-a"],
        issue="x",
        recommended_change="y",
        family_id="family-1",
    )
    family = FindingFamily(
        id="family-1",
        finding_set_id="set-1",
        rule_id="dependency.acceptance_capability_available",
        subject_key="reset",
        scope_kind="active-plan",
        family_fingerprint=compute_family_fingerprint(
            rule_id="dependency.acceptance_capability_available",
            subject_key="reset",
            scope_kind="active-plan",
        ),
        title="t",
        seed_finding_id="f-1",
        confirmed_finding_ids=["f-1"],
        candidate_refs=[],
        recommended_change="fix",
    )
    loop = make_review_loop(
        id="loop-1",
        type="whole_plan",
        finding_set_id="set-1",
        findings=[finding],
        finding_families=[family.to_dict()],
        finding_ids_by_set={"set-1": ["f-1"]},
        **_FAMILY_PROTOCOL_VERSIONS,
    )
    with pytest.raises(ValueError, match="searched_refs"):
        apply_family_fixes(
            loop,
            {
                "family_fixes": [
                    {
                        "family_id": "family-1",
                        "target_finding_ids": [],
                        "rationale": "fixed",
                        "changed_refs": ["item-a"],
                        "owner_sweep": {
                            "artifact_revision": 1,
                            "artifact_digest": "digest-1",
                            "searched_refs": [],
                            "search_dimensions": ["acceptance"],
                            "additional_fixed_refs": [],
                            "remaining_instance_refs": [],
                            "completed": True,
                            "summary": "swept",
                        },
                    }
                ],
                "finding_actions": [],
            },
            actor_role="planner",
            artifact_revision=1,
            artifact_digest="digest-1",
            current_artifact_revision=1,
        )
