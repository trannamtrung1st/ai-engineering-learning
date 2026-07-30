"""Agent plan snapshot/apply/check service (proposal §8, §17.3)."""

from __future__ import annotations

from typing import Any

from top_down_planning.agent_tool.config import planning_limits_from_config
from top_down_planning.agent_tool.errors import (
    OperationError,
    RequestError,
    RevisionConflictError,
)
from top_down_planning.agent_tool.roles import assert_plan_mutations_allowed
from top_down_planning.agent_tool.views import (
    PlanView,
    build_changed_subtree_view,
    build_issues_view,
    build_ready_view,
    build_tree_view,
    ready_item_changes,
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
from top_down_planning.domain.validators import ValidationMode, validate_plan
from top_down_planning.persistence.digests import compute_plan_digest
from top_down_planning.persistence.errors import StoreRevisionConflictError
from top_down_planning.persistence.interface import RunStore


class PlanAgentService:
    """Structured plan interaction for agents against a persisted run."""

    def __init__(self, store: RunStore, run_id: str) -> None:
        self._store = store
        self._run_id = run_id

    def snapshot(
        self,
        *,
        view: PlanView = "tree",
        root_id: str | None = None,
        depth: int | None = None,
        mode: ValidationMode = "draft",
    ) -> dict[str, Any]:
        plan = self._store.load_plan_model(self._run_id)
        limits = self._planning_limits()
        dispositions = self._dispositions()

        if view == "tree":
            payload = build_tree_view(plan, limits=limits, root_id=root_id, depth=depth)
        elif view == "ready":
            payload = build_ready_view(plan, dispositions)
        else:
            payload = build_issues_view(
                plan,
                limits=limits,
                mode=mode,
                dispositions=dispositions,
            )

        validation = validate_plan(plan, limits=limits, dispositions=dispositions, mode="draft")
        payload["ok"] = True
        payload["warnings"] = validation_warnings(validation)
        return payload

    def apply(
        self,
        request: dict[str, Any],
        *,
        role: str,
    ) -> dict[str, Any]:
        normalized_role = str(role).strip()
        if not normalized_role:
            raise RequestError("apply requires role")
        assert_plan_mutations_allowed(normalized_role)

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

        try:
            result = apply_operations(plan, base_revision, operations, limits=limits)
        except DomainRevisionConflictError as exc:
            raise RevisionConflictError(
                str(exc),
                expected=exc.expected,
                actual=exc.actual,
            ) from exc
        except (InvalidMutationError, UnknownItemError) as exc:
            raise OperationError(str(exc)) from exc
        except DomainError as exc:
            raise OperationError(str(exc)) from exc

        before_plan = plan
        try:
            self._store.save_plan_model(self._run_id, result.plan, base_revision)
        except StoreRevisionConflictError as exc:
            raise RevisionConflictError(
                str(exc),
                expected=exc.expected,
                actual=exc.actual,
            ) from exc

        run = self._store.load_run(self._run_id)
        expected_run_revision = int(run["revision"])
        run["revision"] = expected_run_revision + 1
        run["digests"]["plan"] = compute_plan_digest(result.plan)
        self._store.save_run(self._run_id, run, expected_run_revision)

        self._store.append_event(
            self._run_id,
            {
                "type": "plan_applied",
                "run_id": self._run_id,
                "base_revision": base_revision,
                "revision": result.revision,
                "operation_count": len(operations),
                "changed_item_ids": result.changed_item_ids,
            },
        )

        validation = validate_plan(
            result.plan,
            limits=limits,
            dispositions=dispositions,
            mode="draft",
        )

        return {
            "ok": True,
            "revision": result.revision,
            "id_map": dict(result.id_map),
            "changed_item_ids": list(result.changed_item_ids),
            "changed_subtree": build_changed_subtree_view(
                result.plan,
                result.changed_item_ids,
                limits=limits,
            ),
            "warnings": list(result.warnings) + validation_warnings(validation),
            "planning_budget": [budget.to_dict() for budget in result.budgets],
            "ready_changes": ready_item_changes(before_plan, result.plan, dispositions),
        }

    def check(self, *, mode: ValidationMode = "draft") -> dict[str, Any]:
        plan = self._store.load_plan_model(self._run_id)
        limits = self._planning_limits()
        dispositions = self._dispositions()
        validation = validate_plan(
            plan,
            limits=limits,
            dispositions=dispositions,
            mode=mode,
        )
        return {
            "ok": validation.ok,
            "mode": mode,
            "revision": plan.revision,
            "issues": [issue.to_dict() for issue in validation.issues],
        }

    def _planning_limits(self):
        config = self._store.load_resolved_config(self._run_id)
        return planning_limits_from_config(config)

    def _dispositions(self) -> DispositionMap:
        production = self._store.load_production(self._run_id)
        raw = production.get("dispositions") or {}
        return dict(raw)
