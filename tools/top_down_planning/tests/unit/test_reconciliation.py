"""Unit tests for plan-amendment reconciliation."""

from __future__ import annotations

from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.reconciliation import (
    ReconciliationReport,
    apply_reconciliation,
    build_reconciliation_report,
)
from top_down_planning.persistence.digests import compute_output_digest


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


def test_apply_reconciliation_clears_stale_dispositions() -> None:
    report = ReconciliationReport(
        amendment_id="amendment-01",
        prior_plan_revision=0,
        new_plan_revision=1,
        unchanged=("item-root",),
        changed=("item-changed",),
        removed=("item-removed",),
        newly_added=("item-added",),
        evidence_preserved=(),
    )
    production = {
        "revision": 2,
        "pending_amendment_id": "amendment-01",
        "dispositions": {
            "item-changed": "completed",
            "item-removed": "completed",
            "item-root": "completed",
        },
        "completion_claim": {
            "goal_assessment": "Goal met.",
            "goal_met": True,
        },
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

    assert "item-changed" not in updated["dispositions"]
    assert "item-removed" not in updated["dispositions"]
    assert updated["dispositions"]["item-root"] == "completed"
    assert updated["completion_claim"] is None


def test_apply_reconciliation_invalidates_batch_and_output_evidence() -> None:
    report = ReconciliationReport(
        amendment_id="amendment-01",
        prior_plan_revision=0,
        new_plan_revision=1,
        unchanged=("item-root",),
        changed=("item-changed",),
        removed=(),
        newly_added=(),
        evidence_preserved=(),
    )
    production = {
        "revision": 2,
        "output_revision": 1,
        "pending_amendment_id": "amendment-01",
        "batches": [
            {
                "id": "batch-changed",
                "plan_items": ["item-changed"],
                "status": "completed",
            },
            {
                "id": "batch-root",
                "plan_items": ["item-root"],
                "status": "completed",
            },
        ],
        "output_evidence": [
            {"id": "output-changed", "type": "artifact", "ref": "old.py", "batch_id": "batch-changed"},
            {"id": "output-root", "type": "artifact", "ref": "root.py", "batch_id": "batch-root"},
        ],
        "dispositions": {"item-changed": "completed", "item-root": "completed"},
        "amendment_requests": [
            {
                "id": "amendment-01",
                "status": "pending",
                "evidence": "Scope change.",
                "affected_refs": ["item-changed"],
            }
        ],
        "reconciliation_reports": [],
    }

    updated = apply_reconciliation(production, report)

    changed_batch = next(b for b in updated["batches"] if b["id"] == "batch-changed")
    root_batch = next(b for b in updated["batches"] if b["id"] == "batch-root")
    assert changed_batch["evidence_status"] == "invalidated_by_reconciliation"
    assert root_batch.get("evidence_status") is None
    assert updated["output_evidence"] == [
        {"id": "output-root", "type": "artifact", "ref": "root.py", "batch_id": "batch-root"}
    ]
    assert updated["output_revision"] == 2
    assert report.invalidated_item_ids == ("item-changed",)


def test_output_digest_ignores_invalidated_reconciliation_evidence() -> None:
    report = ReconciliationReport(
        amendment_id="amendment-01",
        prior_plan_revision=0,
        new_plan_revision=1,
        unchanged=("item-root",),
        changed=("item-changed",),
        removed=(),
        newly_added=(),
        evidence_preserved=(),
    )
    production = {
        "revision": 2,
        "output_revision": 1,
        "pending_amendment_id": "amendment-01",
        "batches": [
            {
                "id": "batch-changed",
                "plan_items": ["item-changed"],
                "status": "completed",
            },
            {
                "id": "batch-root",
                "plan_items": ["item-root"],
                "status": "completed",
            },
        ],
        "output_evidence": [
            {
                "id": "output-changed",
                "type": "artifact",
                "ref": "old.py",
                "batch_id": "batch-changed",
            },
            {
                "id": "output-root",
                "type": "artifact",
                "ref": "root.py",
                "batch_id": "batch-root",
            },
        ],
        "dispositions": {"item-changed": "completed", "item-root": "completed"},
        "amendment_requests": [
            {
                "id": "amendment-01",
                "status": "pending",
                "evidence": "Scope change.",
                "affected_refs": ["item-changed"],
            }
        ],
        "reconciliation_reports": [],
    }

    reconciled = apply_reconciliation(production, report)
    live_only = {
        "revision": 2,
        "output_revision": reconciled["output_revision"],
        "batches": [
            {
                "id": "batch-root",
                "plan_items": ["item-root"],
                "status": "completed",
            }
        ],
        "output_evidence": [
            {
                "id": "output-root",
                "type": "artifact",
                "ref": "root.py",
                "batch_id": "batch-root",
            }
        ],
        "dispositions": {"item-root": "completed"},
    }

    assert compute_output_digest(reconciled) == compute_output_digest(live_only)


def test_sibling_insert_renumbers_without_marking_survivors_changed() -> None:
    root = PlanItem("item-root", None, "0000000000", "Root")
    first = PlanItem("item-first", "item-root", "0000000000", "First", outcome="A.")
    second = PlanItem("item-second", "item-root", "0000000100", "Second", outcome="B.")
    prior_plan = Plan(
        id="plan-test",
        revision=0,
        output_goal="Goal.",
        items={
            "item-root": root,
            "item-first": first,
            "item-second": second,
        },
    )
    inserted = PlanItem("item-inserted", "item-root", "0000000050", "Inserted", outcome="New.")
    renumbered_second = PlanItem(
        "item-second",
        "item-root",
        "0000000200",
        "Second",
        outcome="B.",
    )
    new_plan = Plan(
        id="plan-test",
        revision=1,
        output_goal="Goal.",
        items={
            "item-root": root,
            "item-first": first,
            "item-inserted": inserted,
            "item-second": renumbered_second,
        },
    )

    report = build_reconciliation_report(
        amendment_id="amendment-01",
        prior_plan=prior_plan,
        new_plan=new_plan,
        production={
            "dispositions": {
                "item-first": "completed",
                "item-second": "completed",
            },
            "batches": [],
        },
    )

    assert report.unchanged == ("item-first", "item-root", "item-second")
    assert report.changed == ()
    assert report.newly_added == ("item-inserted",)
    assert report.evidence_preserved == ("item-first", "item-second")
