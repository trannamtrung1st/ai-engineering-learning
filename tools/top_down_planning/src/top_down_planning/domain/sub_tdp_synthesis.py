"""Synthesize parent production from completed Sub-TDP child runs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from top_down_planning.domain.models import Plan
from top_down_planning.domain.plan_tree import is_active_item, walk_active_tree
from top_down_planning.domain.unit_plan import collect_assigned_item_ids
from top_down_planning.domain.production import (
    disposition_map_from_records,
    parse_disposition_records,
)

_CHILD_OUTPUT_VALIDATED_PHASE = "output_validated"
_ORCHESTRATION_STATUS_COMPLETED = "completed"
_UNIT_STATUS_COMPLETED = "completed"


def _is_child_terminal_accepted(child_run: dict[str, Any]) -> bool:
    return (
        str(child_run.get("status") or "") == "completed"
        and str(child_run.get("phase") or "") == _CHILD_OUTPUT_VALIDATED_PHASE
        and str(child_run.get("outcome") or "") == "accepted"
    )


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def child_run_summary(child_production: dict[str, Any], child_run: dict[str, Any]) -> str:
    claim = child_production.get("completion_claim")
    if isinstance(claim, dict) and str(claim.get("goal_assessment") or "").strip():
        return str(claim["goal_assessment"]).strip()
    outcome = child_run.get("outcome")
    return f"Child run {child_run.get('id')} completed with outcome={outcome!r}."


def synthesize_parent_production(
    plan: Plan,
    production: dict[str, Any],
    *,
    child_runs: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]],
    parent_output_goal: str,
) -> dict[str, Any]:
    """
    Build parent production snapshot for whole_output_review.

    ``child_runs`` is a list of (unit_record, child_run, child_production).

    Synthesis is fail-closed on missing child dispositions and does **not**
    assert that the parent goal is met — that requires a subsequent
    integration validation step.
    """

    state = production.get("sub_tdps")
    if not isinstance(state, dict):
        raise ValueError("parent production missing sub_tdps orchestration state")
    state = dict(state)

    output_evidence: list[dict[str, Any]] = []
    contributions: list[dict[str, Any]] = []
    disposition_records: dict[str, Any] = {}
    summaries: list[str] = []
    covered_work_items: set[str] = set()

    batch_id = "batch-integration-01"
    seen_evidence_ids: set[str] = set()
    for unit, child_run, child_production in child_runs:
        plan_item_id = str(unit.get("plan_item_id") or unit.get("id") or "")
        if not plan_item_id:
            continue
        if not _is_child_terminal_accepted(child_run):
            raise ValueError(
                f"child run {child_run.get('id')} for unit {plan_item_id} "
                "must reach output_validated with outcome=accepted before synthesis"
            )
        summary = child_run_summary(child_production, child_run)
        child_output_refs: list[str] = []
        for evidence in child_production.get("output_evidence") or []:
            if not isinstance(evidence, dict):
                continue
            evidence_id = str(evidence.get("id") or "").strip()
            if not evidence_id:
                continue
            unique_id = evidence_id
            if unique_id in seen_evidence_ids:
                unique_id = f"{child_run.get('id')}-{evidence_id}"
            seen_evidence_ids.add(unique_id)
            merged_evidence = dict(evidence)
            merged_evidence["id"] = unique_id
            merged_evidence["batch_id"] = batch_id
            merged_evidence["source_child_batch_id"] = str(
                evidence.get("batch_id") or ""
            )
            merged_evidence["source_child_evidence_id"] = evidence_id
            merged_evidence["sub_tdp_child_run_id"] = child_run.get("id")
            merged_evidence["sub_tdp_unit_id"] = plan_item_id
            merged_evidence["sub_tdp_plan_item_id"] = plan_item_id
            output_evidence.append(merged_evidence)
            child_output_refs.append(unique_id)
        contributions.append(
            {
                "item_id": plan_item_id,
                "output_refs": child_output_refs,
                "summary": summary,
            }
        )
        child_dispositions = child_production.get("dispositions") or {}
        for assigned_id in collect_assigned_item_ids(plan, plan_item_id):
            assigned_item = plan.items.get(assigned_id)
            if assigned_item is None or assigned_item.kind != "work":
                continue
            covered_work_items.add(assigned_id)
            child_disp = child_dispositions.get(assigned_id)
            if isinstance(child_disp, str) and child_disp.strip():
                disposition_records[assigned_id] = {
                    "disposition": child_disp.strip(),
                    "evidence": (
                        f"Sub-TDP child {child_run.get('id')} disposition for "
                        f"{assigned_id}."
                    ),
                }
            elif isinstance(child_disp, dict) and child_disp.get("disposition"):
                disposition_records[assigned_id] = dict(child_disp)
            else:
                raise ValueError(
                    f"missing terminal child disposition for assigned work item "
                    f"{assigned_id!r} in unit {plan_item_id}"
                )
        summaries.append(f"{unit.get('title')}: {summary}")

    for item_id, _, _ in walk_active_tree(plan).rows:
        item = plan.items[item_id]
        if not is_active_item(item) or item.kind != "work":
            continue
        if item_id not in covered_work_items:
            raise ValueError(
                f"active work item {item_id!r} has no child-derived disposition; "
                "package unit coverage or synthesis inputs are incomplete"
            )

    parsed_records = parse_disposition_records(disposition_records)
    flat_dispositions = disposition_map_from_records(parsed_records)

    completion_claim = {
        "goal_met": False,
        "status": "integration_pending",
        "goal_assessment": (
            "Child Sub-TDP deliveries collected; parent integration validation "
            f"is still required for output goal: {parent_output_goal.strip()}. "
            + " ".join(summaries)
        ).strip(),
        "submitted_at": _utc_now(),
    }

    batch_result = {
        "outputs": output_evidence,
        "contributions": contributions,
        "dispositions": disposition_records,
        "summary": "Sub-TDP integration synthesis (integration pending)",
        "empty_output": False,
        "goal_assessment": completion_claim["goal_assessment"],
    }
    batch = {
        "id": batch_id,
        "plan_items": [
            item_id
            for item_id, record in disposition_records.items()
            if record.get("disposition") == "completed"
        ],
        "status": "completed",
        "agent_turns": 0,
        "intent": "sub_tdp_integration",
        "result": batch_result,
    }

    merged = dict(production)
    merged["batches"] = [batch]
    merged["dispositions"] = flat_dispositions
    merged["output_evidence"] = output_evidence
    merged["completion_claim"] = completion_claim
    merged["output_revision"] = int(merged.get("output_revision") or 0) + 1
    merged["revision"] = int(merged.get("revision") or 0) + 1

    state = dict(state)
    state["status"] = _ORCHESTRATION_STATUS_COMPLETED
    state["active_unit_id"] = None
    completed_ids = {
        str(unit.get("plan_item_id") or unit.get("id") or "")
        for unit, _, _ in child_runs
    }
    for unit_record in state.get("units") or []:
        if not isinstance(unit_record, dict):
            continue
        plan_item_id = str(unit_record.get("plan_item_id") or "")
        if plan_item_id in completed_ids:
            unit_record["status"] = _UNIT_STATUS_COMPLETED
    merged["sub_tdps"] = state
    return merged


__all__ = ["child_run_summary", "synthesize_parent_production"]
