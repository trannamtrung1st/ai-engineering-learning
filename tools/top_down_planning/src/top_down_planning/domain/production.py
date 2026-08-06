"""Production batch, disposition, and output evidence models (proposal §10)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from top_down_planning.domain.dispositions import TERMINAL_DISPOSITIONS, TerminalDisposition
from top_down_planning.domain.item_contract import build_item_production_contract
from top_down_planning.domain.models import Plan
from top_down_planning.domain.readiness import compute_ready_view, detect_deadlock, is_applicable_item
from top_down_planning.domain.reviews import (
    OUTPUT_REVIEW_TYPES,
    build_is_review_blocked_fn,
    whole_output_revision_target_ids,
)

PRODUCTION_PHASE = "production"
WHOLE_OUTPUT_REVIEW_PHASE = "whole_output_review"


@dataclass(frozen=True)
class OutputEvidence:
    id: str
    type: str
    ref: str
    sha256: str
    size: int
    media_type: str
    captured_at: str
    batch_id: str | None = None
    snapshot_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "ref": self.ref,
            "sha256": self.sha256,
            "size": self.size,
            "media_type": self.media_type,
            "captured_at": self.captured_at,
        }
        if self.batch_id is not None:
            payload["batch_id"] = self.batch_id
        if self.snapshot_ref is not None:
            payload["snapshot_ref"] = self.snapshot_ref
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> OutputEvidence:
        required = ("id", "ref", "sha256", "size", "media_type", "captured_at")
        missing = [field for field in required if field not in payload]
        if missing:
            raise ValueError(
                "output evidence missing required fields: " + ", ".join(missing)
            )
        return cls(
            id=str(payload["id"]),
            type=str(payload.get("type") or "artifact"),
            ref=str(payload["ref"]),
            sha256=str(payload["sha256"]),
            size=int(payload["size"]),
            media_type=str(payload["media_type"]),
            captured_at=str(payload["captured_at"]),
            batch_id=payload.get("batch_id"),
            snapshot_ref=payload.get("snapshot_ref"),
        )


@dataclass(frozen=True)
class Contribution:
    item_id: str
    output_refs: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "output_refs": list(self.output_refs),
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Contribution:
        return cls(
            item_id=str(payload["item_id"]),
            output_refs=[str(ref) for ref in (payload.get("output_refs") or [])],
            summary=str(payload.get("summary") or ""),
        )


@dataclass(frozen=True)
class ItemDispositionRecord:
    disposition: TerminalDisposition
    reason: str | None = None
    replacement_ref: str | None = None
    evidence: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"disposition": self.disposition}
        if self.reason is not None:
            payload["reason"] = self.reason
        if self.replacement_ref is not None:
            payload["replacement_ref"] = self.replacement_ref
        if self.evidence is not None:
            payload["evidence"] = self.evidence
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ItemDispositionRecord:
        disposition = str(payload.get("disposition") or "")
        if disposition not in TERMINAL_DISPOSITIONS:
            raise ValueError(f"invalid disposition: {disposition!r}")
        return cls(
            disposition=disposition,  # type: ignore[arg-type]
            reason=_optional_str(payload.get("reason")),
            replacement_ref=_optional_str(payload.get("replacement_ref")),
            evidence=_optional_str(payload.get("evidence")),
        )


@dataclass(frozen=True)
class BatchResult:
    outputs: list[OutputEvidence]
    contributions: list[Contribution]
    dispositions: dict[str, ItemDispositionRecord]
    summary: str = ""
    empty_output: bool = False
    empty_output_reason: str | None = None
    goal_assessment: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "outputs": [output.to_dict() for output in self.outputs],
            "contributions": [contribution.to_dict() for contribution in self.contributions],
            "dispositions": {
                item_id: record.to_dict()
                for item_id, record in sorted(self.dispositions.items())
            },
            "summary": self.summary,
            "empty_output": self.empty_output,
            "goal_assessment": self.goal_assessment,
        }
        if self.empty_output_reason is not None:
            payload["empty_output_reason"] = self.empty_output_reason
        return payload


@dataclass(frozen=True)
class ProductionBatch:
    id: str
    plan_items: list[str]
    status: str
    agent_turns: int = 0
    intent: str | None = None
    result: BatchResult | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "plan_items": list(self.plan_items),
            "status": self.status,
            "agent_turns": self.agent_turns,
        }
        if self.intent is not None:
            payload["intent"] = self.intent
        if self.result is not None:
            payload["result"] = self.result.to_dict()
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ProductionBatch:
        result_payload = payload.get("result")
        result = None
        if isinstance(result_payload, dict):
            result = _batch_result_from_dict(result_payload)
        return cls(
            id=str(payload["id"]),
            plan_items=[str(item_id) for item_id in (payload.get("plan_items") or [])],
            status=str(payload.get("status") or "started"),
            agent_turns=int(payload.get("agent_turns") or 0),
            intent=_optional_str(payload.get("intent")),
            result=result,
        )


def is_production_phase(phase: str) -> bool:
    return phase == PRODUCTION_PHASE


def allows_production_mutations(phase: str) -> bool:
    return phase in {PRODUCTION_PHASE, WHOLE_OUTPUT_REVIEW_PHASE}


def parse_disposition_records(
    raw: Any,
) -> dict[str, ItemDispositionRecord]:
    if not isinstance(raw, dict):
        raise ValueError("dispositions must be an object")
    records: dict[str, ItemDispositionRecord] = {}
    for item_id, value in raw.items():
        if not isinstance(value, dict):
            raise ValueError(f"disposition for {item_id!r} must be an object")
        records[str(item_id)] = ItemDispositionRecord.from_dict(value)
    return records


def validate_disposition_record(record: ItemDispositionRecord) -> list[str]:
    issues: list[str] = []
    if record.disposition == "not_applicable" and not (record.reason or "").strip():
        issues.append("not_applicable requires reason")
    if record.disposition == "superseded" and not (record.replacement_ref or "").strip():
        issues.append("superseded requires replacement_ref")
    if record.disposition == "blocked" and not (record.evidence or "").strip():
        issues.append("blocked requires evidence")
    return issues


def completion_claim_asserts_goal_met(claim: dict[str, Any] | None) -> bool:
    """Return whether a completion claim explicitly assesses the output goal as met."""

    if not isinstance(claim, dict):
        return False
    if claim.get("goal_met") is not True:
        return False
    return bool(str(claim.get("goal_assessment") or "").strip())


def build_production_review_snapshot(production: dict[str, Any]) -> dict[str, Any]:
    """Bounded production artifact for reviewer packages (proposal §5.3, §16)."""

    batches = [
        batch
        for batch in (production.get("batches") or [])
        if isinstance(batch, dict)
        and batch.get("evidence_status") != "invalidated_by_reconciliation"
    ]
    live_batch_ids = {
        str(batch.get("id") or "")
        for batch in batches
        if batch.get("id")
    }
    output_evidence = [
        entry
        for entry in (production.get("output_evidence") or [])
        if isinstance(entry, dict)
        and str(entry.get("batch_id") or "") in live_batch_ids
    ]

    snapshot: dict[str, Any] = {
        "production_revision": int(production["revision"]),
        "output_revision": int(production["output_revision"]),
        "batches": batches,
        "dispositions": dict(production.get("dispositions") or {}),
        "output_evidence": output_evidence,
    }
    completion_claim = production.get("completion_claim")
    if isinstance(completion_claim, dict):
        snapshot["completion_claim"] = dict(completion_claim)
    return snapshot


def build_output_traceability(
    plan: Plan,
    production: dict[str, Any],
    *,
    item_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build plan_contracts and evidence_by_item for output review packages.

    Uses live (non-invalidated) batches and evidence only. Shared artifacts may
    appear under multiple item mappings.
    """

    from top_down_planning.domain.plan_tree import is_active_item, walk_active_tree

    snapshot = build_production_review_snapshot(production)
    evidence_by_id = {
        str(entry["id"]): entry
        for entry in snapshot["output_evidence"]
        if entry.get("id")
    }

    evidence_by_item: dict[str, list[dict[str, Any]]] = {}
    for batch in snapshot["batches"]:
        result = batch.get("result") or {}
        for contrib in result.get("contributions") or []:
            if not isinstance(contrib, dict):
                continue
            item_id = str(contrib.get("item_id") or "")
            if not item_id:
                continue
            if item_ids is not None and item_id not in item_ids:
                continue
            for ref in contrib.get("output_refs") or []:
                evidence = evidence_by_id.get(str(ref))
                if evidence is None:
                    continue
                entry = {
                    "evidence_id": str(evidence["id"]),
                    "ref": evidence.get("ref"),
                    "snapshot_ref": evidence.get("snapshot_ref"),
                    "sha256": evidence.get("sha256"),
                }
                evidence_by_item.setdefault(item_id, []).append(entry)

    if item_ids is not None:
        contract_ids = [item_id for item_id in item_ids if item_id in plan.items]
    else:
        contract_ids = [
            item_id
            for item_id, _, _ in walk_active_tree(plan).rows
            if is_active_item(plan.items[item_id])
        ]

    plan_contracts: dict[str, dict[str, Any]] = {
        item_id: build_item_production_contract(plan, item_id)
        for item_id in contract_ids
    }

    return {
        "plan_contracts": plan_contracts,
        "evidence_by_item": {
            item_id: list(entries)
            for item_id, entries in evidence_by_item.items()
            if item_id in plan_contracts
        },
    }


def build_compact_approved_plan(plan: Plan) -> dict[str, Any]:
    """Compact approved-plan representation for producer session manifests."""

    from top_down_planning.domain.plan_tree import walk_active_tree

    items: list[dict[str, Any]] = []
    for item_id, _, _ in walk_active_tree(plan).rows:
        items.append(build_item_production_contract(plan, item_id))
    return {
        "revision": int(plan.revision),
        "scope": plan.scope.to_dict(),
        "boundaries": list(plan.boundaries),
        "constraints": list(plan.constraints),
        "assumptions": list(plan.assumptions),
        "acceptance": list(plan.acceptance),
        "risks": list(plan.risks),
        "items": items,
    }


def build_production_digest_payload(production: dict[str, Any]) -> dict[str, Any]:
    """Live output fields for digest binding (excludes invalidated reconciliation evidence)."""

    snapshot = build_production_review_snapshot(production)
    payload: dict[str, Any] = {
        "batches": snapshot["batches"],
        "dispositions": snapshot["dispositions"],
        "output_evidence": snapshot["output_evidence"],
    }
    if "completion_claim" in snapshot:
        payload["completion_claim"] = snapshot["completion_claim"]
    return payload


def validate_evidence_revision_request(
    plan: Plan,
    *,
    plan_items: list[str],
    dispositions: dict[str, ItemDispositionRecord],
    current_dispositions: dict[str, TerminalDisposition],
    revision_target_ids: set[str],
    outputs: list[OutputEvidence],
    empty_output: bool,
    empty_output_reason: str | None,
    target_label: str = "unresolved whole-output findings",
) -> list[str]:
    """Validate an evidence revision batch for already-terminal items."""

    issues: list[str] = []
    if not plan_items:
        issues.append("plan_items must not be empty")
    if not revision_target_ids:
        issues.append(f"no {target_label} define revision targets")

    seen: set[str] = set()
    for item_id in plan_items:
        if item_id in seen:
            issues.append(f"duplicate plan item in batch: {item_id}")
        seen.add(item_id)

        if item_id not in plan.items:
            issues.append(f"unknown plan item: {item_id}")
            continue
        if item_id not in revision_target_ids:
            issues.append(
                f"item {item_id} is not targeted by {target_label}"
            )
        if item_id not in current_dispositions:
            issues.append(f"item {item_id} has no disposition to revise")
            continue
        if is_applicable_item(plan, item_id, current_dispositions):
            issues.append(
                f"item {item_id} is not terminal; use a normal production apply"
            )

        if item_id not in dispositions:
            issues.append(f"missing disposition for plan item: {item_id}")
            continue
        record = dispositions[item_id]
        if record.disposition != current_dispositions[item_id]:
            issues.append(
                f"evidence revision cannot change disposition for item {item_id}"
            )
        issues.extend(validate_disposition_record(record))

    for item_id, record in dispositions.items():
        if item_id not in seen:
            issues.append(f"disposition provided for item not in plan_items: {item_id}")

    if empty_output and not (empty_output_reason or "").strip():
        issues.append("empty_output requires empty_output_reason")
    if not empty_output and not outputs:
        issues.append("evidence revision requires outputs unless empty_output is true")

    return issues


def validate_batch_request(
    plan: Plan,
    *,
    plan_items: list[str],
    dispositions: dict[str, ItemDispositionRecord],
    ready_item_ids: set[str],
    empty_output: bool,
    empty_output_reason: str | None,
) -> list[str]:
    issues: list[str] = []
    if not plan_items:
        issues.append("plan_items must not be empty")

    seen: set[str] = set()
    for item_id in plan_items:
        if item_id in seen:
            issues.append(f"duplicate plan item in batch: {item_id}")
        seen.add(item_id)

        if item_id not in plan.items:
            issues.append(f"unknown plan item: {item_id}")
            continue

        if plan.items[item_id].kind == "aggregate":
            issues.append(
                f"item {item_id} is an aggregate and cannot be disposed in a production batch"
            )

        if item_id not in ready_item_ids:
            issues.append(f"item {item_id} is not in the ready set")

        if item_id not in dispositions:
            issues.append(f"missing disposition for plan item: {item_id}")

    for item_id, record in dispositions.items():
        if item_id not in seen:
            issues.append(f"disposition provided for item not in plan_items: {item_id}")
            continue
        issues.extend(validate_disposition_record(record))

    if empty_output and not (empty_output_reason or "").strip():
        issues.append("empty_output requires empty_output_reason")

    return issues


def disposition_map_from_records(
    records: dict[str, ItemDispositionRecord],
) -> dict[str, TerminalDisposition]:
    return {item_id: record.disposition for item_id, record in records.items()}


def all_applicable_items_processed(
    plan: Plan,
    dispositions: dict[str, TerminalDisposition],
) -> bool:
    for item_id in plan.items:
        if is_applicable_item(plan, item_id, dispositions):
            return False
    return True


def next_batch_id(existing_batches: list[dict[str, Any]]) -> str:
    index = len(existing_batches) + 1
    return f"batch-{index:02d}"


def _batch_result_from_dict(payload: dict[str, Any]) -> BatchResult:
    outputs = [
        OutputEvidence.from_dict(item)
        for item in (payload.get("outputs") or [])
        if isinstance(item, dict)
    ]
    contributions = [
        Contribution.from_dict(item)
        for item in (payload.get("contributions") or [])
        if isinstance(item, dict)
    ]
    return BatchResult(
        outputs=outputs,
        contributions=contributions,
        dispositions=parse_disposition_records(payload.get("dispositions") or {}),
        summary=str(payload.get("summary") or ""),
        empty_output=bool(payload.get("empty_output")),
        empty_output_reason=_optional_str(payload.get("empty_output_reason")),
        goal_assessment=str(payload.get("goal_assessment") or ""),
    )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def ready_item_ids_for_plan(
    plan: Plan,
    dispositions: dict[str, TerminalDisposition],
    *,
    reviews: list[dict[str, Any]] | None = None,
) -> set[str]:
    is_review_blocked = build_is_review_blocked_fn(
        reviews,
        review_types=OUTPUT_REVIEW_TYPES,
    )
    return set(
        compute_ready_view(
            plan,
            dispositions,
            is_review_blocked=is_review_blocked,
        ).ready_item_ids
    )


def collect_batch_disposition_records(
    production: dict[str, Any],
) -> dict[str, ItemDispositionRecord]:
    records: dict[str, ItemDispositionRecord] = {}
    for batch_payload in production.get("batches") or []:
        if not isinstance(batch_payload, dict):
            continue
        result_payload = batch_payload.get("result")
        if not isinstance(result_payload, dict):
            continue
        try:
            batch_records = parse_disposition_records(result_payload.get("dispositions") or {})
        except ValueError:
            continue
        records.update(batch_records)
    return records


def validate_production_checks(
    plan: Plan,
    production: dict[str, Any],
    *,
    reviews: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Deterministic output-oriented checks available before whole-output review."""

    issues: list[str] = []
    dispositions = dict(production.get("dispositions") or {})
    disposition_records = collect_batch_disposition_records(production)
    is_review_blocked = build_is_review_blocked_fn(
        reviews,
        review_types=OUTPUT_REVIEW_TYPES,
    )

    if not all_applicable_items_processed(plan, dispositions):
        open_items = [
            item_id
            for item_id in plan.items
            if is_applicable_item(plan, item_id, dispositions)
        ]
        issues.append(
            f"{len(open_items)} applicable item(s) remain without terminal disposition"
        )

    deadlock = detect_deadlock(
        plan,
        dispositions,
        is_review_blocked=is_review_blocked,
    )
    if deadlock is not None:
        issues.append(deadlock.explanation)

    for item_id, disposition in dispositions.items():
        record = disposition_records.get(item_id)
        if disposition == "blocked":
            evidence = record.evidence if record is not None else None
            if not (evidence or "").strip():
                issues.append(f"blocked item {item_id} is missing evidence")
        if disposition == "superseded":
            replacement_ref = record.replacement_ref if record is not None else None
            if not (replacement_ref or "").strip():
                issues.append(f"superseded item {item_id} is missing replacement_ref")
        if disposition == "not_applicable":
            reason = record.reason if record is not None else None
            if not (reason or "").strip():
                issues.append(f"not_applicable item {item_id} is missing reason")

    for batch_payload in production.get("batches") or []:
        if not isinstance(batch_payload, dict):
            continue
        result_payload = batch_payload.get("result")
        if not isinstance(result_payload, dict):
            continue
        if bool(result_payload.get("empty_output")) and not (
            str(result_payload.get("empty_output_reason") or "").strip()
        ):
            batch_id = str(batch_payload.get("id") or "unknown")
            issues.append(f"batch {batch_id} declares empty_output without reason")

    completion_claim = production.get("completion_claim")
    if isinstance(completion_claim, dict):
        if not str(completion_claim.get("goal_assessment") or "").strip():
            issues.append("completion claim is missing goal_assessment")
        elif not completion_claim_asserts_goal_met(completion_claim):
            issues.append("completion claim does not explicitly assess output goal as met")

    return issues


def next_amendment_id(existing_requests: list[dict[str, Any]]) -> str:
    index = len(existing_requests) + 1
    return f"amendment-{index:02d}"


def amendment_request_count(production: dict[str, Any]) -> int:
    return len(production.get("amendment_requests") or [])


_DEFAULT_AMENDMENT_MAX_REQUESTS = 3


def amendment_limit(config: dict[str, Any]) -> int:
    amendment_limits = (config.get("limits") or {}).get("amendment") or {}
    return int(
        amendment_limits.get("max_requests", _DEFAULT_AMENDMENT_MAX_REQUESTS)
    )


def has_pending_amendment(production: dict[str, Any]) -> bool:
    pending = production.get("pending_amendment_id")
    return isinstance(pending, str) and bool(pending.strip())


def latest_reconciliation_report(production: dict[str, Any]) -> dict[str, Any] | None:
    reports = production.get("reconciliation_reports") or []
    if not reports:
        return None
    latest = reports[-1]
    if not isinstance(latest, dict):
        return None
    return dict(latest)


@dataclass(frozen=True)
class AcceptedDelivery:
    """Canonical live delivery extracted from a production snapshot."""

    output_evidence: list[dict[str, Any]]
    outputs: list[dict[str, Any]]
    contributions: list[dict[str, Any]]


def live_batch_ids(production: dict[str, Any]) -> set[str]:
    """Batch ids that remain authoritative after reconciliation."""

    ids: set[str] = set()
    for batch in production.get("batches") or []:
        if not isinstance(batch, dict):
            continue
        if batch.get("evidence_status") == "invalidated_by_reconciliation":
            continue
        batch_id = str(batch.get("id") or "").strip()
        if batch_id:
            ids.add(batch_id)
    return ids


def live_output_evidence_entries(production: dict[str, Any]) -> list[dict[str, Any]]:
    """Output-evidence rows tied to live (non-invalidated) production batches."""

    live_ids = live_batch_ids(production)
    return [
        dict(entry)
        for entry in (production.get("output_evidence") or [])
        if isinstance(entry, dict) and str(entry.get("batch_id") or "") in live_ids
    ]


def extract_accepted_delivery(
    production: dict[str, Any],
    *,
    validate_refs: bool = True,
) -> AcceptedDelivery:
    """Extract live evidence, batch outputs, and contributions from production."""

    live_batches = [
        batch
        for batch in (production.get("batches") or [])
        if isinstance(batch, dict)
        and batch.get("evidence_status") != "invalidated_by_reconciliation"
    ]
    live_ids = live_batch_ids(production)
    output_evidence = [
        dict(entry)
        for entry in (production.get("output_evidence") or [])
        if isinstance(entry, dict) and str(entry.get("batch_id") or "") in live_ids
    ]
    evidence_ids = {
        str(entry.get("id") or "")
        for entry in output_evidence
        if entry.get("id")
    }
    outputs: list[dict[str, Any]] = []
    contributions: list[dict[str, Any]] = []
    for batch in live_batches:
        result = batch.get("result")
        if not isinstance(result, dict):
            continue
        for item in result.get("outputs") or []:
            if isinstance(item, dict):
                outputs.append(dict(item))
        for item in result.get("contributions") or []:
            if not isinstance(item, dict):
                continue
            contrib = dict(item)
            if validate_refs:
                for ref in contrib.get("output_refs") or []:
                    ref_s = str(ref)
                    if ref_s and ref_s not in evidence_ids:
                        raise ValueError(
                            "contribution output_ref "
                            f"{ref_s!r} not in live output_evidence"
                        )
            contributions.append(contrib)
    return AcceptedDelivery(
        output_evidence=output_evidence,
        outputs=outputs,
        contributions=contributions,
    )
