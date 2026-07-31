"""Unit tests for dependency DAG, satisfaction, readiness, and deadlock detection."""

from __future__ import annotations

from top_down_planning.domain.dependencies import (
    dependency_cycle_issue,
    find_dependency_cycle,
)
from top_down_planning.domain.dispositions import DispositionMap
from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.readiness import (
    compute_ready_view,
    detect_deadlock,
    is_applicable_item,
    resolve_satisfaction,
)


def _plan_with_sibling_deps() -> Plan:
    root = PlanItem("item-root", None, "0000000000", "Root", kind="aggregate")
    first = PlanItem("item-first", "item-root", "0000000000", "First", kind="work")
    second = PlanItem(
        "item-second",
        "item-root",
        "0000000100",
        "Second",
        depends_on=["item-first"],
        kind="work",
    )
    return Plan(
        id="plan-deps",
        revision=1,
        output_goal="Test dependencies.",
        items={
            "item-root": root,
            "item-first": first,
            "item-second": second,
        },
    )


def test_dependency_cycle_returns_full_path() -> None:
    plan = _plan_with_sibling_deps()
    plan.items["item-first"] = PlanItem(
        "item-first",
        "item-root",
        "0000000000",
        "First",
        depends_on=["item-second"],
        kind="work",
    )

    cycle = find_dependency_cycle(plan)
    assert cycle == ["item-first", "item-second", "item-first"]

    issue = dependency_cycle_issue(plan)
    assert issue is not None
    assert issue.code == "dependency_cycle"
    assert issue.path == ["item-first", "item-second", "item-first"]
    assert issue.to_dict() == {
        "code": "dependency_cycle",
        "path": ["item-first", "item-second", "item-first"],
    }


def test_unsatisfied_dependency_blocks_readiness_until_completed() -> None:
    plan = _plan_with_sibling_deps()
    dispositions: DispositionMap = {}

    blocked = compute_ready_view(plan, dispositions)
    assert "item-second" not in blocked.ready_item_ids
    assert "item-second" in blocked.not_ready
    blocker = blocked.not_ready["item-second"]
    assert blocker.reason == "unsatisfied_dependency"
    assert blocker.chain == ["item-second", "item-first"]

    dispositions["item-first"] = "completed"
    ready = compute_ready_view(plan, dispositions)
    assert "item-second" in ready.ready_item_ids
    assert "item-second" not in ready.not_ready
    assert not is_applicable_item(plan, "item-first", dispositions)


def test_cross_branch_dependency_readiness() -> None:
    root = PlanItem("item-root", None, "0000000000", "Root", kind="aggregate")
    branch_a = PlanItem("item-a", "item-root", "0000000000", "Branch A", kind="work")
    branch_b = PlanItem(
        "item-b",
        "item-root",
        "0000000100",
        "Branch B",
        depends_on=["item-a"],
        kind="work",
    )
    plan = Plan(
        id="plan-cross",
        revision=1,
        output_goal="Cross-branch deps.",
        items={
            "item-root": root,
            "item-a": branch_a,
            "item-b": branch_b,
        },
    )

    view = compute_ready_view(plan, {})
    assert "item-a" in view.ready_item_ids
    assert "item-b" not in view.ready_item_ids

    view = compute_ready_view(plan, {"item-a": "completed"})
    assert "item-b" in view.ready_item_ids


def test_non_leaf_derives_satisfaction_from_terminal_children() -> None:
    root = PlanItem("item-root", None, "0000000000", "Root", kind="aggregate")
    parent = PlanItem("item-parent", "item-root", "0000000000", "Parent", kind="work")
    child_a = PlanItem("item-child-a", "item-parent", "0000000000", "Child A", kind="work")
    child_b = PlanItem("item-child-b", "item-parent", "0000000100", "Child B", kind="work")
    dependent = PlanItem(
        "item-dependent",
        "item-root",
        "0000000200",
        "Dependent",
        depends_on=["item-parent"],
        kind="work",
    )
    plan = Plan(
        id="plan-subtree",
        revision=1,
        output_goal="Subtree satisfaction.",
        items={
            "item-root": root,
            "item-parent": parent,
            "item-child-a": child_a,
            "item-child-b": child_b,
            "item-dependent": dependent,
        },
    )

    parent_result = resolve_satisfaction(plan, "item-parent", {})
    assert parent_result.state == "unresolved"
    assert parent_result.source == "derived_subtree"
    assert parent_result.blocker_item_id == "item-child-a"

    dispositions: DispositionMap = {
        "item-child-a": "completed",
        "item-child-b": "satisfied_without_change",
    }
    parent_result = resolve_satisfaction(plan, "item-parent", dispositions)
    assert parent_result.state == "satisfied"
    assert parent_result.source == "derived_subtree"

    view = compute_ready_view(plan, dispositions)
    assert "item-dependent" in view.ready_item_ids


def test_leaf_without_disposition_reports_missing_disposition() -> None:
    plan = _plan_with_sibling_deps()

    result = resolve_satisfaction(plan, "item-first", {})
    assert result.state == "unresolved"
    assert result.blocker_reason == "missing_disposition"
    assert result.blocker_item_id == "item-first"


def _cyclic_plan() -> Plan:
    item_a = PlanItem(
        "item-a",
        None,
        "0000000000",
        "A",
        depends_on=["item-b"],
        kind="work",
    )
    item_b = PlanItem(
        "item-b",
        None,
        "0000000100",
        "B",
        depends_on=["item-a"],
        kind="work",
    )
    return Plan(
        id="plan-cycle",
        revision=1,
        output_goal="Cyclic dependencies.",
        items={"item-a": item_a, "item-b": item_b},
    )


def _blocked_gate_plan() -> Plan:
    gate = PlanItem("item-gate", None, "0000000000", "Gate", kind="work")
    worker = PlanItem(
        "item-worker",
        None,
        "0000000100",
        "Worker",
        depends_on=["item-gate"],
        kind="work",
    )
    return Plan(
        id="plan-blocked",
        revision=1,
        output_goal="Blocked gate dependency.",
        items={"item-gate": gate, "item-worker": worker},
    )


def test_deadlock_reports_cycle_when_nothing_is_ready() -> None:
    plan = _cyclic_plan()

    report = detect_deadlock(plan, {})
    assert report is not None
    assert report.cause == "cycle"
    assert set(report.waiting_item_ids) == {"item-a", "item-b"}
    assert "dependency cycle" in report.explanation


def test_deadlock_detects_blocked_dependency_cause() -> None:
    plan = _blocked_gate_plan()
    dispositions: DispositionMap = {"item-gate": "blocked"}

    report = detect_deadlock(plan, dispositions)
    assert report is not None
    assert report.cause == "blocked_dependency"
    assert "blocked disposition" in report.explanation
    assert "item-worker" in report.waiting_item_ids
    assert "item-gate" not in report.waiting_item_ids


def test_deadlock_detects_review_blocked_cause() -> None:
    plan = _blocked_gate_plan()

    report = detect_deadlock(
        plan,
        {},
        is_review_blocked=lambda item_id: item_id in {"item-gate", "item-worker"},
    )
    assert report is not None
    assert report.cause == "review_blocked"
    assert "unresolved review finding" in report.explanation


def test_review_blocked_items_are_not_ready() -> None:
    plan = _plan_with_sibling_deps()
    dispositions: DispositionMap = {"item-first": "completed"}

    view = compute_ready_view(
        plan,
        dispositions,
        is_review_blocked=lambda item_id: item_id == "item-second",
    )
    assert "item-second" not in view.ready_item_ids
    assert view.not_ready["item-second"].reason == "review_blocked"
