"""Plan-amendment reconciliation (proposal §10.4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from top_down_planning.domain.models import Plan, PlanItem


@dataclass(frozen=True)
class ReconciliationReport:
    amendment_id: str
    prior_plan_revision: int
    new_plan_revision: int
    unchanged: tuple[str, ...]
    changed: tuple[str, ...]
    removed: tuple[str, ...]
    newly_added: tuple[str, ...]
    evidence_preserved: tuple[str, ...]

    @property
    def invalidated_item_ids(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.changed) | set(self.removed)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "amendment_id": self.amendment_id,
            "prior_plan_revision": self.prior_plan_revision,
            "new_plan_revision": self.new_plan_revision,
            "unchanged": list(self.unchanged),
            "changed": list(self.changed),
            "removed": list(self.removed),
            "newly_added": list(self.newly_added),
            "evidence_preserved": list(self.evidence_preserved),
            "invalidated_item_ids": list(self.invalidated_item_ids),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ReconciliationReport:
        return cls(
            amendment_id=str(payload["amendment_id"]),
            prior_plan_revision=int(payload["prior_plan_revision"]),
            new_plan_revision=int(payload["new_plan_revision"]),
            unchanged=tuple(str(item_id) for item_id in (payload.get("unchanged") or [])),
            changed=tuple(str(item_id) for item_id in (payload.get("changed") or [])),
            removed=tuple(str(item_id) for item_id in (payload.get("removed") or [])),
            newly_added=tuple(
                str(item_id) for item_id in (payload.get("newly_added") or [])
            ),
            evidence_preserved=tuple(
                str(item_id) for item_id in (payload.get("evidence_preserved") or [])
            ),
        )


def _item_signature(item: PlanItem) -> tuple[Any, ...]:
    return (
        item.parent_id,
        item.order_key,
        item.title,
        item.outcome,
        tuple(item.acceptance or ()),
        tuple(item.depends_on or ()),
        tuple(item.boundaries or ()),
        item.scope.to_dict(),
        item.planning_status,
        item.superseded_by,
    )


def build_reconciliation_report(
    *,
    amendment_id: str,
    prior_plan: Plan,
    new_plan: Plan,
    production: dict[str, Any],
) -> ReconciliationReport:
    """Compare plan revisions and record how production evidence maps forward."""

    prior_ids = set(prior_plan.items)
    new_ids = set(new_plan.items)

    unchanged: list[str] = []
    changed: list[str] = []
    removed = sorted(prior_ids - new_ids)
    newly_added = sorted(new_ids - prior_ids)

    for item_id in sorted(prior_ids & new_ids):
        if _item_signature(prior_plan.items[item_id]) == _item_signature(
            new_plan.items[item_id]
        ):
            unchanged.append(item_id)
        else:
            changed.append(item_id)

    dispositions = dict(production.get("dispositions") or {})
    evidence_preserved = sorted(
        item_id
        for item_id in unchanged
        if item_id in dispositions or _item_has_output_evidence(production, item_id)
    )

    return ReconciliationReport(
        amendment_id=amendment_id,
        prior_plan_revision=prior_plan.revision,
        new_plan_revision=new_plan.revision,
        unchanged=tuple(unchanged),
        changed=tuple(changed),
        removed=tuple(removed),
        newly_added=tuple(newly_added),
        evidence_preserved=tuple(evidence_preserved),
    )


def apply_reconciliation(
    production: dict[str, Any],
    report: ReconciliationReport,
) -> dict[str, Any]:
    """Attach reconciliation report, invalidate stale evidence, and clear pending amendment."""

    updated = dict(production)
    reports = list(updated.get("reconciliation_reports") or [])
    reports.append(report.to_dict())
    updated["reconciliation_reports"] = reports
    updated["pending_amendment_id"] = None

    dispositions = dict(updated.get("dispositions") or {})
    for item_id in report.removed:
        dispositions.pop(item_id, None)
    for item_id in report.changed:
        dispositions.pop(item_id, None)
    updated["dispositions"] = dispositions

    if report.changed or report.removed:
        updated["completion_claim"] = None
        updated["blocker_report"] = None
        updated = _invalidate_evidence_for_items(updated, report.invalidated_item_ids)

    requests = list(updated.get("amendment_requests") or [])
    patched_requests: list[dict[str, Any]] = []
    for request in requests:
        if not isinstance(request, dict):
            continue
        if str(request.get("id") or "") != report.amendment_id:
            patched_requests.append(request)
            continue
        completed = dict(request)
        completed["status"] = "completed"
        completed["reconciliation"] = report.to_dict()
        completed["new_plan_revision"] = report.new_plan_revision
        patched_requests.append(completed)
    updated["amendment_requests"] = patched_requests
    return updated


def _invalidate_evidence_for_items(
    production: dict[str, Any],
    invalidated_item_ids: tuple[str, ...],
) -> dict[str, Any]:
    """Mark batch/evidence artifacts for changed/removed items and drop live output refs."""

    if not invalidated_item_ids:
        return production

    invalidated_ids = set(invalidated_item_ids)
    updated = dict(production)
    invalidated_batch_ids: set[str] = set()
    updated_batches: list[dict[str, Any]] = []

    for batch_payload in updated.get("batches") or []:
        if not isinstance(batch_payload, dict):
            continue
        plan_items = {str(item_id) for item_id in (batch_payload.get("plan_items") or [])}
        overlap = sorted(plan_items & invalidated_ids)
        if not overlap:
            updated_batches.append(batch_payload)
            continue
        marked = dict(batch_payload)
        marked["evidence_status"] = "invalidated_by_reconciliation"
        marked["invalidated_item_ids"] = overlap
        batch_id = str(marked.get("id") or "")
        if batch_id:
            invalidated_batch_ids.add(batch_id)
        updated_batches.append(marked)

    updated["batches"] = updated_batches
    updated["output_evidence"] = [
        entry
        for entry in (updated.get("output_evidence") or [])
        if isinstance(entry, dict)
        and str(entry.get("batch_id") or "") not in invalidated_batch_ids
    ]
    updated["output_revision"] = int(updated.get("output_revision") or 0) + 1
    return updated


def _item_has_output_evidence(production: dict[str, Any], item_id: str) -> bool:
    for batch_payload in production.get("batches") or []:
        if not isinstance(batch_payload, dict):
            continue
        if item_id not in (batch_payload.get("plan_items") or []):
            continue
        return True
    return False
