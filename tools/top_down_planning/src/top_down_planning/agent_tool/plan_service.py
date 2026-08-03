"""Agent plan snapshot/apply/check service (proposal §8, §17.3)."""

from __future__ import annotations

from typing import Any

from top_down_planning.agent_tool.config import planning_limits_from_config
from top_down_planning.agent_tool.authorization import authorize_mutation
from top_down_planning.agent_tool.errors import (
    OperationError,
    RequestError,
    RevisionConflictError,
)
from top_down_planning.agent_tool.validation_context import plan_approval_validation_context
from top_down_planning.agent_tool.views import (
    PlanView,
    build_active_view,
    build_audit_view,
    build_changed_subtree_view,
    build_hierarchy_snapshot,
    build_ready_view,
    ready_item_changes,
    validation_issues,
    validation_warnings,
)
from top_down_planning.domain.dispositions import DispositionMap
from top_down_planning.domain.errors import (
    DomainError,
    InvalidMutationError,
    RevisionConflictError as DomainRevisionConflictError,
    UnknownItemError,
)
from top_down_planning.domain.models import Plan
from top_down_planning.domain.mutations import apply_operations
from top_down_planning.domain.validators import (
    ValidationMode,
    new_hard_validation_issues,
    validate_plan,
)
from top_down_planning.agent_tool.request_audit import (
    AgentRequestContext,
    apply_request_audit_fields,
)
from top_down_planning.persistence.commit import CommitSpec
from top_down_planning.persistence.digests import compute_plan_digest
from core_tools.persistence import StoreRevisionConflictError
from top_down_planning.persistence.interface import RunStore


class PlanAgentService:
    """Structured plan interaction for agents against a persisted run."""

    def __init__(self, store: RunStore, run_id: str) -> None:
        self._store = store
        self._run_id = run_id

    def snapshot(
        self,
        *,
        view: PlanView = "active",
        root_id: str | None = None,
        depth: int | None = None,
        mode: ValidationMode = "draft",
    ) -> dict[str, Any]:
        plan = self._store.load_plan_model(self._run_id)
        limits = self._planning_limits()
        dispositions = self._dispositions()
        reviews = self._store.list_reviews(self._run_id)
        review_state, digests = plan_approval_validation_context(
            self._store,
            self._run_id,
            plan,
            mode,
        )
        validation = validate_plan(
            plan,
            limits=limits,
            dispositions=dispositions,
            review_state=review_state,
            digests=digests,
            reviews=reviews,
            mode=mode,
        )

        if view == "active":
            payload = build_active_view(
                plan, limits=limits, root_id=root_id, depth=depth
            )
        elif view == "audit":
            payload = build_audit_view(
                plan, limits=limits, root_id=root_id, depth=depth
            )
        elif view == "ready":
            payload = build_ready_view(plan, dispositions, reviews=reviews)
        else:
            payload = {
                "view": "issues",
                "revision": plan.revision,
                "mode": mode,
            }

        payload["ok"] = validation.ok
        payload["issues"] = validation_issues(validation)
        payload["warnings"] = validation_warnings(validation)
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
            operation="plan_apply",
            capability_token=capability_token,
        )

        if "base_revision" not in request:
            raise RequestError("apply requires base_revision")
        if "operations" not in request:
            raise RequestError("apply requires operations")

        base_revision = int(request["base_revision"])
        operations = request["operations"]
        if not isinstance(operations, list):
            raise RequestError("operations must be a list")

        plan = self._store.load_plan_model(self._run_id)
        limits = self._planning_limits()
        dispositions = self._dispositions()
        reviews = self._store.list_reviews(self._run_id)
        before_validation = validate_plan(
            plan,
            limits=limits,
            dispositions=dispositions,
            reviews=reviews,
            mode="draft",
        )

        try:
            result = apply_operations(
                plan,
                base_revision,
                operations,
                limits=limits,
                reviews=reviews,
            )
        except DomainRevisionConflictError as exc:
            raise RevisionConflictError(
                str(exc),
                expected=exc.expected,
                actual=exc.actual,
            ) from exc
        except UnknownItemError as exc:
            raise OperationError(str(exc), hint=exc.hint) from exc
        except InvalidMutationError as exc:
            raise OperationError(str(exc)) from exc
        except DomainError as exc:
            raise OperationError(str(exc)) from exc

        after_validation = validate_plan(
            result.plan,
            limits=limits,
            dispositions=dispositions,
            reviews=reviews,
            mode="draft",
        )
        introduced_errors = new_hard_validation_issues(before_validation, after_validation)
        if introduced_errors:
            first = introduced_errors[0]
            raise OperationError(
                f"mutation introduced validation error: {first.code}: {first.message}"
            )

        before_plan = plan
        run = self._store.load_run(self._run_id)
        expected_run_revision = int(run["revision"])
        run_payload = dict(run)
        run_payload["revision"] = expected_run_revision + 1
        run_payload["digests"] = dict(run_payload.get("digests") or {})
        run_payload["digests"]["plan"] = compute_plan_digest(result.plan)

        try:
            self._store.commit(
                self._run_id,
                CommitSpec(
                    plan=result.plan.to_dict(),
                    plan_expected_revision=base_revision,
                    run=run_payload,
                    run_expected_revision=expected_run_revision,
                    events=[
                        apply_request_audit_fields(
                            {
                                "type": "plan_applied",
                                "run_id": self._run_id,
                                "base_revision": base_revision,
                                "revision": result.revision,
                                "operation_count": len(operations),
                                "changed_item_ids": result.changed_item_ids,
                            },
                            request_audit,
                        )
                    ],
                ),
            )
        except StoreRevisionConflictError as exc:
            raise RevisionConflictError(
                str(exc),
                expected=exc.expected,
                actual=exc.actual,
            ) from exc

        validation = after_validation

        return {
            "ok": validation.ok,
            "applied": True,
            "revision": result.revision,
            "id_map": dict(result.id_map),
            "changed_item_ids": list(result.changed_item_ids),
            "changed_subtree": build_changed_subtree_view(
                result.plan,
                result.changed_item_ids,
                limits=limits,
            ),
            "warnings": list(result.warnings) + validation_warnings(validation),
            "issues": validation_issues(validation),
            "planning_budget": [budget.to_dict() for budget in result.budgets],
            "ready_changes": ready_item_changes(
                before_plan,
                result.plan,
                dispositions,
                reviews=reviews,
            ),
        }

    def check(self, *, mode: ValidationMode = "draft") -> dict[str, Any]:
        plan = self._store.load_plan_model(self._run_id)
        limits = self._planning_limits()
        dispositions = self._dispositions()
        reviews = self._store.list_reviews(self._run_id)
        review_state, digests = plan_approval_validation_context(
            self._store,
            self._run_id,
            plan,
            mode,
        )
        validation = validate_plan(
            plan,
            limits=limits,
            dispositions=dispositions,
            review_state=review_state,
            digests=digests,
            reviews=reviews,
            mode=mode,
        )
        return {
            "ok": validation.ok,
            "mode": mode,
            "revision": plan.revision,
            "issues": validation_issues(validation),
            "warnings": validation_warnings(validation),
        }

    def _planning_limits(self):
        config = self._store.load_resolved_config(self._run_id)
        return planning_limits_from_config(config)

    def _dispositions(self) -> DispositionMap:
        production = self._store.load_production(self._run_id)
        raw = production.get("dispositions") or {}
        return dict(raw)
