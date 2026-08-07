"""Regression tests for Slice 2 domain invariants (TDP-S2-001 through TDP-S2-005)."""

from __future__ import annotations

import subprocess
import sys
import os
from pathlib import Path

import pytest

from top_down_planning.agent_tool import PlanAgentService
from top_down_planning.domain.models import Plan, PlanItem, PlanningLimits, Scope
from top_down_planning.domain.mutations import apply_operations
from top_down_planning.domain.errors import (
    InvalidMutationError,
    UnsupportedReviewSchemaVersionError,
)
from top_down_planning.domain.finding_families import (
    AuditAttestationPass,
    AuditAttestationRun,
    FamilySweepRecord,
)
from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID, display_traversal, seed_plan_root_item
from top_down_planning.domain.reviews import (
    ReviewFinding,
    ReviewLoop,
    UNSUPPORTED_REVIEW_SCHEMA_MESSAGE,
    findings_permit_approval,
    is_open_finding_status,
    is_terminal_review_loop,
    is_unresolved_finding_status,
    parse_finding_action,
    parse_review_version_fields,
)
from top_down_planning.domain.validators import validate_plan
from top_down_planning.persistence.digests import compute_plan_digest
from tests.helpers import grant_capability, make_review_loop, review_loop_dict_with_binding

_PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src"


def _minimal_plan_dict(**overrides: object) -> dict:
    root = seed_plan_root_item()
    payload = {
        "schema_version": 2,
        "id": "plan-001",
        "revision": 0,
        "output_goal": "Deliver the output.",
        "items": [
            {
                **root.to_dict(),
                "depth": 0,
            }
        ],
    }
    payload.update(overrides)
    return payload


def _plan_with_root_child() -> Plan:
    root = seed_plan_root_item()
    child = PlanItem(
        id="item-child",
        parent_id=PLAN_ROOT_ITEM_ID,
        order_key="0000000000",
        title="Child",
        kind="work",
    )
    return Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={PLAN_ROOT_ITEM_ID: root, "item-child": child},
    )


# --- TDP-S2-001: canonical root ---


@pytest.mark.parametrize(
    ("operations", "match"),
    [
        ([{"op": "remove_item", "item_id": PLAN_ROOT_ITEM_ID}], "canonical root"),
        ([{"op": "supersede_item", "item_id": PLAN_ROOT_ITEM_ID, "replacement": {"kind": "work", "title": "X"}}], "canonical root"),
        (
            [
                {
                    "op": "move_subtree",
                    "item_id": PLAN_ROOT_ITEM_ID,
                    "new_parent_id": "item-child",
                    "placement": {"last_child": True},
                }
            ],
            "canonical root",
        ),
        (
            [
                {
                    "op": "add_item",
                    "temp_id": "item-second-root",
                    "parent_id": None,
                    "item": {"kind": "aggregate", "title": "Second root"},
                }
            ],
            "parent_id",
        ),
        (
            [
                {
                    "op": "move_subtree",
                    "item_id": "item-child",
                    "new_parent_id": None,
                    "placement": {"last_child": True},
                }
            ],
            "parent_id",
        ),
        (
            [
                {
                    "op": "update_item",
                    "item_id": PLAN_ROOT_ITEM_ID,
                    "patch": {"kind": "work"},
                }
            ],
            "canonical root",
        ),
    ],
)
def test_root_destructive_mutations_are_rejected(operations: list[dict], match: str) -> None:
    plan = _plan_with_root_child()

    with pytest.raises(InvalidMutationError, match=match):
        apply_operations(
            plan,
            base_revision=1,
            operations=operations,
            reviews=[],
        )


def test_missing_root_fails_validation() -> None:
    plan = Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={
            "item-child": PlanItem(
                id="item-child",
                parent_id=None,
                order_key="0000000000",
                title="Orphan",
                kind="work",
            )
        },
    )

    result = validate_plan(plan, mode="approval")

    assert result.ok is False
    assert any(issue.code == "missing_canonical_root" for issue in result.issues)


def test_inactive_root_fails_validation() -> None:
    root = seed_plan_root_item()
    root.planning_status = "removed"
    plan = Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={PLAN_ROOT_ITEM_ID: root},
    )

    result = validate_plan(plan, mode="draft")

    assert result.ok is False
    assert any(issue.code == "inactive_canonical_root" for issue in result.issues)


def test_root_with_wrong_kind_fails_validation() -> None:
    root = seed_plan_root_item()
    root.kind = "work"
    plan = Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={PLAN_ROOT_ITEM_ID: root},
    )

    result = validate_plan(plan, mode="approval")

    assert result.ok is False
    assert any(issue.code == "invalid_canonical_root_kind" for issue in result.issues)


def test_active_item_outside_root_tree_fails_validation() -> None:
    root = seed_plan_root_item()
    orphan = PlanItem(
        id="item-orphan",
        parent_id=None,
        order_key="0000000000",
        title="Orphan",
        kind="work",
    )
    plan = Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={PLAN_ROOT_ITEM_ID: root, "item-orphan": orphan},
    )

    result = validate_plan(plan, mode="draft")

    assert result.ok is False
    assert any(issue.code == "multiple_active_roots" for issue in result.issues)


def test_agent_plan_apply_rejects_second_root(tmp_path) -> None:
    from top_down_planning.agent_tool.errors import OperationError
    from top_down_planning.orchestrator.phases import PLANNING
    from top_down_planning.persistence import FileRunStore
    from tests.helpers import create_run_kwargs

    run_id = "run-20260101T000001-000001"
    store = FileRunStore(tmp_path)
    plan = _plan_with_root_child()
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(tmp_path, resolved_config={"run": {"output_goal": plan.output_goal}}),
    )
    service = PlanAgentService(store, run_id)
    token = grant_capability(store, run_id, role="planner", phase=PLANNING)

    with pytest.raises(OperationError, match="parent_id"):
        service.apply(
            {
                "base_revision": 1,
                "operations": [
                    {
                        "op": "move_subtree",
                        "item_id": "item-child",
                        "new_parent_id": None,
                        "placement": {"last_child": True},
                    }
                ],
            },
            capability_token=token,
        )


# --- TDP-S2-002: review integrity ---


def _base_review_loop_payload(**overrides: object) -> dict:
    payload = review_loop_dict_with_binding(
        {
            "id": "review-whole-plan-01",
            "type": "whole_plan",
            "reviewer_session_id": "sess",
            "target_revision": 0,
            "scope": {"kind": "whole_plan"},
            "status": "pending",
            "revise_at": "blocker",
            "finding_set_id": "fs-01",
            "revision_cycles": 0,
            "revision": 0,
            "findings": [],
            "finding_actions": [],
            "finding_ids_by_set": {},
            "review_record_schema_version": 2,
            "review_contract_version": 2,
        }
    )
    payload.update(overrides)
    return payload


def test_review_loop_from_dict_rejects_non_object_finding() -> None:
    payload = _base_review_loop_payload(
        findings=["CORRUPT"],
        finding_actions=["CORRUPT"],
    )

    with pytest.raises(ValueError, match="findings"):
        ReviewLoop.from_dict(payload)


def test_review_loop_from_dict_rejects_unknown_finding_status() -> None:
    payload = _base_review_loop_payload(
        findings=[
            {
                "id": "f-1",
                "severity": "blocker",
                "category": "correctness",
                "target_refs": ["item-a"],
                "issue": "Broken",
                "recommended_change": "Fix it",
                "status": "banana",
            }
        ],
    )

    with pytest.raises(ValueError, match="finding status"):
        ReviewLoop.from_dict(payload)


def test_unknown_finding_status_never_permits_approval() -> None:
    finding = ReviewFinding(
        id="f-1",
        severity="blocker",
        category="correctness",
        target_refs=["item-a"],
        issue="Broken",
        recommended_change="Fix it",
        status="banana",  # type: ignore[arg-type]
    )

    assert is_open_finding_status("banana") is False
    assert is_unresolved_finding_status("banana") is True
    assert findings_permit_approval([finding], [], "major") is False


def test_review_loop_from_dict_rejects_unknown_loop_status() -> None:
    payload = _base_review_loop_payload(status="banana")

    with pytest.raises(ValueError, match="review loop status"):
        ReviewLoop.from_dict(payload)


def test_review_loop_from_dict_rejects_unknown_lifecycle_status() -> None:
    payload = _base_review_loop_payload(lifecycle_status="banana")

    with pytest.raises(ValueError, match="lifecycle status"):
        ReviewLoop.from_dict(payload)


def test_review_loop_from_dict_rejects_unknown_loop_type() -> None:
    payload = _base_review_loop_payload(type="banana")

    with pytest.raises(ValueError, match="review loop type"):
        ReviewLoop.from_dict(payload)


def test_review_loop_from_dict_rejects_negative_revision() -> None:
    payload = _base_review_loop_payload(revision=-1)

    with pytest.raises(ValueError, match="revision"):
        ReviewLoop.from_dict(payload)


def test_review_loop_from_dict_rejects_malformed_finding_ids_by_set() -> None:
    payload = _base_review_loop_payload(
        finding_ids_by_set={"set-1": "not-a-list"},
    )

    with pytest.raises(ValueError, match="finding_ids_by_set"):
        ReviewLoop.from_dict(payload)


def test_required_blocker_finding_survives_round_trip() -> None:
    loop = make_review_loop(
        id="review-whole-plan-01",
        type="whole_plan",
        reviewer_session_id="sess",
        target_revision=0,
        scope={"kind": "whole_plan"},
        findings=[
            ReviewFinding(
                id="f-block",
                severity="blocker",
                category="correctness",
                target_refs=["item-a"],
                issue="Broken",
                recommended_change="Fix it",
                status="unresolved",
            )
        ],
    )
    round_trip = ReviewLoop.from_dict(loop.to_dict())

    assert len(round_trip.findings) == 1
    assert round_trip.findings[0].id == "f-block"
    assert round_trip.findings[0].status == "unresolved"


# --- TDP-S2-003: plan deserialization ---


@pytest.mark.parametrize(
    ("revision", "match"),
    [
        (True, "revision"),
        ("1", "revision"),
        (-1, "revision"),
    ],
)
def test_plan_from_dict_rejects_invalid_revision(revision: object, match: str) -> None:
    payload = _minimal_plan_dict(revision=revision)

    with pytest.raises(ValueError, match=match):
        Plan.from_dict(payload)


def test_plan_from_dict_rejects_non_string_plan_id() -> None:
    payload = _minimal_plan_dict(id=123)

    with pytest.raises(ValueError, match="plan id"):
        Plan.from_dict(payload)


def test_plan_from_dict_rejects_non_string_output_goal() -> None:
    payload = _minimal_plan_dict(output_goal=123)

    with pytest.raises(ValueError, match="output_goal"):
        Plan.from_dict(payload)


def test_plan_from_dict_rejects_unknown_planning_status() -> None:
    payload = _minimal_plan_dict()
    payload["items"][0]["planning_status"] = "banana"

    with pytest.raises(ValueError, match="planning_status"):
        Plan.from_dict(payload)


def test_plan_from_dict_rejects_non_string_item_title() -> None:
    payload = _minimal_plan_dict()
    payload["items"][0]["title"] = 123

    with pytest.raises(ValueError, match="title"):
        Plan.from_dict(payload)


def test_plan_from_dict_rejects_invalid_items_container() -> None:
    payload = _minimal_plan_dict(items={"item-root": {}})

    with pytest.raises(ValueError, match="items"):
        Plan.from_dict(payload)


def test_validator_returns_issues_for_malformed_in_memory_title() -> None:
    root = seed_plan_root_item()
    root.title = 123  # type: ignore[assignment]
    plan = Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={PLAN_ROOT_ITEM_ID: root},
    )

    result = validate_plan(plan, mode="draft")

    assert result.ok is False
    assert any(
        issue.code == "missing_required_field" and issue.path == ["item-root", "title"]
        for issue in result.issues
    )


def test_validator_reports_unknown_planning_status_instead_of_skipping() -> None:
    root = seed_plan_root_item()
    root.planning_status = "banana"  # type: ignore[assignment]
    plan = Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={PLAN_ROOT_ITEM_ID: root},
    )

    result = validate_plan(plan, mode="draft")

    assert result.ok is False
    assert any(issue.code == "invalid_planning_status" for issue in result.issues)


# --- TDP-S2-004: domain import purity ---


def test_domain_modules_import_in_fresh_interpreter() -> None:
    domain_dir = _PACKAGE_ROOT / "top_down_planning" / "domain"
    modules = sorted(
        f"top_down_planning.domain.{path.stem}"
        for path in domain_dir.rglob("*.py")
        if path.name != "__init__.py"
    )
    failures: list[str] = []
    for module_name in modules:
        completed = subprocess.run(
            [sys.executable, "-c", f"import {module_name}"],
            capture_output=True,
            text=True,
            cwd=_PACKAGE_ROOT.parent,
            env={**os.environ, "PYTHONPATH": str(_PACKAGE_ROOT)},
            check=False,
        )
        if completed.returncode != 0:
            failures.append(f"{module_name}: {completed.stderr.strip()}")
    assert not failures, "fresh import failures:\n" + "\n".join(failures)


# --- TDP-S2-005: sibling order keys ---


def test_duplicate_active_sibling_order_keys_fail_validation() -> None:
    root = seed_plan_root_item()
    first = PlanItem(
        id="item-a",
        parent_id=PLAN_ROOT_ITEM_ID,
        order_key="0000000000",
        title="A",
        kind="work",
    )
    second = PlanItem(
        id="item-b",
        parent_id=PLAN_ROOT_ITEM_ID,
        order_key="0000000000",
        title="B",
        kind="work",
    )
    plan = Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={PLAN_ROOT_ITEM_ID: root, "item-a": first, "item-b": second},
    )

    result = validate_plan(plan, mode="approval")

    assert result.ok is False
    assert any(issue.code == "duplicate_sibling_order_key" for issue in result.issues)


def test_equivalent_payloads_produce_identical_digest_regardless_of_item_order() -> None:
    root = seed_plan_root_item()
    first = PlanItem(
        id="item-a",
        parent_id=PLAN_ROOT_ITEM_ID,
        order_key="0000000000",
        title="A",
        kind="work",
    )
    second = PlanItem(
        id="item-b",
        parent_id=PLAN_ROOT_ITEM_ID,
        order_key="0000000100",
        title="B",
        kind="work",
    )
    plan_ab = Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={PLAN_ROOT_ITEM_ID: root, "item-a": first, "item-b": second},
    )
    plan_ba = Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={PLAN_ROOT_ITEM_ID: root, "item-b": second, "item-a": first},
    )

    assert compute_plan_digest(plan_ab) == compute_plan_digest(plan_ba)
    assert display_traversal(plan_ab) == display_traversal(plan_ba)


# --- TDP-S2-006: strict review evidence parsing ---


def _minimal_sweep_payload(**overrides: object) -> dict:
    payload = {
        "id": "sweep-1",
        "family_id": "family-1",
        "actor_role": "planner",
        "stage": "owner_fix",
        "artifact_revision": 1,
        "artifact_digest": "digest-1",
        "finding_set_id": "set-1",
        "searched_refs": [],
        "search_dimensions": [],
        "additional_fixed_refs": [],
        "remaining_instance_refs": [],
        "completed": True,
        "summary": "done",
        "evidence": [],
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("completed", "false", "completed"),
        ("completed", 1, "completed"),
        ("artifact_revision", "-1", "artifact_revision"),
        ("artifact_revision", True, "artifact_revision"),
        ("searched_refs", "abc", "searched_refs"),
        ("search_dimensions", [1, "x"], "search_dimensions"),
        ("evidence", [123], "evidence"),
    ],
)
def test_family_sweep_record_rejects_coerced_fields(
    field: str,
    value: object,
    match: str,
) -> None:
    payload = _minimal_sweep_payload(**{field: value})

    with pytest.raises(ValueError, match=match):
        FamilySweepRecord.from_dict(payload)


def test_family_sweep_record_rejects_malformed_remaining_instance_refs() -> None:
    payload = _minimal_sweep_payload(remaining_instance_refs=["CORRUPT"])

    with pytest.raises(ValueError, match="artifact refs"):
        FamilySweepRecord.from_dict(payload)


def test_audit_attestation_pass_rejects_string_completed() -> None:
    with pytest.raises(ValueError, match="completed"):
        AuditAttestationPass.from_dict(
            {"pass_id": "pass-1", "completed": "false"},
        )


def test_audit_attestation_run_rejects_non_list_passes() -> None:
    with pytest.raises(ValueError, match="passes must be a list"):
        AuditAttestationRun.from_dict(
            {
                "id": "audit-1",
                "finding_set_id": "set-1",
                "artifact_revision": 1,
                "artifact_digest": "digest-1",
                "passes": {},
                "recorded_at": "2026-01-01T00:00:00Z",
            }
        )


def test_review_finding_rejects_malformed_instance_ref() -> None:
    with pytest.raises(ValueError, match="instance_ref"):
        ReviewFinding.from_dict(
            {
                "id": "f-1",
                "severity": "blocker",
                "category": "correctness",
                "target_refs": ["item-a"],
                "issue": "Broken",
                "recommended_change": "Fix it",
                "instance_ref": "CORRUPT",
            }
        )


def test_parse_finding_action_rejects_coerced_artifact_revision() -> None:
    base = {
        "finding_id": "f-1",
        "action": "fix",
        "actor_role": "planner",
        "finding_set_id": "set-1",
    }
    for revision in ("1", True, -1):
        with pytest.raises(ValueError, match="artifact_revision"):
            parse_finding_action({**base, "artifact_revision": revision})


def test_review_loop_from_dict_rejects_falsey_wrong_containers() -> None:
    base = _base_review_loop_payload()
    for field in ("findings", "finding_actions"):
        payload = dict(base)
        payload[field] = {}
        with pytest.raises(ValueError, match=field):
            ReviewLoop.from_dict(payload)


def test_malformed_owner_sweep_payload_rejected_on_load() -> None:
    with pytest.raises(ValueError):
        FamilySweepRecord.from_dict(
            _minimal_sweep_payload(
                completed="false",
                remaining_instance_refs=["CORRUPT"],
            )
        )


def test_malformed_audit_pass_rejected_on_load() -> None:
    with pytest.raises(ValueError, match="completed"):
        AuditAttestationRun.from_dict(
            {
                "id": "audit-1",
                "finding_set_id": "set-1",
                "artifact_revision": 1,
                "artifact_digest": "digest-1",
                "passes": [{"pass_id": "pass-1", "completed": "false"}],
                "recorded_at": "2026-01-01T00:00:00Z",
            }
        )


# --- TDP-S2-007: mutation and validator contract unification ---


def test_apply_operations_rejects_non_string_item_outcome() -> None:
    plan = _plan_with_root_child()

    with pytest.raises(InvalidMutationError, match="outcome"):
        apply_operations(
            plan,
            base_revision=1,
            operations=[
                {
                    "op": "update_item",
                    "item_id": "item-child",
                    "patch": {"outcome": 123},
                }
            ],
            reviews=[],
        )


def test_apply_operations_rejects_non_string_list_members() -> None:
    plan = _plan_with_root_child()

    with pytest.raises(InvalidMutationError, match="boundaries"):
        apply_operations(
            plan,
            base_revision=1,
            operations=[
                {
                    "op": "update_item",
                    "item_id": "item-child",
                    "patch": {"boundaries": [456]},
                }
            ],
            reviews=[],
        )


def test_apply_operations_rejects_non_string_plan_metadata_members() -> None:
    plan = _plan_with_root_child()

    with pytest.raises(InvalidMutationError, match="constraints"):
        apply_operations(
            plan,
            base_revision=1,
            operations=[
                {
                    "op": "update_plan",
                    "patch": {"constraints": [123]},
                }
            ],
            reviews=[],
        )


def test_successful_mutation_result_round_trips_through_plan_from_dict() -> None:
    plan = _plan_with_root_child()

    result = apply_operations(
        plan,
        base_revision=1,
        operations=[
            {
                "op": "update_item",
                "item_id": "item-child",
                "patch": {
                    "title": "Updated child",
                    "outcome": "Done",
                    "boundaries": ["scope boundary"],
                },
            },
            {
                "op": "update_plan",
                "patch": {"constraints": ["no regressions"]},
            },
        ],
        reviews=[],
    )

    round_trip = Plan.from_dict(result.plan.to_dict())

    assert round_trip.revision == result.revision
    assert round_trip.items["item-child"].title == "Updated child"
    assert round_trip.constraints == ["no regressions"]


@pytest.mark.parametrize("revision", [-1, True, "1"])
def test_validator_rejects_invalid_in_memory_plan_revision(revision: object) -> None:
    root = seed_plan_root_item()
    plan = Plan(
        id="plan-001",
        revision=revision,  # type: ignore[arg-type]
        output_goal="Deliver the output.",
        items={PLAN_ROOT_ITEM_ID: root},
    )

    result = validate_plan(plan, mode="draft")

    assert result.ok is False
    assert any(issue.path == ["plan", "revision"] for issue in result.issues)


def test_validator_returns_issues_for_malformed_depends_on_without_raising() -> None:
    root = seed_plan_root_item()
    child = PlanItem(
        id="item-child",
        parent_id=PLAN_ROOT_ITEM_ID,
        order_key="0000000000",
        title="Child",
        kind="work",
        depends_on=123,  # type: ignore[arg-type]
    )
    plan = Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={PLAN_ROOT_ITEM_ID: root, "item-child": child},
    )

    result = validate_plan(plan, mode="draft")

    assert result.ok is False
    assert any(
        issue.path == ["item-child", "depends_on"] for issue in result.issues
    )


def test_validator_returns_issues_for_malformed_plan_metadata_without_raising() -> None:
    root = seed_plan_root_item()
    plan = Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={PLAN_ROOT_ITEM_ID: root},
        constraints=[123],  # type: ignore[list-item]
    )

    result = validate_plan(plan, mode="draft")

    assert result.ok is False
    assert any(
        issue.path == ["plan", "constraints", "0"] for issue in result.issues
    )


# --- TDP-S2-009 / TDP-S2-010 / TDP-S2-011: second remediation ---


def test_review_loop_from_dict_rejects_wrong_type_scope_review_result() -> None:
    payload = _base_review_loop_payload(scope_review_result="CORRUPT")

    with pytest.raises(ValueError, match="scope_review_result"):
        ReviewLoop.from_dict(payload)


def test_review_loop_from_dict_rejects_wrong_type_verification_result() -> None:
    payload = _base_review_loop_payload(verification_result="CORRUPT")

    with pytest.raises(ValueError, match="verification_result"):
        ReviewLoop.from_dict(payload)


def test_review_loop_from_dict_rejects_wrong_type_review_incomplete() -> None:
    payload = _base_review_loop_payload(review_incomplete="CORRUPT")

    with pytest.raises(ValueError, match="review_incomplete"):
        ReviewLoop.from_dict(payload)


def test_review_loop_from_dict_rejects_wrong_type_reviewer_binding() -> None:
    payload = _base_review_loop_payload(reviewer_binding="CORRUPT")

    with pytest.raises(ValueError, match="reviewer_binding"):
        ReviewLoop.from_dict(payload)


def test_approved_mandatory_loop_without_scope_review_result_fails_load() -> None:
    payload = _base_review_loop_payload(
        status="approved",
        lifecycle_status="approved",
        active_stage="scope_review",
        scope_review_result=None,
    )

    with pytest.raises(ValueError, match="scope_review_result"):
        ReviewLoop.from_dict(payload)


def test_parse_finding_action_rejects_numeric_rationale() -> None:
    with pytest.raises(ValueError, match="rationale"):
        parse_finding_action(
            {
                "finding_id": "finding-minor",
                "action": "accept_as_is",
                "actor_role": "planner",
                "artifact_revision": 1,
                "finding_set_id": "set-1",
                "rationale": 123,
            }
        )


def test_malformed_action_cannot_satisfy_findings_permit_approval() -> None:
    finding = ReviewFinding(
        id="finding-minor",
        severity="minor",
        category="other",
        target_refs=["item-a"],
        issue="Optional",
        recommended_change="Polish",
        status="unresolved",
    )

    with pytest.raises(ValueError, match="rationale"):
        parse_finding_action(
            {
                "finding_id": "finding-minor",
                "action": "accept_as_is",
                "actor_role": "planner",
                "artifact_revision": 1,
                "finding_set_id": "set-1",
                "rationale": 123,
            }
        )

    assert findings_permit_approval([finding], [], "major") is False


def test_family_sweep_record_rejects_empty_id() -> None:
    with pytest.raises(ValueError, match="id"):
        FamilySweepRecord.from_dict(_minimal_sweep_payload(id=""))


def test_validator_returns_issue_for_unhashable_item_id_without_raising() -> None:
    root = seed_plan_root_item()
    child = PlanItem(
        id=["bad"],  # type: ignore[arg-type]
        parent_id=PLAN_ROOT_ITEM_ID,
        order_key="0000000000",
        title="Child",
        kind="work",
    )
    plan = Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={"item-child": child},
    )

    result = validate_plan(plan, mode="draft")

    assert result.ok is False
    assert any(issue.path == ["item-child", "id"] for issue in result.issues)


def test_validator_returns_issue_for_unhashable_planning_status_without_raising() -> None:
    root = seed_plan_root_item()
    root.planning_status = ["open"]  # type: ignore[assignment]
    plan = Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={PLAN_ROOT_ITEM_ID: root},
    )

    result = validate_plan(plan, mode="draft")

    assert result.ok is False
    assert any(
        issue.path == [PLAN_ROOT_ITEM_ID, "planning_status"] for issue in result.issues
    )


def test_validator_returns_issue_for_none_item_scope_without_raising() -> None:
    root = seed_plan_root_item()
    child = PlanItem(
        id="item-child",
        parent_id=PLAN_ROOT_ITEM_ID,
        order_key="0000000000",
        title="Child",
        kind="work",
        scope=None,  # type: ignore[arg-type]
    )
    plan = Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={PLAN_ROOT_ITEM_ID: root, "item-child": child},
    )

    result = validate_plan(plan, mode="draft")

    assert result.ok is False
    assert any(
        issue.path == ["item-child", "scope"] for issue in result.issues
    )


def test_validator_returns_issue_for_none_plan_scope_without_raising() -> None:
    root = seed_plan_root_item()
    plan = Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={PLAN_ROOT_ITEM_ID: root},
        scope=None,  # type: ignore[arg-type]
    )

    result = validate_plan(plan, mode="draft")

    assert result.ok is False
    assert any(issue.path == ["plan", "scope"] for issue in result.issues)


def test_validator_returns_issues_for_unhashable_depends_on_member_without_raising() -> None:
    root = seed_plan_root_item()
    child = PlanItem(
        id="item-child",
        parent_id=PLAN_ROOT_ITEM_ID,
        order_key="0000000000",
        title="Child",
        kind="work",
        depends_on=[{}],  # type: ignore[list-item]
    )
    plan = Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={PLAN_ROOT_ITEM_ID: root, "item-child": child},
    )

    result = validate_plan(plan, mode="draft")

    assert result.ok is False
    assert any(
        issue.path == ["item-child", "depends_on", "0"] for issue in result.issues
    )


def test_parse_review_version_fields_raises_guided_error_for_v1() -> None:
    with pytest.raises(UnsupportedReviewSchemaVersionError, match="recreate the run"):
        parse_review_version_fields(
            {"review_record_schema_version": 1, "review_contract_version": 1}
        )


def test_persisted_v1_review_record_raises_guided_error_on_load(tmp_path: Path) -> None:
    from core_tools.persistence import atomic_write_json
    from top_down_planning.persistence import FileRunStore
    from tests.helpers import create_run_kwargs

    run_id = "run-20260101T000001-000001"
    store = FileRunStore(tmp_path)
    plan = _plan_with_root_child()
    store.create_run(
        run_id,
        plan=plan,
        **create_run_kwargs(tmp_path, resolved_config={"run": {"output_goal": plan.output_goal}}),
    )
    review_path = store.reviews_dir(run_id) / "review-whole-plan-01.json"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        review_path,
        {
            "id": "review-whole-plan-01",
            "type": "whole_plan",
            "target_revision": 0,
            "scope": {"kind": "whole_plan"},
            "status": "approved",
            "lifecycle_status": "approved",
            "revise_at": "blocker",
            "findings": [],
            "finding_actions": [],
            "revision_cycles": 0,
            "revision": 0,
            "review_record_schema_version": 1,
            "review_contract_version": 1,
        },
    )

    with pytest.raises(UnsupportedReviewSchemaVersionError) as exc_info:
        ReviewLoop.from_dict(store.load_review(run_id, "review-whole-plan-01"))

    assert UNSUPPORTED_REVIEW_SCHEMA_MESSAGE in str(exc_info.value)


def _plan_with_child_parent_id(parent_id: object, **child_overrides: object) -> Plan:
    root = seed_plan_root_item()
    child = PlanItem(
        id="item-child",
        parent_id=parent_id,  # type: ignore[arg-type]
        order_key="0000000000",
        title="Child",
        kind="work",
        **child_overrides,
    )
    return Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={PLAN_ROOT_ITEM_ID: root, "item-child": child},
    )


@pytest.mark.parametrize(
    "parent_id",
    [
        [],
        {},
        1,
    ],
)
def test_validate_plan_returns_parent_id_issue_for_malformed_parent_without_raising(
    parent_id: object,
) -> None:
    plan = _plan_with_child_parent_id(parent_id)

    result = validate_plan(plan, mode="draft")

    assert result.ok is False
    assert any(
        issue.path == ["item-child", "parent_id"] for issue in result.issues
    )


def test_validate_plan_with_mixed_malformed_and_valid_parents_does_not_raise() -> None:
    root = seed_plan_root_item()
    malformed = PlanItem(
        id="item-bad",
        parent_id=[],  # type: ignore[arg-type]
        order_key="0000000001",
        title="Bad",
        kind="work",
    )
    valid = PlanItem(
        id="item-good",
        parent_id=PLAN_ROOT_ITEM_ID,
        order_key="0000000002",
        title="Good",
        kind="work",
    )
    plan = Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={
            PLAN_ROOT_ITEM_ID: root,
            "item-bad": malformed,
            "item-good": valid,
        },
    )

    result = validate_plan(plan, mode="draft")

    assert result.ok is False
    assert any(issue.path == ["item-bad", "parent_id"] for issue in result.issues)


def test_validate_plan_with_malformed_parent_and_siblings_does_not_raise() -> None:
    root = seed_plan_root_item()
    siblings = [
        PlanItem(
            id=f"item-sib-{index}",
            parent_id=[],  # type: ignore[arg-type]
            order_key=f"000000000{index}",
            title=f"Sibling {index}",
            kind="work",
        )
        for index in range(3)
    ]
    plan = Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={PLAN_ROOT_ITEM_ID: root, **{item.id: item for item in siblings}},
    )

    result = validate_plan(plan, mode="approval", limits=PlanningLimits(max_depth=3))

    assert result.ok is False
    for item in siblings:
        assert any(issue.path == [item.id, "parent_id"] for issue in result.issues)


def test_validate_plan_malformed_parent_with_soft_limits_does_not_raise() -> None:
    plan = _plan_with_child_parent_id([])

    result = validate_plan(plan, mode="draft", limits=PlanningLimits(max_depth=2))

    assert result.ok is False
    assert any(
        issue.path == ["item-child", "parent_id"] for issue in result.issues
    )


def test_validate_plan_malformed_order_key_does_not_raise_traversal() -> None:
    root = seed_plan_root_item()
    child = PlanItem(
        id="item-child",
        parent_id=PLAN_ROOT_ITEM_ID,
        order_key=[],  # type: ignore[arg-type]
        title="Child",
        kind="work",
    )
    plan = Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={PLAN_ROOT_ITEM_ID: root, "item-child": child},
    )

    result = validate_plan(plan, mode="draft")

    assert result.ok is False
    assert any(
        issue.path == ["item-child", "order_key"] for issue in result.issues
    )


def test_validate_plan_rejects_non_dict_items_container_without_raising() -> None:
    root = seed_plan_root_item()
    plan = Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={PLAN_ROOT_ITEM_ID: root},
    )
    plan.items = []  # type: ignore[assignment]

    result = validate_plan(plan, mode="draft")

    assert result.ok is False
    assert any(issue.path == ["plan", "items"] for issue in result.issues)


def _assert_validate_plan_fails_without_raising(
    plan: Plan,
    *,
    mode: str = "draft",
) -> None:
    result = validate_plan(plan, mode=mode)  # type: ignore[arg-type]
    assert result.ok is False


def _reachable_child_with_embedded_id(item_id: object) -> Plan:
    root = seed_plan_root_item()
    child = PlanItem(
        id=item_id,  # type: ignore[arg-type]
        parent_id=PLAN_ROOT_ITEM_ID,
        order_key="0000000000",
        title="Child",
        kind="work",
    )
    return Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={PLAN_ROOT_ITEM_ID: root, "item-child": child},
    )


@pytest.mark.parametrize("embedded_id", [[], {}])
@pytest.mark.parametrize("mode", ["draft", "approval"])
def test_validate_plan_reachable_child_with_unhashable_embedded_id_does_not_raise(
    embedded_id: object,
    mode: str,
) -> None:
    _assert_validate_plan_fails_without_raising(
        _reachable_child_with_embedded_id(embedded_id),
        mode=mode,
    )


@pytest.mark.parametrize("mode", ["draft", "approval"])
def test_validate_plan_rejects_dict_item_value_without_raising(mode: str) -> None:
    plan = Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={
            PLAN_ROOT_ITEM_ID: seed_plan_root_item(),
            "item-child": {},  # type: ignore[dict-item]
        },
    )

    _assert_validate_plan_fails_without_raising(plan, mode=mode)
    result = validate_plan(plan, mode=mode)  # type: ignore[arg-type]
    assert any(issue.path == ["plan", "items", "item-child"] for issue in result.issues)


@pytest.mark.parametrize("mode", ["draft", "approval"])
def test_validate_plan_rejects_none_item_value_without_raising(mode: str) -> None:
    plan = Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={
            PLAN_ROOT_ITEM_ID: seed_plan_root_item(),
            "item-child": None,  # type: ignore[dict-item]
        },
    )

    _assert_validate_plan_fails_without_raising(plan, mode=mode)
    result = validate_plan(plan, mode=mode)  # type: ignore[arg-type]
    assert any(issue.path == ["plan", "items", "item-child"] for issue in result.issues)


@pytest.mark.parametrize("mode", ["draft", "approval"])
def test_validate_plan_rejects_mixed_string_and_integer_item_keys_without_raising(
    mode: str,
) -> None:
    valid_child = PlanItem(
        id="item-child",
        parent_id=PLAN_ROOT_ITEM_ID,
        order_key="0000000000",
        title="Child",
        kind="work",
    )
    plan = Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={
            PLAN_ROOT_ITEM_ID: seed_plan_root_item(),
            1: valid_child,  # type: ignore[dict-item]
        },
    )

    _assert_validate_plan_fails_without_raising(plan, mode=mode)
    result = validate_plan(plan, mode=mode)  # type: ignore[arg-type]
    assert any(issue.path == ["plan", "items", "1"] for issue in result.issues)


@pytest.mark.parametrize("mode", ["draft", "approval"])
def test_validate_plan_rejects_integer_only_item_key_without_raising(mode: str) -> None:
    valid_child = PlanItem(
        id="item-child",
        parent_id=PLAN_ROOT_ITEM_ID,
        order_key="0000000000",
        title="Child",
        kind="work",
    )
    plan = Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={1: valid_child},  # type: ignore[dict-item]
    )

    _assert_validate_plan_fails_without_raising(plan, mode=mode)


@pytest.mark.parametrize("mode", ["draft", "approval"])
def test_validate_plan_rejects_invalid_root_item_value_without_raising(mode: str) -> None:
    plan = Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={PLAN_ROOT_ITEM_ID: {}},  # type: ignore[dict-item]
    )

    _assert_validate_plan_fails_without_raising(plan, mode=mode)
    result = validate_plan(plan, mode=mode)  # type: ignore[arg-type]
    assert any(
        issue.path == ["plan", "items", PLAN_ROOT_ITEM_ID] for issue in result.issues
    )


def test_validate_plan_with_mixed_valid_and_malformed_item_values_does_not_raise() -> None:
    valid = PlanItem(
        id="item-good",
        parent_id=PLAN_ROOT_ITEM_ID,
        order_key="0000000001",
        title="Good",
        kind="work",
    )
    plan = Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={
            PLAN_ROOT_ITEM_ID: seed_plan_root_item(),
            "item-good": valid,
            "item-bad": None,  # type: ignore[dict-item]
        },
    )

    result = validate_plan(plan, mode="draft")

    assert result.ok is False
    assert any(issue.path == ["plan", "items", "item-bad"] for issue in result.issues)


MALFORMED_LIST_FIELD_VALUES: list[object] = [
    1,
    {},
    "not-a-list",
    [1],
    [{}],
    [None],
]


def _plan_with_child_field(field: str, value: object) -> Plan:
    root = seed_plan_root_item()
    child = PlanItem(
        id="item-child",
        parent_id=PLAN_ROOT_ITEM_ID,
        order_key="0000000000",
        title="Child",
        kind="work",
    )
    if field == "scope.includes":
        child.scope.includes = value  # type: ignore[assignment]
    elif field == "scope.excludes":
        child.scope.excludes = value  # type: ignore[assignment]
    else:
        setattr(child, field, value)
    return Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={PLAN_ROOT_ITEM_ID: root, "item-child": child},
    )


def _expected_field_issue_path(field: str) -> list[str]:
    if field.startswith("scope."):
        return ["item-child", "scope", field.split(".", 1)[1]]
    return ["item-child", field]


@pytest.mark.parametrize("field", [
    "scope.includes",
    "scope.excludes",
    "boundaries",
    "acceptance",
    "depends_on",
    "risks",
    "source_refs",
])
@pytest.mark.parametrize("value", MALFORMED_LIST_FIELD_VALUES)
def test_validate_plan_returns_issue_for_malformed_list_field_without_raising(
    field: str,
    value: object,
) -> None:
    plan = _plan_with_child_field(field, value)

    result = validate_plan(plan, mode="draft")

    assert result.ok is False
    expected_path = _expected_field_issue_path(field)
    if isinstance(value, list) and value and not isinstance(value[0], str):
        expected_path = [*expected_path, "0"]
    assert any(issue.path == expected_path for issue in result.issues)


@pytest.mark.parametrize("mode", ["draft", "approval"])
def test_validate_plan_malformed_acceptance_with_limits_does_not_raise(mode: str) -> None:
    plan = _plan_with_child_field("acceptance", 1)

    result = validate_plan(plan, mode=mode, limits=PlanningLimits(max_depth=3))  # type: ignore[arg-type]

    assert result.ok is False


def test_validate_plan_duplicate_looking_siblings_with_malformed_ids_does_not_raise() -> None:
    root = seed_plan_root_item()
    siblings = [
        PlanItem(
            id=[],  # type: ignore[arg-type]
            parent_id=PLAN_ROOT_ITEM_ID,
            order_key="0000000001",
            title="Same",
            kind="work",
            outcome="Same outcome",
            acceptance=["same"],
        ),
        PlanItem(
            id={},  # type: ignore[arg-type]
            parent_id=PLAN_ROOT_ITEM_ID,
            order_key="0000000002",
            title="Same",
            kind="work",
            outcome="Same outcome",
            acceptance=["same"],
        ),
    ]
    plan = Plan(
        id="plan-001",
        revision=1,
        output_goal="Deliver the output.",
        items={
            PLAN_ROOT_ITEM_ID: root,
            "item-sib-a": siblings[0],
            "item-sib-b": siblings[1],
        },
    )

    result = validate_plan(plan, mode="draft")

    assert result.ok is False
