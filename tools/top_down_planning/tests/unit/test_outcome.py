"""Tests for acceptance invariant and outcome resolution."""

from __future__ import annotations

from top_down_planning.domain.models import Plan, PlanItem
from top_down_planning.domain.outcome import AcceptanceInvariant, evaluate_acceptance_invariant
from top_down_planning.domain.validators import PlanningLimits
from top_down_planning.persistence.digests import compute_config_digest, compute_output_digest, compute_plan_digest


def _sample_plan() -> Plan:
    root = PlanItem("item-root", None, "0000000000", "Root")
    leaf = PlanItem(
        "item-leaf",
        "item-root",
        "0000000000",
        "Leaf",
        outcome="Done.",
        acceptance=["Verifiable."],
    )
    return Plan(
        id="plan-1",
        revision=0,
        output_goal="Deliver.",
        items={"item-root": root, "item-leaf": leaf},
    )


def _sample_run() -> dict:
    plan = _sample_plan()
    return {
        "digests": {
            "input": "input-a",
            "output_goal": "goal-b",
            "config": "config-c",
            "plan": compute_plan_digest(plan),
            "output": "output-d",
        }
    }


def test_acceptance_invariant_requires_all_checks() -> None:
    invariant = AcceptanceInvariant(
        plan_whole_plan_review_approved_current_revision=True,
        plan_deterministic_plan_validation_passed=True,
        production_all_applicable_items_terminal_or_derived=True,
        production_output_goal_explicitly_assessed_as_met=True,
        output_whole_output_review_approved_current_revision=True,
        output_deterministic_output_validation_passed=True,
        findings_unresolved_blocking_findings=0,
    )
    assert invariant.satisfied is True

    blocked = AcceptanceInvariant(
        plan_whole_plan_review_approved_current_revision=True,
        plan_deterministic_plan_validation_passed=True,
        production_all_applicable_items_terminal_or_derived=True,
        production_output_goal_explicitly_assessed_as_met=False,
        output_whole_output_review_approved_current_revision=True,
        output_deterministic_output_validation_passed=True,
        findings_unresolved_blocking_findings=0,
    )
    assert blocked.satisfied is False


def test_missing_goal_assessment_cannot_accept() -> None:
    plan = _sample_plan()
    production = {
        "revision": 1,
        "output_revision": 1,
        "batches": [],
        "dispositions": {"item-leaf": "completed"},
        "output_evidence": [],
        "completion_claim": {"goal_assessment": "", "summary": ""},
    }
    reviews = [
        {
            "id": "review-whole-plan-01",
            "type": "whole_plan",
            "status": "approved",
            "target_revision": 0,
            "findings": [],
        },
        {
            "id": "review-whole-output-01",
            "type": "whole_output",
            "status": "approved",
            "target_revision": 1,
            "findings": [],
        },
    ]
    run = _sample_run()
    run["digests"]["output"] = compute_output_digest(production)

    invariant, _plan_validation, output_validation = evaluate_acceptance_invariant(
        plan=plan,
        production=production,
        reviews=reviews,
        limits=PlanningLimits(),
        run=run,
        plan_approval=reviews[0],
        output_approval=reviews[1],
        actual_plan_digest=compute_plan_digest(plan),
        actual_config_digest=compute_config_digest({"run": {"output_goal": "Deliver."}}),
        actual_output_digest=compute_output_digest(production),
    )

    assert output_validation.ok is False
    assert invariant.satisfied is False
    assert invariant.production_output_goal_explicitly_assessed_as_met is False


def test_unapproved_output_cannot_accept() -> None:
    plan = _sample_plan()
    production = {
        "revision": 1,
        "output_revision": 1,
        "batches": [],
        "dispositions": {"item-leaf": "completed"},
        "output_evidence": [],
        "completion_claim": {"goal_assessment": "Goal met.", "summary": ""},
    }
    reviews = [
        {
            "id": "review-whole-plan-01",
            "type": "whole_plan",
            "status": "approved",
            "target_revision": 0,
            "findings": [],
        }
    ]
    run = _sample_run()
    run["digests"]["output"] = compute_output_digest(production)

    invariant, _plan_validation, output_validation = evaluate_acceptance_invariant(
        plan=plan,
        production=production,
        reviews=reviews,
        limits=PlanningLimits(),
        run=run,
        plan_approval=reviews[0],
        output_approval=None,
        actual_plan_digest=compute_plan_digest(plan),
        actual_config_digest=compute_config_digest({"run": {"output_goal": "Deliver."}}),
        actual_output_digest=compute_output_digest(production),
    )

    assert output_validation.ok is False
    assert invariant.satisfied is False
    assert invariant.output_whole_output_review_approved_current_revision is False


def test_accepted_outcome_is_not_assigned_directly_in_source() -> None:
    from pathlib import Path

    src_root = Path(__file__).resolve().parents[2] / "src" / "top_down_planning"
    direct_assignments: list[str] = []
    for path in sorted(src_root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if 'run["outcome"] = "accepted"' in text or "run['outcome'] = 'accepted'" in text:
            direct_assignments.append(str(path.relative_to(src_root)))

    assert direct_assignments == []
