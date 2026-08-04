"""Domain tests for review families, versioning, and artifact refs."""

from __future__ import annotations

from pathlib import Path

import pytest

from dataclasses import replace

from tests.helpers import (
    create_run_kwargs,
    grant_capability,
    make_review_loop,
    mandatory_plan_digest,
    minimal_resolved_config,
)
from top_down_planning.orchestrator.phases import PLANNING

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
    legacy = make_review_loop(
        id="loop-2",
        type="whole_plan",
        review_record_schema_version=LEGACY_REVIEW_RECORD_SCHEMA_VERSION,
        review_contract_version=LEGACY_REVIEW_CONTRACT_VERSION,
    )
    assert not uses_finding_family_protocol(legacy)


def test_new_whole_plan_review_loop_sets_contract_v2() -> None:
    loop = new_whole_plan_review_loop(
        loop_id="review-whole-plan-01",
        target_revision=1,
        config={"review": {"whole_plan": {"revise_at": "blocker"}}},
    )
    assert loop.review_record_schema_version == CURRENT_REVIEW_RECORD_SCHEMA_VERSION
    assert loop.review_contract_version == CURRENT_REVIEW_CONTRACT_VERSION


def test_new_whole_output_review_loop_uses_contract_v2() -> None:
    loop = new_whole_output_review_loop(
        loop_id="review-whole-output-01",
        target_revision=1,
        config={"review": {"whole_output": {"revise_at": "blocker"}}},
    )
    assert loop.review_record_schema_version == CURRENT_REVIEW_RECORD_SCHEMA_VERSION
    assert loop.review_contract_version == CURRENT_REVIEW_CONTRACT_VERSION


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


def test_focused_plan_family_fingerprint_uses_focused_plan_scope() -> None:
    fingerprint = compute_family_fingerprint(
        rule_id="dependency.acceptance_capability_available",
        subject_key="API acceptance",
        scope_kind="focused-plan",
    )
    other = compute_family_fingerprint(
        rule_id="dependency.acceptance_capability_available",
        subject_key="API acceptance",
        scope_kind="active-plan",
    )
    assert fingerprint != other


def test_focused_output_family_fingerprint_uses_focused_output_scope() -> None:
    fingerprint = compute_family_fingerprint(
        rule_id="dependency.acceptance_capability_available",
        subject_key="item-api evidence",
        scope_kind="focused-output",
    )
    other = compute_family_fingerprint(
        rule_id="dependency.acceptance_capability_available",
        subject_key="item-api evidence",
        scope_kind="whole-output",
    )
    assert fingerprint != other


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


def test_active_families_includes_family_pending_owner_sweep() -> None:
    from top_down_planning.domain.finding_families import (
        FindingFamily,
        derive_family_operational_status,
    )

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
            }
        ],
        **_FAMILY_PROTOCOL_VERSIONS,
    )
    assert (
        derive_family_operational_status(
            loop,
            "family-1",
            artifact_revision=1,
            artifact_digest="digest-1",
        )
        == "owner_sweep_pending"
    )
    active = active_families(loop, artifact_revision=1, artifact_digest="digest-1")
    assert [item.id for item in active] == ["family-1"]


def test_owner_sweep_pending_family_surfaces_in_owner_package_views() -> None:
    from top_down_planning.domain.finding_families import (
        FindingFamily,
        build_active_family_view,
        family_observability_fields,
    )

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
            }
        ],
        **_FAMILY_PROTOCOL_VERSIONS,
    )
    view = build_active_family_view(loop, artifact_revision=1, artifact_digest="digest-1")
    observability = family_observability_fields(
        loop,
        artifact_revision=1,
        artifact_digest="digest-1",
    )
    assert [item["id"] for item in view["families"]] == ["family-1"]
    assert view["families"][0]["operational_status"] == "owner_sweep_pending"
    assert observability["families_awaiting_owner_sweep"] == ["family-1"]
    assert observability["required_open_family_ids"] == ["family-1"]


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
        merge_mandatory_family_verification,
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
        merge_mandatory_family_verification(
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


def test_output_family_fix_records_producer_owner_sweep() -> None:
    from top_down_planning.agent_tool.review_owner_actions import apply_family_fixes
    from top_down_planning.domain.artifact_refs import digest_field_value
    from top_down_planning.domain.finding_families import (
        FindingFamily,
        compute_family_fingerprint,
    )

    finding = ReviewFinding(
        id="f-1",
        severity="blocker",
        category="correctness",
        target_refs=["item-leaf"],
        issue="Missing evidence.",
        recommended_change="Add artifact.",
        family_id="family-output-1",
    )
    family = FindingFamily(
        id="family-output-1",
        finding_set_id="set-1",
        rule_id="custom.evidence-gap",
        subject_key="leaf-evidence",
        scope_kind="whole-output",
        rule_definition="output evidence completeness gap",
        family_fingerprint=compute_family_fingerprint(
            rule_id="custom.evidence-gap",
            subject_key="leaf-evidence",
            scope_kind="whole-output",
            rule_definition="output evidence completeness gap",
        ),
        title="Evidence gap",
        seed_finding_id="f-1",
        confirmed_finding_ids=["f-1"],
        candidate_refs=[],
        recommended_change="Add artifact.",
    )
    owner_sweep = {
        "artifact_revision": 2,
        "artifact_digest": "output-digest-2",
        "searched_refs": ["production:*"],
        "search_dimensions": ["evidence"],
        "additional_fixed_refs": [],
        "remaining_instance_refs": [],
        "completed": True,
        "summary": "Swept production evidence.",
    }
    loop = make_review_loop(
        id="loop-output",
        type="whole_output",
        finding_set_id="set-1",
        findings=[finding],
        finding_families=[family.to_dict()],
        finding_ids_by_set={"set-1": ["f-1"]},
        **_FAMILY_PROTOCOL_VERSIONS,
    )
    updated, actions, events = apply_family_fixes(
        loop,
        {
            "family_fixes": [
                {
                    "family_id": "family-output-1",
                    "target_finding_ids": [],
                    "rationale": "Added missing evidence.",
                    "changed_refs": [
                        {
                            "kind": "output_record",
                            "record_kind": "evidence",
                            "record_key": "evidence-01",
                            "field": "summary",
                            "value_digest": digest_field_value("artifact added"),
                        }
                    ],
                    "owner_sweep": owner_sweep,
                }
            ],
            "finding_actions": [],
        },
        actor_role="producer",
        artifact_revision=2,
        artifact_digest="output-digest-2",
        current_artifact_revision=2,
    )
    assert actions
    assert actions[0].actor_role == "producer"
    assert any(sweep.stage == "owner_fix" for sweep in updated.family_sweeps)
    assert any(event.get("type") == "review_family_owner_sweep_recorded" for event in events)


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
    from top_down_planning.agent_tool.review_discovery import _parse_mandatory_discovery_families

    loop = make_review_loop(
        id="loop-1",
        type="whole_plan",
        finding_set_id="set-1",
        **_FAMILY_PROTOCOL_VERSIONS,
    )
    with pytest.raises(ValueError, match="finding_families"):
        _parse_mandatory_discovery_families(
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
    from top_down_planning.agent_tool.review_discovery import _parse_mandatory_discovery_families

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
        _parse_mandatory_discovery_families(
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
    from top_down_planning.agent_tool.review_discovery import _parse_mandatory_discovery_families

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
        _parse_mandatory_discovery_families(
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
        merge_mandatory_family_verification,
    )
    from top_down_planning.domain.finding_families import (
        FamilySweepRecord,
        FindingFamily,
    )

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
            FamilySweepRecord.from_dict(
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
            )
        ],
    )
    merged_findings, _, updated_loop, _ = merge_mandatory_family_verification(
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
        merge_mandatory_family_verification,
    )

    with pytest.raises(ValueError, match="disposition closed"):
        merge_mandatory_family_verification(
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


def test_mandatory_output_discovery_rejects_plan_artifact_refs() -> None:
    from top_down_planning.agent_tool.review_discovery import (
        apply_mandatory_discovery_response,
    )
    from top_down_planning.config.defaults import DEFAULT_CONFIG
    from top_down_planning.domain.mandatory_audit_passes import WHOLE_OUTPUT_AUDIT_PASS_IDS
    from top_down_planning.orchestrator.review_analysis_context import rubric_items_with_ids

    loop = make_review_loop(
        id="loop-output",
        type="whole_output",
        finding_set_id="set-1",
        **_FAMILY_PROTOCOL_VERSIONS,
    )
    rubric_items = rubric_items_with_ids(
        [str(item) for item in DEFAULT_CONFIG["review"]["whole_output"]["rubric"]]
    )
    rubric_ids = [item["id"] for item in rubric_items]
    with pytest.raises(ValueError, match="plan_item_field"):
        apply_mandatory_discovery_response(
            loop,
            {
                "finding_set_id": "set-1",
                "review_completed": True,
                "summary": "Invalid plan ref on output gate",
                "target_digest": "output-digest-1",
                "audit_attestation": {
                    "artifact_revision": 1,
                    "artifact_digest": "output-digest-1",
                    "passes": [
                        {
                            "pass_id": pass_id,
                            "completed": True,
                            "scope_id": "whole-output-active-v1",
                            "search_dimensions": ["evidence"],
                            "inspected_refs": ["outputs:*"],
                            "rubric_item_ids": rubric_ids,
                            "summary": f"Completed {pass_id}.",
                        }
                        for pass_id in WHOLE_OUTPUT_AUDIT_PASS_IDS
                    ],
                },
                "finding_families": [
                    {
                        "id": "family-output-1",
                        "finding_set_id": "set-1",
                        "rule_id": "custom.evidence-gap",
                        "rule_definition": "output evidence completeness gap",
                        "subject_key": "leaf",
                        "scope_kind": "whole-output",
                        "title": "Evidence gap",
                        "seed_finding_id": "f-1",
                        "confirmed_finding_ids": ["f-1"],
                        "candidate_refs": [],
                        "recommended_change": "Fix evidence",
                        "discovery_sweep": {
                            "artifact_revision": 1,
                            "artifact_digest": "output-digest-1",
                            "searched_refs": ["outputs:*"],
                            "search_dimensions": ["evidence"],
                            "completed": True,
                            "summary": "Searched outputs.",
                        },
                    }
                ],
                "reported_findings": [
                    {
                        "id": "f-1",
                        "family_id": "family-output-1",
                        "instance_ref": {
                            "kind": "plan_item_field",
                            "item_id": "item-leaf",
                            "field": "acceptance",
                            "value_digest": "abc",
                        },
                        "severity": "blocker",
                        "category": "correctness",
                        "target_refs": ["item-leaf"],
                        "issue": "Bad ref kind",
                        "recommended_change": "Fix",
                    }
                ],
            },
            stage="initial_review",
            review_type="whole_output",
            artifact_revision=1,
            artifact_digest="output-digest-1",
            rubric=[
                str(item) for item in DEFAULT_CONFIG["review"]["whole_output"]["rubric"]
            ],
            allowed_artifact_ref_kinds=frozenset({"output_path", "output_record"}),
            family_scope_kind="whole-output",
        )


def test_discovery_accepts_custom_rule_with_definition() -> None:
    from top_down_planning.agent_tool.review_discovery import (
        apply_mandatory_discovery_response,
    )
    from top_down_planning.config.defaults import DEFAULT_CONFIG
    from top_down_planning.domain.mandatory_audit_passes import WHOLE_PLAN_AUDIT_PASS_IDS
    from top_down_planning.orchestrator.review_analysis_context import rubric_items_with_ids

    loop = make_review_loop(
        id="loop-custom",
        type="whole_plan",
        finding_set_id="set-1",
        **_FAMILY_PROTOCOL_VERSIONS,
    )
    rubric_items = rubric_items_with_ids(
        [str(item) for item in DEFAULT_CONFIG["review"]["whole_plan"]["rubric"]]
    )
    rubric_ids = [item["id"] for item in rubric_items]
    fingerprint = compute_family_fingerprint(
        rule_id="custom.reset-wiring",
        subject_key="reset",
        scope_kind="active-plan",
        rule_definition="Reset references must resolve through dependencies.",
    )
    updated, findings, outcome, events = apply_mandatory_discovery_response(
        loop,
        {
            "finding_set_id": "set-1",
            "review_completed": True,
            "summary": "Custom rule family",
            "target_digest": "digest-1",
            "audit_attestation": {
                "artifact_revision": 1,
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
            "reported_findings": [
                {
                "id": "f-1",
                "family_id": "family-custom",
                "severity": "blocker",
                "category": "correctness",
                    "target_refs": ["item-a"],
                    "issue": "Reset wiring",
                    "recommended_change": "Fix wiring",
                    "instance_ref": {
                        "kind": "plan_item_field",
                        "item_id": "item-a",
                        "field": "acceptance",
                        "value_digest": digest_field_value("Reset wiring"),
                        "duplicate_ordinal": 0,
                    },
                }
            ],
            "finding_families": [
                {
                    "id": "family-custom",
                    "finding_set_id": "set-1",
                    "rule_id": "custom.reset-wiring",
                    "rule_definition": "Reset references must resolve through dependencies.",
                    "subject_key": "reset",
                    "scope_kind": "active-plan",
                    "family_fingerprint": fingerprint,
                    "title": "Reset wiring",
                    "seed_finding_id": "f-1",
                    "confirmed_finding_ids": ["f-1"],
                    "candidate_refs": [],
                    "recommended_change": "Fix wiring",
                    "discovery_sweep": {
                        "artifact_revision": 1,
                        "artifact_digest": "digest-1",
                        "searched_refs": ["active-items:*"],
                        "search_dimensions": ["acceptance"],
                        "completed": True,
                        "summary": "Searched acceptance",
                    },
                }
            ],
        },
        stage="initial_review",
        review_type="whole_plan",
        artifact_revision=1,
        artifact_digest="digest-1",
        rubric=[str(item) for item in DEFAULT_CONFIG["review"]["whole_plan"]["rubric"]],
    )
    assert outcome == "changes_requested"
    assert len(updated.finding_families) == 1
    assert updated.finding_families[0].rule_id == "custom.reset-wiring"
    assert any(event["type"] == "review_finding_family_reported" for event in events)


def test_discovery_rejects_agent_submitted_reopen_fields() -> None:
    from top_down_planning.agent_tool.review_discovery import _reject_agent_reopen_fields

    with pytest.raises(ValueError, match="reopens_family_id"):
        _reject_agent_reopen_fields(
            {
                "finding_families": [{"reopens_family_id": "family-old"}],
            }
        )
    with pytest.raises(ValueError, match="reopens_finding_id"):
        _reject_agent_reopen_fields(
            {
                "reported_findings": [{"reopens_finding_id": "f-old"}],
            }
        )


def test_plan_apply_without_record_actions_can_resume_family_fix(tmp_path: Path) -> None:
    from top_down_planning.agent_tool import PlanAgentService, ReviewAgentService
    from top_down_planning.config.defaults import DEFAULT_CONFIG
    from top_down_planning.domain.mandatory_audit_passes import WHOLE_PLAN_AUDIT_PASS_IDS
    from top_down_planning.domain.models import Plan, PlanItem
    from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID
    from top_down_planning.domain.review_loop_factory import new_whole_plan_review_loop
    from top_down_planning.orchestrator.review_analysis_context import rubric_items_with_ids
    from top_down_planning.persistence.file_store import FileRunStore

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
    plan.items["item-a"] = PlanItem(
        id="item-a",
        parent_id=PLAN_ROOT_ITEM_ID,
        order_key="0000000001",
        title="item-a",
        outcome="Outcome",
        kind="work",
        acceptance=["Reset control must work end-to-end"],
    )
    next_plan = plan.to_dict()
    next_plan["revision"] = plan.revision + 1
    store.save_plan(run_id, next_plan, plan.revision)

    loop = new_whole_plan_review_loop(
        loop_id="review-whole-plan-01",
        target_revision=int(store.load_plan(run_id)["revision"]),
        config=config,
    )
    loop, finding_set_id = __import__(
        "top_down_planning.domain.reviews",
        fromlist=["allocate_discovery_finding_set_id"],
    ).allocate_discovery_finding_set_id(loop)
    store.save_review(run_id, loop.to_dict())

    target_revision = int(store.load_plan(run_id)["revision"])
    digest = mandatory_plan_digest(store, run_id)
    rubric_items = rubric_items_with_ids(
        [str(item) for item in DEFAULT_CONFIG["review"]["whole_plan"]["rubric"]]
    )
    rubric_ids = [item["id"] for item in rubric_items]
    fingerprint = compute_family_fingerprint(
        rule_id="dependency.acceptance_capability_available",
        subject_key="reset-control",
        scope_kind="active-plan",
    )
    discovery = {
        "loop_id": loop.id,
        "target_revision": target_revision,
        "stage": "initial_review",
        "finding_set_id": finding_set_id,
        "reported_findings": [
            {
                "id": "sf-001",
                "family_id": "family-reset",
                "severity": "blocker",
                "category": "architecture",
                "target_refs": ["item-a"],
                "issue": "Reset referenced before dependency exists",
                "recommended_change": "Normalize Reset references",
                "instance_ref": {
                    "kind": "plan_item_field",
                    "item_id": "item-a",
                    "field": "acceptance",
                    "value_digest": digest_field_value("Reset control must work end-to-end"),
                    "duplicate_ordinal": 0,
                },
            }
        ],
        "review_completed": True,
        "summary": "One Reset instance found",
        "target_digest": digest,
        "audit_attestation": {
            "artifact_revision": target_revision,
            "artifact_digest": digest,
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
        "finding_families": [
            {
                "id": "family-reset",
                "finding_set_id": finding_set_id,
                "rule_id": "dependency.acceptance_capability_available",
                "subject_key": "reset-control",
                "scope_kind": "active-plan",
                "family_fingerprint": fingerprint,
                "title": "Reset dependency closure",
                "seed_finding_id": "sf-001",
                "confirmed_finding_ids": ["sf-001"],
                "candidate_refs": [],
                "recommended_change": "Normalize Reset references",
                "discovery_sweep": {
                    "artifact_revision": target_revision,
                    "artifact_digest": digest,
                    "searched_refs": ["active-items:*"],
                    "search_dimensions": ["acceptance"],
                    "completed": True,
                    "summary": "Searched acceptance",
                },
            }
        ],
    }
    ReviewAgentService(store, run_id).respond(
        discovery,
        capability_token=grant_capability(
            store, run_id, role="reviewer", loop_id=loop.id, phase=PLANNING
        ),
    )

    PlanAgentService(store, run_id).apply(
        {
            "base_revision": target_revision,
            "operations": [
                {
                    "op": "update_item",
                    "item_id": "item-a",
                    "patch": {"acceptance": ["Reserved slot only"]},
                }
            ],
        },
        capability_token=grant_capability(store, run_id, role="planner", phase=PLANNING),
    )
    new_revision = int(store.load_plan(run_id)["revision"])
    new_digest = mandatory_plan_digest(store, run_id)

    ReviewAgentService(store, run_id).record_finding_actions(
        {
            "loop_id": loop.id,
            "artifact_revision": new_revision,
            "artifact_digest": new_digest,
            "family_fixes": [
                {
                    "family_id": "family-reset",
                    "target_finding_ids": [],
                    "rationale": "Normalized Reset reference",
                    "changed_refs": ["item-a"],
                    "owner_sweep": {
                        "artifact_revision": new_revision,
                        "artifact_digest": new_digest,
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
    loop_payload = store.load_review(run_id, loop.id)
    assert any(
        sweep.get("stage") == "owner_fix"
        for sweep in loop_payload.get("family_sweeps", [])
    )


def test_family_fixes_overlap_finding_actions_rejected() -> None:
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
    with pytest.raises(ValueError, match="overlap finding_actions"):
        apply_family_fixes(
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
                "finding_actions": [
                    {
                        "finding_id": "f-1",
                        "action": "fix",
                        "actor_role": "planner",
                        "artifact_revision": 1,
                        "finding_set_id": "set-1",
                        "rationale": "already fixing",
                    }
                ],
            },
            actor_role="planner",
            artifact_revision=1,
            artifact_digest="digest-1",
            current_artifact_revision=1,
        )


def test_family_fix_idempotent_replay_rejects_conflicting_digest() -> None:
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
    with pytest.raises(ValueError, match="conflicting request_digest"):
        apply_family_fixes(
            updated,
            {
                "family_fixes": [
                    {
                        "family_id": "family-1",
                        "target_finding_ids": [],
                        "rationale": "different rationale",
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


def test_optional_target_must_be_confirmed_family_member() -> None:
    finding_confirmed = ReviewFinding(
        id="f-req",
        severity="blocker",
        category="correctness",
        target_refs=["item-a"],
        issue="x",
        recommended_change="y",
        family_id="family-1",
    )
    finding_orphan = ReviewFinding(
        id="f-orphan",
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
        confirmed_finding_ids=["f-req"],
        candidate_refs=[],
        recommended_change="fix",
    )
    loop = make_review_loop(
        id="loop-1",
        type="whole_plan",
        finding_set_id="set-1",
        findings=[finding_confirmed, finding_orphan],
        finding_families=[family.to_dict()],
        finding_ids_by_set={"set-1": ["f-req"]},
        **_FAMILY_PROTOCOL_VERSIONS,
    )
    with pytest.raises(ValueError, match="confirmed member"):
        compute_effective_fix_target_ids(
            loop,
            "family-1",
            target_finding_ids=["f-orphan"],
            challenged_required_ids=set(),
        )


def test_discovery_regression_links_fingerprint_and_emits_event() -> None:
    from top_down_planning.agent_tool.review_discovery import (
        apply_mandatory_discovery_response,
    )
    from top_down_planning.config.defaults import DEFAULT_CONFIG
    from top_down_planning.domain.artifact_refs import digest_field_value
    from top_down_planning.domain.finding_families import FindingFamily
    from top_down_planning.domain.mandatory_audit_passes import WHOLE_PLAN_AUDIT_PASS_IDS
    from top_down_planning.orchestrator.review_analysis_context import (
        rubric_items_with_ids,
    )

    fingerprint = compute_family_fingerprint(
        rule_id="dependency.acceptance_capability_available",
        subject_key="reset",
        scope_kind="active-plan",
    )
    prior_family = FindingFamily(
        id="family-old",
        finding_set_id="set-0",
        rule_id="dependency.acceptance_capability_available",
        subject_key="reset",
        scope_kind="active-plan",
        family_fingerprint=fingerprint,
        title="Prior",
        seed_finding_id="f-old",
        confirmed_finding_ids=["f-old"],
        candidate_refs=[],
        recommended_change="fix",
    )
    loop = make_review_loop(
        id="loop-1",
        type="whole_plan",
        finding_set_id="set-1",
        findings=[
            ReviewFinding(
                id="f-old",
                severity="blocker",
                category="correctness",
                target_refs=["item-a"],
                issue="old",
                recommended_change="fix",
                family_id="family-old",
                status="resolved",
            )
        ],
        finding_families=[prior_family.to_dict()],
        finding_ids_by_set={"set-0": ["f-old"]},
        family_sweeps=[
            {
                "id": "sweep-verify-old",
                "family_id": "family-old",
                "actor_role": "reviewer",
                "stage": "verification",
                "artifact_revision": 1,
                "artifact_digest": "digest-1",
                "finding_set_id": "set-0",
                "searched_refs": ["active-items:*"],
                "search_dimensions": ["acceptance"],
                "additional_fixed_refs": [],
                "remaining_instance_refs": [],
                "completed": True,
                "summary": "closed",
            }
        ],
        **_FAMILY_PROTOCOL_VERSIONS,
    )
    instance_ref = {
        "kind": "plan_item_field",
        "item_id": "item-a",
        "field": "acceptance",
        "value_digest": digest_field_value("Reset wiring"),
        "duplicate_ordinal": 0,
    }
    rubric_items = rubric_items_with_ids(
        [str(item) for item in DEFAULT_CONFIG["review"]["whole_plan"]["rubric"]]
    )
    rubric_ids = [item["id"] for item in rubric_items]
    updated, _, _, events = apply_mandatory_discovery_response(
        loop,
        {
            "finding_set_id": "set-1",
            "review_completed": True,
            "target_digest": "digest-2",
            "summary": "Regression rediscovered",
            "reported_findings": [
                {
                    "id": "f-new",
                    "family_id": "family-new",
                    "severity": "blocker",
                    "category": "correctness",
                    "target_refs": ["item-a"],
                    "issue": "Reset wiring",
                    "recommended_change": "Fix wiring",
                    "instance_ref": instance_ref,
                }
            ],
            "finding_families": [
                {
                    "id": "family-new",
                    "finding_set_id": "set-1",
                    "rule_id": "dependency.acceptance_capability_available",
                    "subject_key": "reset",
                    "scope_kind": "active-plan",
                    "title": "Reset wiring",
                    "seed_finding_id": "f-new",
                    "confirmed_finding_ids": ["f-new"],
                    "candidate_refs": [],
                    "recommended_change": "Fix wiring",
                    "discovery_sweep": {
                        "artifact_revision": 2,
                        "artifact_digest": "digest-2",
                        "searched_refs": ["active-items:*"],
                        "search_dimensions": ["acceptance"],
                        "completed": True,
                        "summary": "Searched acceptance",
                    },
                }
            ],
            "audit_attestation": {
                "artifact_revision": 2,
                "artifact_digest": "digest-2",
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
        },
        stage="scope_review",
        review_type="whole_plan",
        artifact_revision=2,
        artifact_digest="digest-2",
        rubric=[str(item) for item in DEFAULT_CONFIG["review"]["whole_plan"]["rubric"]],
    )
    regressed = next(
        family for family in updated.finding_families if family.id == "family-new"
    )
    assert regressed.reopens_family_id == "family-old"
    assert any(event["type"] == "review_family_regressed" for event in events)


def test_family_observability_counts_latest_audit_run_only() -> None:
    from top_down_planning.domain.finding_families import family_observability_fields
    from top_down_planning.domain.mandatory_audit_passes import WHOLE_PLAN_AUDIT_PASS_IDS

    loop = make_review_loop(
        id="loop-1",
        type="whole_plan",
        finding_set_id="set-1",
        audit_runs=[
            {
                "id": "audit-1",
                "finding_set_id": "set-0",
                "artifact_revision": 1,
                "artifact_digest": "digest-1",
                "recorded_at": "2026-01-01T00:00:00Z",
                "passes": [
                    {"pass_id": pass_id, "completed": True}
                    for pass_id in WHOLE_PLAN_AUDIT_PASS_IDS
                ],
            },
            {
                "id": "audit-2",
                "finding_set_id": "set-1",
                "artifact_revision": 2,
                "artifact_digest": "digest-2",
                "recorded_at": "2026-01-02T00:00:00Z",
                "passes": [
                    {"pass_id": pass_id, "completed": True}
                    for pass_id in WHOLE_PLAN_AUDIT_PASS_IDS
                ],
            },
        ],
        **_FAMILY_PROTOCOL_VERSIONS,
    )
    fields = family_observability_fields(
        loop,
        artifact_revision=2,
        artifact_digest="digest-2",
    )
    assert fields["audit_passes_completed"] == len(WHOLE_PLAN_AUDIT_PASS_IDS)
    assert fields["audit_passes_required"] == len(WHOLE_PLAN_AUDIT_PASS_IDS)


def test_active_family_view_includes_discovery_sweep_dimensions() -> None:
    from top_down_planning.domain.finding_families import (
        FindingFamily,
        build_active_family_view,
    )

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
        family_sweeps=[
            {
                "id": "sweep-discovery-1",
                "family_id": "family-1",
                "actor_role": "reviewer",
                "stage": "discovery",
                "artifact_revision": 1,
                "artifact_digest": "digest-1",
                "finding_set_id": "set-1",
                "searched_refs": ["active-items:*"],
                "search_dimensions": ["acceptance", "depends_on"],
                "additional_fixed_refs": [],
                "remaining_instance_refs": [],
                "completed": True,
                "summary": "searched",
            }
        ],
        **_FAMILY_PROTOCOL_VERSIONS,
    )
    view = build_active_family_view(loop, artifact_revision=1, artifact_digest="digest-1")
    sweep = view["families"][0]["discovery_sweep"]
    assert sweep["search_dimensions"] == ["acceptance", "depends_on"]
    assert sweep["searched_refs"] == ["active-items:*"]


def test_mandatory_whole_plan_v1_respond_rejected(tmp_path: Path) -> None:
    from top_down_planning.agent_tool import ReviewAgentService
    from top_down_planning.agent_tool.errors import RequestError
    from top_down_planning.domain.models import Plan, PlanItem
    from top_down_planning.orchestrator.phases import WHOLE_PLAN_REVIEW
    from top_down_planning.persistence import FileRunStore
    from top_down_planning.persistence.digests import compute_plan_digest

    store = FileRunStore(tmp_path)
    run_id = "run-20260101T009950-009950"
    root = PlanItem(
        id="item-root",
        parent_id=None,
        order_key="0000000000",
        title="Root",
        outcome="Done.",
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
    loop = make_review_loop(
        id="review-whole-plan-legacy",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "whole_plan"},
        finding_set_id="review-whole-plan-legacy-fs-01",
        review_record_schema_version=LEGACY_REVIEW_RECORD_SCHEMA_VERSION,
        review_contract_version=LEGACY_REVIEW_CONTRACT_VERSION,
    )
    store.save_review(run_id, loop.to_dict())
    digest = compute_plan_digest(plan)
    token = grant_capability(
        store,
        run_id,
        role="reviewer",
        phase=WHOLE_PLAN_REVIEW,
        loop_id=loop.id,
        session_id="sess",
    )
    with pytest.raises(RequestError, match="contract v2"):
        ReviewAgentService(store, run_id).respond(
            {
                "loop_id": loop.id,
                "target_revision": 0,
                "stage": "initial_review",
                "finding_set_id": loop.finding_set_id,
                "reported_findings": [],
                "review_completed": True,
                "target_digest": digest,
                "summary": "Clear legacy review.",
            },
            capability_token=token,
        )
