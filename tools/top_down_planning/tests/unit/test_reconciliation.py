"""Unit tests for plan-amendment reconciliation."""

from __future__ import annotations

from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.reconciliation import (
    ReconciliationReport,
    apply_reconciliation,
    build_reconciliation_report,
)


def test_build_reconciliation_report_classifies_items() -> None:
    root = PlanItem("item-root", None, "0000000000", "Root")
    first = PlanItem("item-first", "item-root", "0000000000", "First", outcome="A.")
    changed = PlanItem("item-changed", "item-root", "0000000100", "Changed", outcome="Old.")
    removed = PlanItem("item-removed", "item-root", "0000000200", "Removed", outcome="Gone.")
    prior_plan = Plan(
        id="plan-test",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": root,
            "item-first": first,
            "item-changed": changed,
            "item-removed": removed,
        },
    )
    updated_changed = PlanItem(
        "item-changed",
        "item-root",
        "0000000100",
        "Changed",
        outcome="New.",
    )
    added = PlanItem("item-added", "item-root", "0000000300", "Added", outcome="Fresh.")
    new_plan = Plan(
        id="plan-test",
        revision=1,
        output_goal="Goal.",
        items={
            "item-root": root,
            "item-first": first,
            "item-changed": updated_changed,
            "item-added": added,
        },
    )

    report = build_reconciliation_report(
        amendment_id="amendment-01",
        prior_plan=prior_plan,
        new_plan=new_plan,
        production={"dispositions": {"item-first": "completed"}, "batches": []},
    )

    assert report.unchanged == ("item-first", "item-root")
    assert report.changed == ("item-changed",)
    assert report.removed == ("item-removed",)
    assert report.newly_added == ("item-added",)


def test_apply_reconciliation_marks_amendment_completed() -> None:
    report = ReconciliationReport(
        amendment_id="amendment-01",
        prior_plan_revision=0,
        new_plan_revision=1,
        unchanged=("item-first",),
        changed=(),
        removed=(),
        newly_added=("item-added",),
        evidence_preserved=("item-first",),
    )
    production = {
        "revision": 2,
        "pending_amendment_id": "amendment-01",
        "amendment_requests": [
            {
                "id": "amendment-01",
                "status": "pending",
                "evidence": "Need more scope.",
                "affected_refs": ["item-root"],
            }
        ],
        "reconciliation_reports": [],
    }

    updated = apply_reconciliation(production, report)

    assert updated["pending_amendment_id"] is None
    assert updated["amendment_requests"][0]["status"] == "completed"
    assert updated["reconciliation_reports"][0]["newly_added"] == ["item-added"]
