"""Unit tests for deterministic plan validation."""

from __future__ import annotations

import pytest

from top_down_planning.domain.models import Plan, PlanItem, PlanningLimits, Scope
from top_down_planning.domain.validators import validate_plan


def _chain_plan(depth: int) -> Plan:
    """Build an active chain of depth `depth` (root at depth 0)."""

    items: dict[str, PlanItem] = {}
    parent_id: str | None = None
    for level in range(depth + 1):
        item_id = f"item-{level}"
        items[item_id] = PlanItem(
            id=item_id,
            parent_id=parent_id,
            order_key="0000000000",
            title=f"Level {level}",
            kind="work",
        )
        parent_id = item_id

    return Plan(
        id="plan-depth",
        revision=1,
        output_goal="Depth validation plan.",
        items=items,
    )


def test_approval_mode_fails_on_depth_overflow_draft_mode_warns() -> None:
    limits = PlanningLimits(max_depth=2)
    plan = _chain_plan(depth=3)

    draft = validate_plan(plan, limits=limits, mode="draft")
    assert draft.ok
    depth_issues = [issue for issue in draft.issues if issue.code == "exceeded_depth_limit"]
    assert len(depth_issues) == 1
    assert depth_issues[0].severity == "warning"
    assert depth_issues[0].path == ["item-3"]

    approval = validate_plan(plan, limits=limits, mode="approval")
    assert not approval.ok
    approval_depth = [issue for issue in approval.issues if issue.code == "exceeded_depth_limit"]
    assert len(approval_depth) == 1
    assert approval_depth[0].severity == "error"


def test_hierarchy_cycle_and_dependency_cycle_have_distinct_codes_and_paths() -> None:
    root = PlanItem("item-root", None, "0000000000", "Root", kind="aggregate")
    first = PlanItem("item-first", "item-root", "0000000000", "First", kind="work")
    second = PlanItem("item-second", "item-root", "0000000100", "Second", kind="work")
    plan = Plan(
        id="plan-cycles",
        revision=1,
        output_goal="Cycle validation plan.",
        items={
            "item-root": root,
            "item-first": first,
            "item-second": second,
        },
    )

    plan.items["item-first"] = PlanItem(
        "item-first",
        "item-second",
        "0000000000",
        "First",
        depends_on=["item-second"],
        kind="work",
    )
    plan.items["item-second"] = PlanItem(
        "item-second",
        "item-first",
        "0000000100",
        "Second",
        depends_on=["item-first"],
        kind="work",
    )

    result = validate_plan(plan)
    codes = {issue.code for issue in result.issues}
    assert "hierarchy_cycle" in codes
    assert "dependency_cycle" in codes

    hierarchy = next(issue for issue in result.issues if issue.code == "hierarchy_cycle")
    dependency = next(issue for issue in result.issues if issue.code == "dependency_cycle")
    assert hierarchy.path == ["item-first", "item-second", "item-first"]
    assert dependency.path == ["item-first", "item-second", "item-first"]
    assert not result.ok


def test_approval_mode_detects_input_digest_tampering() -> None:
    from top_down_planning.domain.validators import (
        DigestBundle,
        build_plan_approval_validation_context,
        validate_digest_hooks,
    )

    root = PlanItem("item-root", None, "0000000000", "Root", kind="aggregate")
    plan = Plan(
        id="plan-digest",
        revision=1,
        output_goal="Goal.",
        items={"item-root": root},
    )
    run = {
        "digests": {
            "plan": "plan-digest",
            "input": "input-digest",
            "output_goal": "goal-digest",
            "config_contract": "config-digest",
        }
    }
    approval = {
        "target_revision": 1,
        "revise_at": "blocker",
        "approved_digests": dict(run["digests"]),
        "findings": [],
    }
    _, digest_bundle = build_plan_approval_validation_context(
        plan=plan,
        approval=approval,
        actual_plan_digest="plan-digest",
        actual_config_contract_digest="config-digest",
        actual_input_digest="tampered-input-digest",
        actual_output_goal_digest="goal-digest",
    )
    issues = validate_digest_hooks(plan, digest_bundle, mode="approval")
    assert any(issue.code == "digest_mismatch" and issue.path == ["input"] for issue in issues)


def test_legacy_config_approved_digest_rejected() -> None:
    from top_down_planning.domain.models import Plan, PlanItem
    from top_down_planning.domain.validators import build_plan_approval_validation_context

    root = PlanItem("item-root", None, "0000000000", "Root", kind="aggregate")
    plan = Plan(
        id="plan-legacy",
        revision=0,
        output_goal="Goal.",
        items={"item-root": root},
    )
    approval = {
        "target_revision": 0,
        "approved_digests": {
            "plan": "plan-digest",
            "config": "legacy-config-digest",
        },
        "findings": [],
    }
    with pytest.raises(ValueError, match="legacy approved digest key 'config'"):
        build_plan_approval_validation_context(
            plan=plan,
            approval=approval,
            actual_plan_digest="plan-digest",
            actual_config_contract_digest="contract-digest",
            actual_input_digest="input-digest",
            actual_output_goal_digest="goal-digest",
        )


def test_review_loop_round_trips_approved_digests() -> None:
    from top_down_planning.domain.reviews import ReviewLoop
    from tests.helpers import review_loop_dict_with_binding

    payload = review_loop_dict_with_binding(
        {
        "id": "review-whole-plan-01",
        "type": "whole_plan",
        "revise_at": "blocker",
        "reviewer_session_id": "session-1",
        "target_revision": 2,
        "scope": {"kind": "whole_plan"},
        "status": "approved",
        "findings": [],
        "revision_cycles": 1,
        "approved_digests": {
            "plan": "plan-digest",
            "config_contract": "config-digest",
            "input": "input-digest",
        },
        }
    )
    loop = ReviewLoop.from_dict(payload)
    assert loop.to_dict()["approved_digests"] == payload["approved_digests"]


def test_orphan_parent_and_duplicate_item_id_are_reported() -> None:
    root = PlanItem("item-root", None, "0000000000", "Root", kind="aggregate")
    orphan = PlanItem(
        "item-orphan",
        "item-missing",
        "0000000000",
        "Orphan",
        kind="work",
    )
    duplicate = PlanItem("item-root", "item-root", "0000000100", "Duplicate key", kind="aggregate")
    plan = Plan(
        id="plan-orphan",
        revision=1,
        output_goal="Orphan validation plan.",
        items={
            "item-root": root,
            "item-orphan": orphan,
            "item-dup-key": duplicate,
        },
    )

    result = validate_plan(plan)
    codes = {issue.code for issue in result.issues}
    assert "missing_parent" in codes
    assert "duplicate_item_id" in codes
    assert not result.ok

    missing_parent = next(issue for issue in result.issues if issue.code == "missing_parent")
    assert missing_parent.path == ["item-orphan", "item-missing"]


def test_invalid_schema_version_fails_validation() -> None:
    plan = _chain_plan(depth=1)
    plan.schema_version = 99

    result = validate_plan(plan)

    assert not result.ok
    assert any(issue.code == "invalid_schema_version" for issue in result.issues)


def test_executable_parent_overlap_warns_without_blocking() -> None:
    plan = Plan(
        id="plan-overlap",
        revision=0,
        output_goal="Goal.",
        items={
            "item-parent": PlanItem(
                id="item-parent",
                parent_id=None,
                order_key="0000000000",
                title="Parent work",
                kind="work",
                outcome="Parent outcome.",
            ),
            "item-child": PlanItem(
                id="item-child",
                parent_id="item-parent",
                order_key="0000000000",
                title="Child work",
                kind="work",
                outcome="Child outcome.",
            ),
        },
    )
    result = validate_plan(plan)
    assert result.ok
    overlap = [issue for issue in result.issues if issue.code == "executable_parent_overlap"]
    assert len(overlap) == 1
    assert overlap[0].severity == "warning"
    assert "item-parent" in overlap[0].message
    assert "executable descendants" in overlap[0].message


def test_duplicate_looking_sibling_contracts_warns_without_blocking() -> None:
    plan = Plan(
        id="plan-dup",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Deliverable",
                outcome="Deliverable outcome.",
                kind="aggregate",
            ),
            "item-a": PlanItem(
                id="item-a",
                parent_id="item-root",
                order_key="0000000000",
                title="Same title",
                kind="work",
                outcome="Same outcome.",
                acceptance=["done"],
            ),
            "item-b": PlanItem(
                id="item-b",
                parent_id="item-root",
                order_key="0000000100",
                title="Same title",
                kind="work",
                outcome="Same outcome.",
                acceptance=["done"],
            ),
        },
    )
    result = validate_plan(plan)
    assert result.ok
    dupes = [
        issue
        for issue in result.issues
        if issue.code == "duplicate_looking_sibling_contracts"
    ]
    assert len(dupes) == 1
    assert dupes[0].severity == "warning"
    assert "item-a" in dupes[0].message and "item-b" in dupes[0].message


def test_plan_quality_warnings_remain_warnings_in_approval_mode() -> None:
    plan = Plan(
        id="plan-overlap-approval",
        revision=0,
        output_goal="Goal.",
        items={
            "item-parent": PlanItem(
                id="item-parent",
                parent_id=None,
                order_key="0000000000",
                title="Parent work",
                kind="work",
                scope=Scope(includes=["parent capability"]),
            ),
            "item-child": PlanItem(
                id="item-child",
                parent_id="item-parent",
                order_key="0000000000",
                title="Child work",
                kind="work",
                scope=Scope(includes=["child capability"]),
            ),
        },
    )
    approval = validate_plan(plan, mode="approval")
    assert approval.ok
    assert any(
        issue.code == "executable_parent_overlap" and issue.severity == "warning"
        for issue in approval.issues
    )


def test_seed_root_without_children_passes_validation() -> None:
    plan = Plan(
        id="plan-seed",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Root",
                kind="aggregate",
            ),
        },
    )

    result = validate_plan(plan)

    assert result.ok
    assert not any(issue.code.startswith("default_root") for issue in result.issues)
    assert not any(issue.code == "missing_root_outcome" for issue in result.issues)


def test_default_root_with_children_fails_validation() -> None:
    plan = Plan(
        id="plan-root-default",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Root",
                kind="aggregate",
            ),
            "item-work": PlanItem(
                id="item-work",
                parent_id="item-root",
                order_key="0000000000",
                title="Work",
                kind="work",
                outcome="Done.",
            ),
        },
    )

    result = validate_plan(plan)

    assert not result.ok
    codes = {issue.code for issue in result.issues}
    assert "default_root_title" in codes
    assert "missing_root_outcome" in codes


def test_default_root_title_is_case_insensitive() -> None:
    plan = Plan(
        id="plan-root-case",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="root",
                outcome="Deliverable outcome.",
                kind="aggregate",
            ),
            "item-work": PlanItem(
                id="item-work",
                parent_id="item-root",
                order_key="0000000000",
                title="Work",
                kind="work",
                outcome="Done.",
            ),
        },
    )

    result = validate_plan(plan)

    assert not result.ok
    assert any(issue.code == "default_root_title" for issue in result.issues)


def test_populated_root_with_children_passes_validation() -> None:
    plan = Plan(
        id="plan-root-ok",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Deliverable",
                outcome="Deliverable outcome.",
                kind="aggregate",
            ),
            "item-work": PlanItem(
                id="item-work",
                parent_id="item-root",
                order_key="0000000000",
                title="Work",
                kind="work",
                outcome="Done.",
            ),
        },
    )

    result = validate_plan(plan)

    assert result.ok


def _work_leaf_plan(**item_overrides: object) -> Plan:
    defaults: dict[str, object] = {
        "id": "item-work",
        "parent_id": "item-root",
        "order_key": "0000000000",
        "title": "Work",
        "kind": "work",
        "outcome": "Work outcome.",
    }
    defaults.update(item_overrides)
    return Plan(
        id="plan-scope-contract",
        revision=0,
        output_goal="Goal.",
        scope=Scope(includes=["plan scope"]),
        boundaries=["plan boundary"],
        items={
            "item-root": PlanItem(
                id="item-root",
                parent_id=None,
                order_key="0000000000",
                title="Deliverable",
                outcome="Root outcome.",
                kind="aggregate",
            ),
            str(defaults["id"]): PlanItem(**defaults),  # type: ignore[arg-type]
        },
    )


def test_work_item_scope_contract_warns_in_draft_errors_in_approval() -> None:
    plan = _work_leaf_plan()

    draft = validate_plan(plan, mode="draft")
    assert draft.ok
    scope_issues = [
        issue for issue in draft.issues if issue.code == "missing_work_item_scope_contract"
    ]
    assert len(scope_issues) == 1
    assert scope_issues[0].severity == "warning"

    approval = validate_plan(plan, mode="approval")
    assert not approval.ok
    approval_scope = [
        issue for issue in approval.issues if issue.code == "missing_work_item_scope_contract"
    ]
    assert len(approval_scope) == 1
    assert approval_scope[0].severity == "error"


def test_work_item_scope_contract_rejects_whitespace_only_entries() -> None:
    plan = _work_leaf_plan(scope=Scope(includes=["   "]))
    approval = validate_plan(plan, mode="approval")
    assert not approval.ok
    assert any(
        issue.code == "missing_work_item_scope_contract"
        for issue in approval.issues
    )


@pytest.mark.parametrize(
    "patch",
    [
        {"scope": Scope(includes=["owned capability"])},
        {"scope": Scope(excludes=["out of scope"])},
        {"boundaries": ["No external APIs"]},
    ],
)
def test_work_item_scope_contract_passes_with_item_level_field(patch: dict) -> None:
    plan = _work_leaf_plan(**patch)

    draft = validate_plan(plan, mode="draft")
    approval = validate_plan(plan, mode="approval")

    assert not [
        issue
        for issue in draft.issues
        if issue.code == "missing_work_item_scope_contract"
    ]
    assert not [
        issue
        for issue in approval.issues
        if issue.code == "missing_work_item_scope_contract"
    ]
