"""Agent production snapshot/apply/check service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pathlib import Path

from top_down_planning.agent_tool.artifacts import capture_output_artifact
from top_down_planning.agent_tool.authorization import authorize_mutation
from top_down_planning.agent_tool.config import planning_limits_from_config
from top_down_planning.agent_tool.errors import (
    ProductionContextMutationError,
    ProductionEvidenceIncompleteError,
    RequestError,
    RevisionConflictError,
)
from top_down_planning.agent_tool.request_audit import (
    AgentRequestContext,
    apply_request_audit_fields,
)
from top_down_planning.agent_tool.request_schema import validate_agent_request
from top_down_planning.agent_tool.views import (
    build_hierarchy_snapshot,
    build_ready_view,
    validation_issues,
    validation_warnings,
)
from top_down_planning.config import (
    InvalidProductionEvidenceError,
    UnauthorizedContextMutationError,
    format_apply_context_mutation_message,
    format_apply_snapshot_evidence_message,
    recompute_context_snapshot_binding,
    split_unauthorized_snapshot_paths,
    validate_run_production_snapshot_drift,
)
from top_down_planning.workspace import run_workspace
from top_down_planning.domain.reviews import (
    OUTPUT_REVIEW_TYPES,
    ReviewLoop,
    blocking_focused_findings_for_items,
    find_whole_plan_approval,
    focused_output_revision_target_ids,
    whole_output_revision_target_ids,
)
from top_down_planning.domain.production import (
    BatchResult,
    Contribution,
    ItemDispositionRecord,
    OutputEvidence,
    ProductionBatch,
    PRODUCTION_PHASE,
    WHOLE_OUTPUT_REVIEW_PHASE,
    all_applicable_items_processed,
    allows_production_mutations,
    disposition_map_from_records,
    has_pending_amendment,
    next_amendment_id,
    amendment_limit,
    amendment_request_count,
    next_batch_id,
    parse_disposition_records,
    ready_item_ids_for_plan,
    validate_batch_request,
    validate_evidence_revision_request,
    validate_production_checks,
)
from top_down_planning.domain.readiness import is_applicable_item
from top_down_planning.domain.validators import validate_plan
from core_tools.persistence import StoreRevisionConflictError
from top_down_planning.persistence.commit import CommitSpec
from top_down_planning.persistence.interface import RunStore

_PRODUCTION_SNAPSHOT_ACTION = (
    "Call `tdp agent production snapshot` and retry with the current revision."
)


def _disposition_summary(dispositions: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in dispositions.values():
        if isinstance(value, str):
            key = value
        elif isinstance(value, dict):
            key = str(value.get("disposition") or "unknown")
        else:
            key = "unknown"
        counts[key] = counts.get(key, 0) + 1
    return counts


class ProductionAgentService:
    """Structured production interaction for agents against a persisted run."""

    def __init__(self, store: RunStore, run_id: str) -> None:
        self._store = store
        self._run_id = run_id

    def snapshot(self, *, view: str = "ready") -> dict[str, Any]:
        plan = self._store.load_plan_model(self._run_id)
        production = self._store.load_production(self._run_id)
        dispositions = self._dispositions(production)
        reviews = self._store.list_reviews(self._run_id)

        limits = planning_limits_from_config(self._store.load_resolved_config(self._run_id))
        validation = validate_plan(
            plan,
            limits=limits,
            dispositions=dispositions,
            reviews=reviews,
            review_types=OUTPUT_REVIEW_TYPES,
        )

        if view == "tree":
            payload = build_hierarchy_snapshot(plan, limits=limits, view="tree")
        elif view == "ready":
            payload = build_ready_view(
                plan,
                dispositions,
                reviews=reviews,
                review_types=OUTPUT_REVIEW_TYPES,
            )
            payload["disposition_summary"] = _disposition_summary(dispositions)
        elif view == "dispositions":
            payload = {
                "view": "dispositions",
                "dispositions": dict(dispositions),
            }
        else:
            raise RequestError(f"unsupported production snapshot view: {view!r}")

        payload["ok"] = validation.ok
        payload["issues"] = validation_issues(validation)
        payload["warnings"] = validation_warnings(validation)
        payload["production_revision"] = int(production["revision"])
        payload["output_revision"] = int(production["output_revision"])
        payload["batch_count"] = len(production["batches"])
        return payload

    def apply(
        self,
        request: dict[str, Any],
        *,
        capability_token: str | None = None,
        request_audit: AgentRequestContext | None = None,
    ) -> dict[str, Any]:
        authorize_mutation(
            self._store,
            self._run_id,
            operation="production_apply",
            capability_token=capability_token,
        )
        validate_agent_request("production_apply", request)

        plan = self._store.load_plan_model(self._run_id)
        self._require_production_context(plan)

        production = self._store.load_production(self._run_id)
        if has_pending_amendment(production):
            raise RequestError(
                "production batches are paused while a plan amendment is pending"
            )

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
        reviews = self._store.list_reviews(self._run_id)
        evidence_revision = bool(request.get("evidence_revision"))
        plan_item_ids = [str(item_id) for item_id in plan_items]
        if not evidence_revision:
            blocked = blocking_focused_findings_for_items(
                reviews,
                "focused_output",
                plan_item_ids,
            )
            if blocked:
                joined = ", ".join(blocked)
                raise RequestError(
                    f"production blocked by unresolved focused output findings: {joined}"
                )

        disposition_records = parse_disposition_records(request.get("dispositions") or {})
        empty_output = bool(request.get("empty_output"))
        empty_output_reason = request.get("empty_output_reason")
        if empty_output_reason is not None:
            empty_output_reason = str(empty_output_reason).strip() or None
        run = self._store.load_run(self._run_id)
        workspace = run_workspace(run)
        output_specs = _parse_output_specs(
            self._store,
            self._run_id,
            request.get("outputs") or [],
            workspace=workspace,
        )
        provisional_outputs = _provisional_outputs_from_specs(output_specs)
        contributions = _parse_contributions(request.get("contributions") or [])
        _validate_contributions(provisional_outputs, contributions, plan_item_ids)

        if evidence_revision:
            run = self._store.load_run(self._run_id)
            phase = str(run.get("phase") or "")
            focused_loop_id = request.get("focused_review_loop_id")
            if focused_loop_id is not None:
                focused_loop_id = str(focused_loop_id).strip() or None
            if phase == WHOLE_OUTPUT_REVIEW_PHASE:
                revision_targets = whole_output_revision_target_ids(reviews)
                target_label = "open required whole-output findings"
            elif phase == PRODUCTION_PHASE:
                revision_targets = focused_output_revision_target_ids(
                    reviews,
                    loop_id=focused_loop_id,
                )
                target_label = "open required focused-output findings"
                if not revision_targets:
                    raise RequestError(
                        "evidence_revision during production requires an active "
                        "focused_output review with status changes_requested"
                    )
                if focused_loop_id is None:
                    raise RequestError(
                        "evidence_revision during production requires focused_review_loop_id"
                    )
                loop = next(
                    (
                        ReviewLoop.from_dict(payload)
                        for payload in reviews
                        if payload.get("id") == focused_loop_id
                    ),
                    None,
                )
                if loop is None or loop.type != "focused_output":
                    raise RequestError(
                        f"focused review loop not found: {focused_loop_id}"
                    )
                output_revision = int(production["output_revision"])
                if loop.target_revision != output_revision:
                    raise RequestError(
                        "focused evidence revision target_revision "
                        f"{loop.target_revision} does not match current output revision "
                        f"{output_revision}"
                    )
            else:
                raise RequestError(
                    "evidence_revision apply is only allowed during production "
                    "(focused_output) or whole_output_review"
                )
            issues = validate_evidence_revision_request(
                plan,
                plan_items=plan_item_ids,
                dispositions=disposition_records,
                current_dispositions=current_dispositions,
                revision_target_ids=revision_targets,
                outputs=provisional_outputs,
                empty_output=empty_output,
                empty_output_reason=empty_output_reason,
                target_label=target_label,
            )
            if issues:
                raise RequestError("; ".join(issues))
        else:
            ready_ids = ready_item_ids_for_plan(
                plan,
                current_dispositions,
                reviews=reviews,
            )
            already_terminal = [
                item_id
                for item_id in plan_item_ids
                if not is_applicable_item(plan, item_id, current_dispositions)
            ]
            if already_terminal:
                joined = ", ".join(already_terminal)
                raise RequestError(f"plan_items already have terminal disposition: {joined}")

            issues = validate_batch_request(
                plan,
                plan_items=plan_item_ids,
                dispositions=disposition_records,
                ready_item_ids=ready_ids,
                empty_output=empty_output,
                empty_output_reason=empty_output_reason,
            )
            if issues:
                raise RequestError("; ".join(issues))

        batch_id = next_batch_id(production.get("batches") or [])
        run = self._store.load_run(self._run_id)
        production_loop = run.get("production_loop") or {}
        batch_agent_turns = int(production_loop.get("current_batch_agent_turns") or 0)
        agent_turns = batch_agent_turns if batch_agent_turns > 0 else 1
        batch = ProductionBatch(
            id=batch_id,
            plan_items=[str(item_id) for item_id in plan_items],
            status="completed",
            agent_turns=agent_turns,
            intent=_optional_text(request.get("intent")),
            result=BatchResult(
                outputs=[],
                contributions=contributions,
                dispositions=disposition_records,
                summary=str(request.get("summary") or ""),
                empty_output=empty_output,
                empty_output_reason=empty_output_reason,
                goal_assessment=str(request.get("goal_assessment") or ""),
            ),
        )

        candidate = _build_apply_candidate(
            production,
            batch,
            disposition_records,
            output_specs,
        )
        if evidence_revision:
            candidate["completion_claim"] = None
        self._validate_apply_snapshot_evidence(candidate, current_revision=current_revision)
        outputs = _capture_output_specs(self._store, self._run_id, workspace, output_specs)
        batch = ProductionBatch(
            id=batch_id,
            plan_items=batch.plan_items,
            status=batch.status,
            agent_turns=batch.agent_turns,
            intent=batch.intent,
            result=BatchResult(
                outputs=outputs,
                contributions=contributions,
                dispositions=disposition_records,
                summary=str(request.get("summary") or ""),
                empty_output=empty_output,
                empty_output_reason=empty_output_reason,
                goal_assessment=str(request.get("goal_assessment") or ""),
            ),
        )

        updated = self._merge_batch(production, batch, disposition_records, outputs)
        if evidence_revision:
            updated["completion_claim"] = None
        try:
            self._store.commit(
                self._run_id,
                CommitSpec(
                    production=updated,
                    production_expected_revision=current_revision,
                    events=[
                        apply_request_audit_fields(
                            {
                                "type": "production_batch_recorded",
                                "run_id": self._run_id,
                                "batch_id": batch_id,
                                "plan_items": batch.plan_items,
                                "production_revision": updated["revision"],
                                "output_revision": updated["output_revision"],
                            },
                            request_audit,
                        )
                    ],
                ),
            )
            next_revision = int(updated["revision"])
        except StoreRevisionConflictError as exc:
            raise RevisionConflictError(
                str(exc),
                expected=exc.expected,
                actual=exc.actual,
                action=_PRODUCTION_SNAPSHOT_ACTION,
            ) from exc

        merged_dispositions = self._dispositions(updated)
        changed_dispositions = disposition_map_from_records(disposition_records)
        return {
            "ok": True,
            "batch_id": batch_id,
            "production_revision": next_revision,
            "output_revision": updated["output_revision"],
            "changed_disposition_count": len(changed_dispositions),
            "changed_dispositions": dict(changed_dispositions),
            "all_applicable_items_processed": all_applicable_items_processed(
                plan,
                merged_dispositions,
            ),
        }

    def check(self) -> dict[str, Any]:
        plan = self._store.load_plan_model(self._run_id)
        production = self._store.load_production(self._run_id)
        dispositions = self._dispositions(production)
        reviews = self._store.list_reviews(self._run_id)
        issues = validate_production_checks(plan, production, reviews=reviews)
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
        capability_token: str | None = None,
        request_audit: AgentRequestContext | None = None,
    ) -> dict[str, Any]:
        authorize_mutation(
            self._store,
            self._run_id,
            operation="production_request_amendment",
            capability_token=capability_token,
        )
        validate_agent_request("production_request_amendment", request)

        plan = self._store.load_plan_model(self._run_id)
        self._require_production_context(plan)

        run = self._store.load_run(self._run_id)
        phase = str(run.get("phase") or "")
        if phase == WHOLE_OUTPUT_REVIEW_PHASE:
            raise RequestError(
                "plan amendment is not allowed during whole-output review; "
                "address reviewer findings via evidence revision or report blocked"
            )

        evidence = _required_text(request.get("evidence"), field="evidence")
        affected_refs = _required_affected_refs(request.get("affected_refs"))
        summary = str(request.get("summary") or "").strip()

        production = self._store.load_production(self._run_id)
        if has_pending_amendment(production):
            raise RequestError("an amendment request is already pending")

        config = self._store.load_resolved_config(self._run_id)
        max_requests = amendment_limit(config)
        requests = list(production.get("amendment_requests") or [])
        if amendment_request_count(production) >= max_requests:
            raise RequestError(
                f"plan amendment limit exceeded (max_requests={max_requests})"
            )

        expected_revision = int(production["revision"])
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
            self._store.commit(
                self._run_id,
                CommitSpec(
                    production=updated,
                    production_expected_revision=expected_revision,
                    events=[
                        apply_request_audit_fields(
                            {
                                "type": "production_amendment_requested",
                                "run_id": self._run_id,
                                "amendment_id": amendment_id,
                                "affected_refs": affected_refs,
                                "production_revision": updated["revision"],
                            },
                            request_audit,
                        )
                    ],
                ),
            )
            next_revision = int(updated["revision"])
        except StoreRevisionConflictError as exc:
            raise RevisionConflictError(
                str(exc),
                expected=exc.expected,
                actual=exc.actual,
                action=_PRODUCTION_SNAPSHOT_ACTION,
            ) from exc

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
        capability_token: str | None = None,
        request_audit: AgentRequestContext | None = None,
    ) -> dict[str, Any]:
        authorize_mutation(
            self._store,
            self._run_id,
            operation="production_submit_completion",
            capability_token=capability_token,
        )
        validate_agent_request("production_submit_completion", request)

        goal_assessment = _required_text(
            request.get("goal_assessment"),
            field="goal_assessment",
        )
        summary = str(request.get("summary") or "").strip()

        plan = self._store.load_plan_model(self._run_id)
        self._require_production_context(plan)
        production = self._store.load_production(self._run_id)
        if has_pending_amendment(production):
            raise RequestError(
                "production is paused while a plan amendment is pending"
            )
        dispositions = self._dispositions(production)
        if not all_applicable_items_processed(plan, dispositions):
            raise RequestError(
                "submit-completion requires every applicable item to have a "
                "terminal disposition or derived satisfaction"
            )

        blocked = blocking_focused_findings_for_items(
            self._store.list_reviews(self._run_id),
            "focused_output",
            list(plan.items.keys()),
        )
        if blocked:
            joined = ", ".join(blocked)
            raise RequestError(
                f"production blocked by unresolved focused output findings: {joined}"
            )

        expected_revision = int(production["revision"])
        claim = {
            "goal_assessment": goal_assessment,
            "goal_met": True,
            "summary": summary,
            "plan_revision": plan.revision,
            "output_revision": int(production["output_revision"]),
            "all_applicable_items_processed": True,
        }

        updated = dict(production)
        updated["revision"] = expected_revision + 1
        updated["completion_claim"] = claim

        try:
            self._store.commit(
                self._run_id,
                CommitSpec(
                    production=updated,
                    production_expected_revision=expected_revision,
                    events=[
                        apply_request_audit_fields(
                            {
                                "type": "production_completion_claimed",
                                "run_id": self._run_id,
                                "production_revision": updated["revision"],
                                "output_revision": claim["output_revision"],
                            },
                            request_audit,
                        )
                    ],
                ),
            )
            next_revision = int(updated["revision"])
        except StoreRevisionConflictError as exc:
            raise RevisionConflictError(
                str(exc),
                expected=exc.expected,
                actual=exc.actual,
                action=_PRODUCTION_SNAPSHOT_ACTION,
            ) from exc

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
        capability_token: str | None = None,
        request_audit: AgentRequestContext | None = None,
    ) -> dict[str, Any]:
        authorize_mutation(
            self._store,
            self._run_id,
            operation="production_report_blocked",
            capability_token=capability_token,
        )
        validate_agent_request("production_report_blocked", request)

        evidence = _required_text(request.get("evidence"), field="evidence")
        affected_refs = _parse_affected_refs(request.get("affected_refs"))
        summary = str(request.get("summary") or "").strip()

        plan = self._store.load_plan_model(self._run_id)
        self._require_production_context(plan)
        production = self._store.load_production(self._run_id)
        if has_pending_amendment(production):
            raise RequestError(
                "production is paused while a plan amendment is pending"
            )
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
            self._store.commit(
                self._run_id,
                CommitSpec(
                    production=updated,
                    production_expected_revision=expected_revision,
                    events=[
                        apply_request_audit_fields(
                            {
                                "type": "production_blocked_reported",
                                "run_id": self._run_id,
                                "affected_refs": affected_refs,
                                "production_revision": updated["revision"],
                            },
                            request_audit,
                        )
                    ],
                ),
            )
            next_revision = int(updated["revision"])
        except StoreRevisionConflictError as exc:
            raise RevisionConflictError(
                str(exc),
                expected=exc.expected,
                actual=exc.actual,
                action=_PRODUCTION_SNAPSHOT_ACTION,
            ) from exc

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
                    sha256=output.sha256,
                    size=output.size,
                    media_type=output.media_type,
                    captured_at=output.captured_at,
                    batch_id=batch.id,
                    snapshot_ref=output.snapshot_ref,
                ).to_dict()
            )
        updated["output_evidence"] = evidence
        updated["output_revision"] = int(updated.get("output_revision") or 0) + 1
        return updated

    def _require_production_context(self, plan) -> None:
        run = self._store.load_run(self._run_id)
        phase = str(run.get("phase") or "")
        if not allows_production_mutations(phase):
            raise RequestError(
                "production commands are only allowed in production or "
                f"whole-output review phases (current: {phase!r})"
            )
        if find_whole_plan_approval(self._store.list_reviews(self._run_id), plan.revision) is None:
            raise RequestError(
                "production commands require an approved whole-plan review "
                "for the current plan revision"
            )

    def _dispositions(self, production: dict[str, Any]) -> DispositionMap:
        raw = production.get("dispositions") or {}
        return dict(raw)

    def _validate_apply_snapshot_evidence(
        self,
        candidate_production: dict[str, Any],
        *,
        current_revision: int,
    ) -> None:
        run = self._store.load_run(self._run_id)
        config = self._store.load_resolved_config(self._run_id)
        workspace = run_workspace(run)
        old_binding = dict(run.get("context_snapshot_binding") or {})
        new_binding, new_snapshot_digest = recompute_context_snapshot_binding(
            config,
            workspace=workspace,
        )

        try:
            from top_down_planning.config.context_digests import prospective_batch_output_refs

            validate_run_production_snapshot_drift(
                run,
                config,
                candidate_production,
                workspace=workspace,
                new_binding=new_binding,
                new_snapshot_digest=new_snapshot_digest,
                prospective_output_refs=prospective_batch_output_refs(
                    candidate_production
                ),
            )
        except UnauthorizedContextMutationError as exc:
            drift_counts = _snapshot_drift_count_fields(exc)
            evidence_gaps, context_mutations = split_unauthorized_snapshot_paths(
                exc.unauthorized_paths,
                binding=old_binding,
                other_binding=new_binding,
            )
            if context_mutations:
                raise ProductionContextMutationError(
                    format_apply_context_mutation_message(
                        list(context_mutations),
                        production_revision=current_revision,
                        evidence_gap_paths=list(evidence_gaps) or None,
                    ),
                    context_mutation_paths=context_mutations,
                    production_revision=current_revision,
                    unauthorized_changed_paths=exc.unauthorized_paths,
                    evidence_gap_paths=evidence_gaps,
                    **drift_counts,
                ) from exc
            raise ProductionEvidenceIncompleteError(
                format_apply_snapshot_evidence_message(
                    list(evidence_gaps),
                    production_revision=current_revision,
                ),
                unauthorized_paths=evidence_gaps,
                production_revision=current_revision,
                **drift_counts,
            ) from exc
        except InvalidProductionEvidenceError as exc:
            raise RequestError(str(exc)) from exc


def _snapshot_drift_count_fields(
    exc: UnauthorizedContextMutationError,
) -> dict[str, int]:
    changed = exc.changed_paths or exc.unauthorized_paths
    authorized_changed = exc.authorized_changed_paths
    return {
        "changed_snapshot_paths": len(changed),
        "authorized_changed_paths": len(authorized_changed),
    }


@dataclass(frozen=True)
class OutputSpec:
    id: str
    type: str
    ref: str


def _provisional_outputs_from_specs(specs: list[OutputSpec]) -> list[OutputEvidence]:
    return [
        OutputEvidence(
            id=spec.id,
            type=spec.type,
            ref=spec.ref,
            sha256="0" * 64,
            size=0,
            media_type="application/octet-stream",
            captured_at="",
            snapshot_ref="",
        )
        for spec in specs
    ]


def _build_apply_candidate(
    production: dict[str, Any],
    batch: ProductionBatch,
    disposition_records: dict[str, ItemDispositionRecord],
    output_specs: list[OutputSpec],
) -> dict[str, Any]:
    expected_revision = int(production["revision"])
    updated = dict(production)
    updated["revision"] = expected_revision + 1

    batch_dict = batch.to_dict()
    result = dict(batch_dict.get("result") or {})
    result["outputs"] = [
        {"id": spec.id, "type": spec.type, "ref": spec.ref}
        for spec in output_specs
    ]
    batch_dict["result"] = result

    batches = list(updated.get("batches") or [])
    batches.append(batch_dict)
    updated["batches"] = batches

    flat_dispositions = dict(updated.get("dispositions") or {})
    flat_dispositions.update(disposition_map_from_records(disposition_records))
    updated["dispositions"] = flat_dispositions

    evidence = list(updated.get("output_evidence") or [])
    for spec in output_specs:
        evidence.append(
            {
                "id": spec.id,
                "type": spec.type,
                "ref": spec.ref,
            }
        )
    updated["output_evidence"] = evidence
    updated["output_revision"] = int(updated.get("output_revision") or 0) + 1
    return updated


def _parse_output_specs(
    store: RunStore,
    run_id: str,
    raw_outputs: Any,
    *,
    workspace: Path,
) -> list[OutputSpec]:
    from top_down_planning.config.snapshot_policy import (
        CanonicalPathError,
        canonicalize_evidence_ref,
    )

    if not isinstance(raw_outputs, list):
        raise RequestError("outputs must be a list")
    production = store.load_production(run_id)
    existing_ids = {
        str(entry.get("id") or "")
        for entry in (production.get("output_evidence") or [])
        if entry.get("id")
    }
    specs: list[OutputSpec] = []
    seen_ids: set[str] = set()
    workspace_root = workspace.resolve()
    for item in raw_outputs:
        if not isinstance(item, dict):
            raise RequestError("each output must be an object")
        evidence_id = str(item.get("id") or "")
        ref = str(item.get("ref") or "")
        if not evidence_id or not ref:
            raise RequestError("each output requires id and ref")
        if evidence_id in existing_ids:
            raise RequestError(f"duplicate output id across run history: {evidence_id}")
        if evidence_id in seen_ids:
            raise RequestError(f"duplicate output id: {evidence_id}")
        seen_ids.add(evidence_id)
        try:
            canonical_ref = canonicalize_evidence_ref(ref, workspace=workspace_root)
        except CanonicalPathError as exc:
            raise RequestError(str(exc)) from exc
        artifact_path = (workspace_root / canonical_ref).resolve()
        if not artifact_path.is_relative_to(workspace_root):
            raise RequestError(f"artifact ref escapes workspace: {ref!r}")
        if not artifact_path.is_file():
            raise RequestError(f"artifact ref does not exist: {ref!r}")
        specs.append(
            OutputSpec(
                id=evidence_id,
                type=str(item.get("type") or "artifact"),
                ref=canonical_ref,
            )
        )
    return specs


def _capture_output_specs(
    store: RunStore,
    run_id: str,
    workspace: Path,
    specs: list[OutputSpec],
) -> list[OutputEvidence]:
    outputs: list[OutputEvidence] = []
    for spec in specs:
        captured = capture_output_artifact(
            store,  # type: ignore[arg-type]
            run_id,
            workspace=workspace,
            ref=spec.ref,
        )
        outputs.append(
            OutputEvidence(
                id=spec.id,
                type=spec.type,
                ref=str(captured["ref"]),
                sha256=str(captured["sha256"]),
                size=int(captured["size"]),
                media_type=str(captured["media_type"]),
                captured_at=str(captured["captured_at"]),
                snapshot_ref=str(captured["snapshot_ref"]),
            )
        )
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
