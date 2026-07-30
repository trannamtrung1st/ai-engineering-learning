"""Agent production snapshot/apply/check service (proposal §10, §17.3)."""

from __future__ import annotations

from typing import Any

from top_down_planning.agent_tool.config import planning_limits_from_config
from top_down_planning.agent_tool.errors import RequestError, RevisionConflictError
from top_down_planning.agent_tool.roles import assert_production_mutations_allowed
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
    next_amendment_id,
    next_batch_id,
    parse_disposition_records,
    ready_item_ids_for_plan,
    validate_batch_request,
    validate_production_checks,
)
from top_down_planning.domain.readiness import is_applicable_item
from top_down_planning.domain.reviews import find_whole_plan_approval
from top_down_planning.persistence.errors import StoreRevisionConflictError
from top_down_planning.persistence.interface import RunStore

_PRODUCTION_SNAPSHOT_ACTION = (
    "Call `tdp agent production snapshot` and retry with the current revision."
)


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
        payload["production_revision"] = int(production["revision"])
        payload["output_revision"] = int(production["output_revision"])
        payload["batch_count"] = len(production["batches"])
        payload["dispositions"] = dict(dispositions)
        return payload

    def apply(
        self,
        request: dict[str, Any],
        *,
        role: str,
    ) -> dict[str, Any]:
        normalized_role = str(role).strip()
        assert_production_mutations_allowed(normalized_role)

        plan = self._store.load_plan_model(self._run_id)
        self._require_production_context(plan)

        if "production_revision" not in request:
            raise RequestError("apply requires production_revision")
        if "plan_items" not in request:
            raise RequestError("apply requires plan_items")

        plan_items = request["plan_items"]
        if not isinstance(plan_items, list) or not plan_items:
            raise RequestError("plan_items must be a non-empty list")

        production = self._store.load_production(self._run_id)
        expected_revision = int(request["production_revision"])
        current_revision = int(production["revision"])
        if expected_revision != current_revision:
            raise RevisionConflictError(
                (
                    f"production revision conflict: expected {expected_revision}, "
                    f"current {current_revision}"
                ),
                expected=expected_revision,
                actual=current_revision,
                action=_PRODUCTION_SNAPSHOT_ACTION,
            )

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

        updated = self._merge_batch(production, batch, disposition_records, outputs)
        try:
            next_revision = self._store.save_production(
                self._run_id,
                updated,
                current_revision,
            )
        except StoreRevisionConflictError as exc:
            raise RevisionConflictError(
                str(exc),
                expected=exc.expected,
                actual=exc.actual,
                action=_PRODUCTION_SNAPSHOT_ACTION,
            ) from exc

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
        issues = validate_production_checks(plan, production)
        return {
            "ok": not issues,
            "revision": plan.revision,
            "production_revision": int(production["revision"]),
            "output_revision": int(production["output_revision"]),
            "all_applicable_items_processed": all_applicable_items_processed(
                plan,
                dispositions,
            ),
            "issues": issues,
        }

    def request_amendment(
        self,
        request: dict[str, Any],
        *,
        role: str,
    ) -> dict[str, Any]:
        normalized_role = str(role).strip()
        assert_production_mutations_allowed(normalized_role)

        plan = self._store.load_plan_model(self._run_id)
        self._require_production_context(plan)

        evidence = _required_text(request.get("evidence"), field="evidence")
        affected_refs = _required_affected_refs(request.get("affected_refs"))
        summary = str(request.get("summary") or "").strip()

        production = self._store.load_production(self._run_id)
        expected_revision = int(production["revision"])
        requests = list(production.get("amendment_requests") or [])
        amendment_id = str(request.get("id") or next_amendment_id(requests))
        amendment = {
            "id": amendment_id,
            "status": "pending",
            "evidence": evidence,
            "affected_refs": affected_refs,
            "summary": summary,
            "plan_revision": plan.revision,
            "output_revision": int(production["output_revision"]),
        }

        updated = dict(production)
        updated["revision"] = expected_revision + 1
        updated["amendment_requests"] = [*requests, amendment]
        updated["pending_amendment_id"] = amendment_id

        try:
            next_revision = self._store.save_production(
                self._run_id,
                updated,
                expected_revision,
            )
        except StoreRevisionConflictError as exc:
            raise RevisionConflictError(
                str(exc),
                expected=exc.expected,
                actual=exc.actual,
                action=_PRODUCTION_SNAPSHOT_ACTION,
            ) from exc

        self._store.append_event(
            self._run_id,
            {
                "type": "production_amendment_requested",
                "run_id": self._run_id,
                "amendment_id": amendment_id,
                "affected_refs": affected_refs,
                "production_revision": next_revision,
            },
        )

        return {
            "ok": True,
            "amendment_id": amendment_id,
            "status": "pending",
            "production_revision": next_revision,
            "signal": "amendment_requested",
        }

    def submit_completion(
        self,
        request: dict[str, Any],
        *,
        role: str,
    ) -> dict[str, Any]:
        normalized_role = str(role).strip()
        assert_production_mutations_allowed(normalized_role)

        goal_assessment = _required_text(
            request.get("goal_assessment"),
            field="goal_assessment",
        )
        summary = str(request.get("summary") or "").strip()

        plan = self._store.load_plan_model(self._run_id)
        self._require_production_context(plan)
        production = self._store.load_production(self._run_id)
        dispositions = self._dispositions(production)
        if not all_applicable_items_processed(plan, dispositions):
            raise RequestError(
                "submit-completion requires every applicable item to have a "
                "terminal disposition or derived satisfaction"
            )

        expected_revision = int(production["revision"])
        claim = {
            "goal_assessment": goal_assessment,
            "summary": summary,
            "plan_revision": plan.revision,
            "output_revision": int(production["output_revision"]),
            "all_applicable_items_processed": True,
        }

        updated = dict(production)
        updated["revision"] = expected_revision + 1
        updated["completion_claim"] = claim

        try:
            next_revision = self._store.save_production(
                self._run_id,
                updated,
                expected_revision,
            )
        except StoreRevisionConflictError as exc:
            raise RevisionConflictError(
                str(exc),
                expected=exc.expected,
                actual=exc.actual,
                action=_PRODUCTION_SNAPSHOT_ACTION,
            ) from exc

        self._store.append_event(
            self._run_id,
            {
                "type": "production_completion_claimed",
                "run_id": self._run_id,
                "production_revision": next_revision,
                "output_revision": claim["output_revision"],
            },
        )

        run = self._store.load_run(self._run_id)
        return {
            "ok": True,
            "production_revision": next_revision,
            "completion_claim": claim,
            "run_outcome": run.get("outcome"),
        }

    def report_blocked(
        self,
        request: dict[str, Any],
        *,
        role: str,
    ) -> dict[str, Any]:
        normalized_role = str(role).strip()
        assert_production_mutations_allowed(normalized_role)

        evidence = _required_text(request.get("evidence"), field="evidence")
        affected_refs = _parse_affected_refs(request.get("affected_refs"))
        summary = str(request.get("summary") or "").strip()

        plan = self._store.load_plan_model(self._run_id)
        self._require_production_context(plan)
        production = self._store.load_production(self._run_id)
        expected_revision = int(production["revision"])
        report = {
            "evidence": evidence,
            "affected_refs": affected_refs,
            "summary": summary,
            "plan_revision": plan.revision,
            "output_revision": int(production["output_revision"]),
        }

        updated = dict(production)
        updated["revision"] = expected_revision + 1
        updated["blocker_report"] = report

        try:
            next_revision = self._store.save_production(
                self._run_id,
                updated,
                expected_revision,
            )
        except StoreRevisionConflictError as exc:
            raise RevisionConflictError(
                str(exc),
                expected=exc.expected,
                actual=exc.actual,
                action=_PRODUCTION_SNAPSHOT_ACTION,
            ) from exc

        self._store.append_event(
            self._run_id,
            {
                "type": "production_blocked_reported",
                "run_id": self._run_id,
                "affected_refs": affected_refs,
                "production_revision": next_revision,
            },
        )

        run = self._store.load_run(self._run_id)
        return {
            "ok": True,
            "production_revision": next_revision,
            "blocker_report": report,
            "run_outcome": run.get("outcome"),
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

    def _require_production_context(self, plan) -> None:
        run = self._store.load_run(self._run_id)
        phase = str(run.get("phase") or "")
        if not is_production_phase(phase):
            raise RequestError(
                f"production commands are only allowed in production phase (current: {phase!r})"
            )
        if find_whole_plan_approval(self._store.list_reviews(self._run_id), plan.revision) is None:
            raise RequestError(
                "production commands require an approved whole-plan review "
                "for the current plan revision"
            )

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


def _parse_affected_refs(raw_refs: Any) -> list[str]:
    if raw_refs is None:
        return []
    if not isinstance(raw_refs, list):
        raise RequestError("affected_refs must be a list")
    return [str(item_id) for item_id in raw_refs]


def _required_affected_refs(raw_refs: Any) -> list[str]:
    affected_refs = _parse_affected_refs(raw_refs)
    if not affected_refs:
        raise RequestError("affected_refs must be a non-empty list")
    return affected_refs


def _required_text(value: Any, *, field: str) -> str:
    if value is None:
        raise RequestError(f"{field} is required")
    text = str(value).strip()
    if not text:
        raise RequestError(f"{field} is required")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
