"""Apply validated planning operations atomically."""

from __future__ import annotations

import copy

from top_down_planning.models import (
    AgentResponse,
    DecompositionStatus,
    ExpandOperation,
    MarkActionableOperation,
    MarkBlockedOperation,
    MarkOutOfScopeOperation,
    PlanItem,
    PlanState,
    PlanningOperation,
    ReadinessStatus,
    ReviseActionableOperation,
)
from top_down_planning.scheduler import next_item_id, next_order


def apply_response(plan: PlanState, response: AgentResponse) -> PlanState:
    updated = copy.deepcopy(plan)
    for operation in response.operations:
        item = updated.item_by_id(operation.node_id)
        if item is None:
            raise ValueError(f"Unknown node id: {operation.node_id}")
        if isinstance(operation, ExpandOperation):
            _apply_expand(updated, item, operation)
        elif isinstance(operation, MarkActionableOperation):
            _apply_actionable(item, operation)
        elif isinstance(operation, MarkBlockedOperation):
            _apply_blocked(item, operation)
        elif isinstance(operation, MarkOutOfScopeOperation):
            _apply_out_of_scope(item, operation)
        elif isinstance(operation, ReviseActionableOperation):
            _apply_revise_actionable(item, operation)
        else:
            raise ValueError(f"Unsupported operation: {operation}")
    _recompute_readiness(updated)
    return updated


def _apply_expand(
    plan: PlanState,
    parent: PlanItem,
    operation: ExpandOperation,
) -> None:
    _apply_root_metadata(
        parent,
        title=operation.title,
        objective=operation.objective,
        operation_name="Expand",
    )
    parent.decomposition_status = DecompositionStatus.ACTIONABLE
    parent.readiness_status = ReadinessStatus.READY

    ref_to_id: dict[str, str] = {}
    created: list[PlanItem] = []
    for index, child in enumerate(operation.children):
        child_id = next_item_id(plan)
        ref = child.ref or f"child-{index + 1}"
        ref_to_id[ref] = child_id
        created.append(
            PlanItem(
                id=child_id,
                parent_id=parent.id,
                title=child.title.strip(),
                objective=child.objective.strip(),
                depth=parent.depth + 1,
                order=next_order(plan),
                decomposition_status=DecompositionStatus.NEEDS_EXPANSION,
                readiness_status=ReadinessStatus.PENDING,
                expected_outputs=list(child.expected_outputs),
                acceptance_criteria=list(child.acceptance_criteria),
                notes=list(child.notes),
                risks=list(child.risks),
                open_questions=list(child.open_questions),
            )
        )
        plan.plan.append(created[-1])

    for item, draft in zip(created, operation.children, strict=True):
        resolved: list[str] = []
        for dep in draft.dependencies:
            if dep in ref_to_id:
                resolved.append(ref_to_id[dep])
            else:
                resolved.append(dep)
        item.dependencies = resolved


def _apply_actionable(item: PlanItem, operation: MarkActionableOperation) -> None:
    _apply_root_metadata(
        item,
        title=operation.title,
        objective=operation.objective,
        operation_name="Mark actionable",
    )
    item.decomposition_status = DecompositionStatus.ACTIONABLE
    item.readiness_status = ReadinessStatus.READY
    if operation.expected_outputs:
        item.expected_outputs = list(operation.expected_outputs)
    if operation.acceptance_criteria:
        item.acceptance_criteria = list(operation.acceptance_criteria)
    if operation.dependencies:
        item.dependencies = list(operation.dependencies)
    if operation.notes:
        item.notes.extend(operation.notes)
    if operation.risks:
        item.risks.extend(operation.risks)


def _apply_blocked(item: PlanItem, operation: MarkBlockedOperation) -> None:
    _apply_root_metadata(
        item,
        title=operation.title,
        objective=operation.objective,
        operation_name="Mark blocked",
    )
    item.decomposition_status = DecompositionStatus.BLOCKED
    item.readiness_status = ReadinessStatus.BLOCKED
    item.blocked_reason = operation.reason.strip()
    item.blocked_constraint_code = operation.constraint_code
    item.blocked_required_min_children = operation.required_min_children
    if operation.open_question.strip():
        item.open_questions.append(operation.open_question.strip())
    if operation.missing_information.strip():
        item.notes.append(
            f"Missing information: {operation.missing_information.strip()}"
        )


def _apply_out_of_scope(item: PlanItem, operation: MarkOutOfScopeOperation) -> None:
    _apply_root_metadata(
        item,
        title=operation.title,
        objective=operation.objective,
        operation_name="Mark out of scope",
    )
    item.decomposition_status = DecompositionStatus.OUT_OF_SCOPE
    item.readiness_status = ReadinessStatus.READY
    item.out_of_scope_reason = operation.reason.strip()


def _apply_root_metadata(
    item: PlanItem,
    *,
    title: str | None,
    objective: str | None,
    operation_name: str,
) -> None:
    if item.parent_id is None:
        if title is None or objective is None:
            raise ValueError(
                f"{operation_name} on root item {item.id} requires a generated "
                "title and objective"
            )
        item.title = title
        item.objective = objective
    elif title is not None or objective is not None:
        raise ValueError(
            f"{operation_name} on {item.id} may update title and objective only "
            "for the root item"
        )


def _apply_revise_actionable(item: PlanItem, operation: ReviseActionableOperation) -> None:
    item.decomposition_status = DecompositionStatus.ACTIONABLE
    item.readiness_status = ReadinessStatus.READY
    if operation.title and operation.title.strip():
        item.title = operation.title.strip()
    if operation.objective and operation.objective.strip():
        item.objective = operation.objective.strip()
    if operation.expected_outputs:
        item.expected_outputs = list(operation.expected_outputs)
    if operation.acceptance_criteria:
        item.acceptance_criteria = list(operation.acceptance_criteria)
    if operation.dependencies:
        item.dependencies = list(operation.dependencies)
    if operation.notes:
        item.notes.extend(operation.notes)
    if operation.risks:
        item.risks.extend(operation.risks)


def _recompute_readiness(plan: PlanState) -> None:
    by_id = {item.id: item for item in plan.plan}
    for item in plan.plan:
        if item.decomposition_status in {
            DecompositionStatus.BLOCKED,
            DecompositionStatus.OUT_OF_SCOPE,
            DecompositionStatus.ACTIONABLE,
        }:
            continue
        if item.decomposition_status == DecompositionStatus.NEEDS_EXPANSION:
            item.readiness_status = ReadinessStatus.PENDING
            continue
        unresolved = [
            dep
            for dep in item.dependencies
            if dep in by_id
            and by_id[dep].decomposition_status
            not in {
                DecompositionStatus.ACTIONABLE,
                DecompositionStatus.OUT_OF_SCOPE,
            }
        ]
        item.readiness_status = (
            ReadinessStatus.BLOCKED if unresolved else ReadinessStatus.READY
        )


def detect_dependency_cycles(plan: PlanState) -> list[str]:
    graph = {item.id: set(item.dependencies) for item in plan.plan}
    cycles: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(node: str, stack: list[str]) -> None:
        if node in visiting:
            cycle_start = stack.index(node)
            cycles.append(" -> ".join(stack[cycle_start:] + [node]))
            return
        if node in visited:
            return
        visiting.add(node)
        stack.append(node)
        for dep in graph.get(node, ()):
            if dep in graph:
                dfs(dep, stack)
        stack.pop()
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        dfs(node, [])
    return cycles
