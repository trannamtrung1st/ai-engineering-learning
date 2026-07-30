"""Agent production snapshot/apply/check service (proposal §10, §17.3)."""

from __future__ import annotations

from typing import Any

from top_down_planning.agent_tool.config import planning_limits_from_config
from top_down_planning.agent_tool.errors import RequestError
from top_down_planning.agent_tool.views import build_ready_view, build_tree_view
from top_down_planning.domain.dispositions import DispositionMap
from top_down_planning.domain.production import (
    BatchResult,
    Contribution,
    ItemDispositionRecord,
    OutputEvidence,
    ProductionBatch,
    all_applicable_items_processed,
    disposition_map_from_records,
    is_production_phase,
    next_batch_id,
    parse_disposition_records,
    ready_item_ids_for_plan,
    validate_batch_request,
)
from top_down_planning.domain.readiness import detect_deadlock, is_applicable_item
from top_down_planning.domain.reviews import find_whole_plan_approval
from top_down_planning.persistence.errors import StoreRevisionConflictError
from top_down_planning.persistence.interface import RunStore


class ProductionAgentService:
    """Structured production interaction for agents against a persisted run."""

    def __init__(self, store: RunStore, run_id: str) -> None:
        self._store = store
        self._run_id = run_id

    def snapshot(self, *, view: str = "ready") -> dict[str, Any]:
        plan = self._store.load_plan_model(self._run_id)
        production = self._store.load_production(self._run_id)
        dispositions = self._dispositions(production)

        if view == "tree":
            limits = planning_limits_from_config(self._store.load_resolved_config(self._run_id))
            payload = build_tree_view(plan, limits=limits)
        elif view == "ready":
            payload = build_ready_view(plan, dispositions)
        else:
            raise RequestError(f"unsupported production snapshot view: {view!r}")

        payload["ok"] = True
        payload["production_revision"] = int(production.get("revision") or 0)
        payload["output_revision"] = int(production.get("output_revision") or 0)
        payload["batch_count"] = len(production.get("batches") or [])
        payload["dispositions"] = dict(dispositions)
        return payload

    def apply(
        self,
        request: dict[str, Any],
        *,
        role: str,
    ) -> dict[str, Any]:
        normalized_role = str(role).strip()
        if normalized_role != "producer":
            raise RequestError("only the producer role may record production batches")

        run = self._store.load_run(self._run_id)
        phase = str(run.get("phase") or "")
        if not is_production_phase(phase):
            raise RequestError(
                f"production apply is only allowed in production phase (current: {phase!r})"
            )

        plan = self._store.load_plan_model(self._run_id)
        if find_whole_plan_approval(self._store.list_reviews(self._run_id), plan.revision) is None:
            raise RequestError(
                "production apply requires an approved whole-plan review "
                "for the current plan revision"
            )

        if "plan_items" not in request:
            raise RequestError("apply requires plan_items")

        plan_items = request["plan_items"]
        if not isinstance(plan_items, list) or not plan_items:
            raise RequestError("plan_items must be a non-empty list")

        production = self._store.load_production(self._run_id)
        current_dispositions = self._dispositions(production)
        ready_ids = ready_item_ids_for_plan(plan, current_dispositions)

        already_terminal = [
            item_id
            for item_id in (str(item_id) for item_id in plan_items)
            if not is_applicable_item(plan, item_id, current_dispositions)
        ]
        if already_terminal:
            joined = ", ".join(already_terminal)
            raise RequestError(f"plan_items already have terminal disposition: {joined}")

        disposition_records = parse_disposition_records(request.get("dispositions") or {})
        empty_output = bool(request.get("empty_output"))
        empty_output_reason = request.get("empty_output_reason")
        if empty_output_reason is not None:
            empty_output_reason = str(empty_output_reason).strip() or None

        issues = validate_batch_request(
            plan,
            plan_items=[str(item_id) for item_id in plan_items],
            dispositions=disposition_records,
            ready_item_ids=ready_ids,
            empty_output=empty_output,
            empty_output_reason=empty_output_reason,
        )
        if issues:
            raise RequestError("; ".join(issues))

        outputs = _parse_outputs(request.get("outputs") or [])
        contributions = _parse_contributions(request.get("contributions") or [])
        _validate_contributions(outputs, contributions, plan_items)

        batch_id = str(request.get("batch_id") or next_batch_id(production.get("batches") or []))
        result = BatchResult(
            outputs=outputs,
            contributions=contributions,
            dispositions=disposition_records,
            summary=str(request.get("summary") or ""),
            empty_output=empty_output,
            empty_output_reason=empty_output_reason,
            goal_assessment=str(request.get("goal_assessment") or ""),
        )
        batch = ProductionBatch(
            id=batch_id,
            plan_items=[str(item_id) for item_id in plan_items],
            status="completed",
            agent_turns=int(request.get("agent_turns") or 1),
            intent=_optional_text(request.get("intent")),
            result=result,
        )

        expected_revision = int(production["revision"])
        updated = self._merge_batch(production, batch, disposition_records, outputs)
        try:
            next_revision = self._store.save_production(
                self._run_id,
                updated,
                expected_revision,
            )
        except StoreRevisionConflictError as exc:
            raise RequestError(str(exc)) from exc

        self._store.append_event(
            self._run_id,
            {
                "type": "production_batch_recorded",
                "run_id": self._run_id,
                "batch_id": batch_id,
                "plan_items": batch.plan_items,
                "production_revision": next_revision,
                "output_revision": updated["output_revision"],
            },
        )

        merged_dispositions = self._dispositions(updated)
        return {
            "ok": True,
            "batch_id": batch_id,
            "production_revision": next_revision,
            "output_revision": updated["output_revision"],
            "dispositions": dict(merged_dispositions),
            "all_applicable_items_processed": all_applicable_items_processed(
                plan,
                merged_dispositions,
            ),
        }

    def check(self) -> dict[str, Any]:
        plan = self._store.load_plan_model(self._run_id)
        production = self._store.load_production(self._run_id)
        dispositions = self._dispositions(production)
        deadlock = detect_deadlock(plan, dispositions)
        return {
            "ok": deadlock is None,
            "revision": plan.revision,
            "production_revision": int(production.get("revision") or 0),
            "all_applicable_items_processed": all_applicable_items_processed(
                plan,
                dispositions,
            ),
            "deadlock": deadlock.to_dict() if deadlock is not None else None,
        }

    def _merge_batch(
        self,
        production: dict[str, Any],
        batch: ProductionBatch,
        disposition_records: dict[str, ItemDispositionRecord],
        outputs: list[OutputEvidence],
    ) -> dict[str, Any]:
        expected_revision = int(production["revision"])
        updated = dict(production)
        updated["revision"] = expected_revision + 1

        batches = list(updated.get("batches") or [])
        batches.append(batch.to_dict())
        updated["batches"] = batches

        flat_dispositions = dict(updated.get("dispositions") or {})
        flat_dispositions.update(disposition_map_from_records(disposition_records))
        updated["dispositions"] = flat_dispositions

        evidence = list(updated.get("output_evidence") or [])
        for output in outputs:
            evidence.append(
                OutputEvidence(
                    id=output.id,
                    type=output.type,
                    ref=output.ref,
                    batch_id=batch.id,
                ).to_dict()
            )
        updated["output_evidence"] = evidence
        updated["output_revision"] = int(updated.get("output_revision") or 0) + 1
        return updated

    def _dispositions(self, production: dict[str, Any]) -> DispositionMap:
        raw = production.get("dispositions") or {}
        return dict(raw)


def _parse_outputs(raw_outputs: Any) -> list[OutputEvidence]:
    if not isinstance(raw_outputs, list):
        raise RequestError("outputs must be a list")
    outputs: list[OutputEvidence] = []
    seen_ids: set[str] = set()
    for item in raw_outputs:
        if not isinstance(item, dict):
            raise RequestError("each output must be an object")
        output = OutputEvidence.from_dict(item)
        if output.id in seen_ids:
            raise RequestError(f"duplicate output id: {output.id}")
        seen_ids.add(output.id)
        outputs.append(output)
    return outputs


def _parse_contributions(raw_contributions: Any) -> list[Contribution]:
    if not isinstance(raw_contributions, list):
        raise RequestError("contributions must be a list")
    contributions: list[Contribution] = []
    for item in raw_contributions:
        if not isinstance(item, dict):
            raise RequestError("each contribution must be an object")
        contributions.append(Contribution.from_dict(item))
    return contributions


def _validate_contributions(
    outputs: list[OutputEvidence],
    contributions: list[Contribution],
    plan_items: list[str],
) -> None:
    output_ids = {output.id for output in outputs}
    plan_item_set = set(plan_items)
    for contribution in contributions:
        if contribution.item_id not in plan_item_set:
            raise RequestError(
                f"contribution item_id {contribution.item_id!r} is not in plan_items"
            )
        for output_ref in contribution.output_refs:
            if output_ref not in output_ids:
                raise RequestError(
                    f"contribution references unknown output id: {output_ref}"
                )


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
