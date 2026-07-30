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
    """Attach reconciliation report and clear the pending amendment marker."""

    updated = dict(production)
    reports = list(updated.get("reconciliation_reports") or [])
    reports.append(report.to_dict())
    updated["reconciliation_reports"] = reports
    updated["pending_amendment_id"] = None

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


def _item_has_output_evidence(production: dict[str, Any], item_id: str) -> bool:
    for batch_payload in production.get("batches") or []:
        if not isinstance(batch_payload, dict):
            continue
        if item_id not in (batch_payload.get("plan_items") or []):
            continue
        return True
    return False
