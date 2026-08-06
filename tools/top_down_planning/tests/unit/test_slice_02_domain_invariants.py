"""Regression tests for Slice 2 domain invariants (TDP-S2-001 through TDP-S2-005)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from top_down_planning.agent_tool import PlanAgentService
from top_down_planning.domain.models import Plan, PlanItem, Scope
from top_down_planning.domain.mutations import apply_operations
from top_down_planning.domain.errors import InvalidMutationError
from top_down_planning.domain.plan_tree import PLAN_ROOT_ITEM_ID, display_traversal, seed_plan_root_item
from top_down_planning.domain.reviews import (
    ReviewFinding,
    ReviewLoop,
    findings_permit_approval,
    is_open_finding_status,
    is_unresolved_finding_status,
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
