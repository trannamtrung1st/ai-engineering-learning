"""Production batch, disposition, and output evidence models (proposal §10)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from top_down_planning.domain.dispositions import TERMINAL_DISPOSITIONS, TerminalDisposition
from top_down_planning.domain.models import Plan
from top_down_planning.domain.readiness import compute_ready_view, detect_deadlock, is_applicable_item

PRODUCTION_PHASE = "production"


@dataclass(frozen=True)
class OutputEvidence:
    id: str
    type: str
    ref: str
    batch_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "ref": self.ref,
        }
        if self.batch_id is not None:
            payload["batch_id"] = self.batch_id
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> OutputEvidence:
        return cls(
            id=str(payload["id"]),
            type=str(payload.get("type") or "artifact"),
            ref=str(payload.get("ref") or ""),
            batch_id=payload.get("batch_id"),
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
) -> set[str]:
    return set(compute_ready_view(plan, dispositions).ready_item_ids)


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
) -> list[str]:
    """Deterministic output-oriented checks available before whole-output review."""

    issues: list[str] = []
    dispositions = dict(production.get("dispositions") or {})
    disposition_records = collect_batch_disposition_records(production)

    if not all_applicable_items_processed(plan, dispositions):
        open_items = [
            item_id
            for item_id in plan.items
            if is_applicable_item(plan, item_id, dispositions)
        ]
        issues.append(
            f"{len(open_items)} applicable item(s) remain without terminal disposition"
        )

    deadlock = detect_deadlock(plan, dispositions)
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

    return issues


def next_amendment_id(existing_requests: list[dict[str, Any]]) -> str:
    index = len(existing_requests) + 1
    return f"amendment-{index:02d}"
