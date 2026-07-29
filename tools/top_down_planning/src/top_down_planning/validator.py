"""Validate agent operations before applying them to planning state."""

from __future__ import annotations

from top_down_planning.generation_context import select_patchable_node_ids
from top_down_planning.scheduler import compute_batch_write_scope
from top_down_planning.models import (
    AgentResponse,
    BlockedConstraintCode,
    DecompositionStatus,
    ExpandOperation,
    MarkActionableOperation,
    MarkBlockedOperation,
    MarkOutOfScopeOperation,
    PlanItem,
    PlanState,
    PlanningLimits,
    PlanningOperation,
    ReviseActionableOperation,
    UpdateItemOperation,
)
from top_down_planning.completeness import structural_errors
from top_down_planning.state_updates import apply_response


def _normalize(text: str) -> str:
    return " ".join(text.strip().split()).lower()


def _is_implementation_goal(output_goal: str) -> bool:
    lowered = output_goal.lower()
    markers = (
        "implementation",
        "development",
        "actionable",
        "migration",
        "engineering",
        "build",
        "task",
    )
    return any(marker in lowered for marker in markers)


def validate_response(
    plan: PlanState,
    response: AgentResponse,
    *,
    selected_ids: list[str],
    limits: PlanningLimits,
) -> list[str]:
    errors: list[str] = []
    selected_set = set(selected_ids)
    op_by_node: dict[str, PlanningOperation] = {}

    if not response.operations:
        errors.append("Response must include at least one operation")
        return errors

    for operation in response.operations:
        node_id = operation.node_id
        if node_id not in selected_set:
            errors.append(f"Operation targets unselected node: {node_id}")
            continue
        if node_id in op_by_node:
            errors.append(f"Duplicate operation for node: {node_id}")
            continue
        op_by_node[node_id] = operation

    missing = selected_set - set(op_by_node)
    if missing:
        errors.append(
            "Missing operations for selected nodes: "
            + ", ".join(sorted(missing))
        )

    for node_id, operation in op_by_node.items():
        item = plan.item_by_id(node_id)
        if item is None:
            errors.append(f"Unknown node id: {node_id}")
            continue
        if item.decomposition_status != DecompositionStatus.NEEDS_EXPANSION:
            errors.append(
                f"Node {node_id} is not expandable "
                f"(status={item.decomposition_status.value})"
            )
            continue
        errors.extend(_validate_operation(plan, item, operation, limits=limits))

    if not errors:
        errors.extend(
            _validate_updates(
                plan,
                response.updates,
                selected_ids=selected_set,
            )
        )

    if not errors:
        errors.extend(
            _validate_cumulative_item_limit(plan, list(op_by_node.values()), limits=limits)
        )

    if not errors:
        errors.extend(_validate_applied_state(plan, response))

    return errors


def validate_amend_response(
    plan: PlanState,
    response: AgentResponse,
    *,
    selected_ids: list[str],
) -> list[str]:
    """Validate in-place revision operations for actionable items."""
    errors: list[str] = []
    selected_set = set(selected_ids)
    op_by_node: dict[str, PlanningOperation] = {}

    if not response.operations:
        errors.append("Response must include at least one operation")
        return errors

    if response.updates:
        errors.append("Amend sessions must not include cross-item updates")

    for operation in response.operations:
        node_id = operation.node_id
        if node_id not in selected_set:
            errors.append(f"Operation targets unselected node: {node_id}")
            continue
        if node_id in op_by_node:
            errors.append(f"Duplicate operation for node: {node_id}")
            continue
        if not isinstance(operation, ReviseActionableOperation):
            errors.append(
                f"Amend session for {node_id} must use revise_actionable, "
                f"got {operation.type}"
            )
            continue
        op_by_node[node_id] = operation

    missing = selected_set - set(op_by_node)
    if missing:
        errors.append(
            "Missing revise_actionable operations for selected nodes: "
            + ", ".join(sorted(missing))
        )

    for node_id, operation in op_by_node.items():
        item = plan.item_by_id(node_id)
        if item is None:
            errors.append(f"Unknown node id: {node_id}")
            continue
        if item.decomposition_status != DecompositionStatus.ACTIONABLE:
            errors.append(
                f"Node {node_id} is not actionable "
                f"(status={item.decomposition_status.value})"
            )
            continue
        errors.extend(_validate_revise_actionable(plan, item, operation))

    if not errors:
        errors.extend(_validate_applied_state(plan, response))

    return errors


def validate_amend_wave_responses(
    plan: PlanState,
    batches: list[tuple[list[str], AgentResponse]],
    *,
    plan_digest: str,
) -> list[str]:
    """Validate concurrent amend batch responses against one plan snapshot."""
    for selected_ids, response in batches:
        if response.plan_digest != plan_digest:
            return [
                f"Transaction plan_digest mismatch: expected {plan_digest}, "
                f"got {response.plan_digest}"
            ]
        errors = validate_amend_response(
            plan,
            response,
            selected_ids=selected_ids,
        )
        if errors:
            return errors

    updated = plan
    try:
        for _, response in batches:
            updated = apply_response(updated, response)
    except ValueError as exc:
        return [str(exc)]

    return structural_errors(updated)


def validate_wave_responses(
    plan: PlanState,
    batches: list[tuple[list[str], AgentResponse]],
    *,
    limits: PlanningLimits,
    plan_digest: str,
) -> list[str]:
    """Validate independent concurrent batch responses against one plan snapshot."""
    all_operations: list[PlanningOperation] = []
    all_update_targets: list[str] = []
    for selected_ids, response in batches:
        if response.plan_digest != plan_digest:
            return [
                f"Transaction plan_digest mismatch: expected {plan_digest}, "
                f"got {response.plan_digest}"
            ]
        errors = validate_response(
            plan,
            response,
            selected_ids=selected_ids,
            limits=limits,
        )
        if errors:
            return errors
        all_operations.extend(response.operations)
        all_update_targets.extend(update.node_id for update in response.updates)

    errors = _validate_cross_batch_update_conflicts(all_update_targets)
    if errors:
        return errors

    errors = _validate_wave_write_scope_separation(plan, batches)
    if errors:
        return errors

    errors = _validate_cumulative_item_limit(plan, all_operations, limits=limits)
    if errors:
        return errors

    updated = plan
    try:
        for _, response in batches:
            updated = apply_response(updated, response)
    except ValueError as exc:
        return [str(exc)]

    errors = _validate_cross_batch_duplicates(updated)
    if errors:
        return errors

    return structural_errors(updated)


def _validate_cross_batch_update_conflicts(update_targets: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for node_id in update_targets:
        if node_id in seen:
            duplicates.add(node_id)
        seen.add(node_id)
    if not duplicates:
        return []
    return [
        "Concurrent batches attempted cross-item updates for the same node: "
        + ", ".join(sorted(duplicates))
    ]


def _validate_wave_write_scope_separation(
    plan: PlanState,
    batches: list[tuple[list[str], AgentResponse]],
) -> list[str]:
    scopes: list[set[str]] = []
    for selected_ids, _ in batches:
        items = [
            item
            for item in (plan.item_by_id(node_id) for node_id in selected_ids)
            if item is not None
        ]
        if not items:
            continue
        scope = compute_batch_write_scope(plan, items)
        if any(scope & existing for existing in scopes):
            return [
                "Concurrent wave batches have overlapping write scopes: "
                + ", ".join(sorted(selected_ids))
            ]
        scopes.append(scope)
    return []


def _validate_updates(
    plan: PlanState,
    updates: list[UpdateItemOperation],
    *,
    selected_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    patchable = select_patchable_node_ids(plan, selected_ids)
    seen: set[str] = set()

    for update in updates:
        node_id = update.node_id
        if node_id in selected_ids:
            errors.append(
                f"Update targets assigned node {node_id}; use the primary operation instead"
            )
            continue
        if node_id not in patchable:
            errors.append(f"Update targets non-patchable node: {node_id}")
            continue
        if node_id in seen:
            errors.append(f"Duplicate update for node: {node_id}")
            continue
        seen.add(node_id)

        item = plan.item_by_id(node_id)
        if item is None:
            errors.append(f"Unknown update node id: {node_id}")
            continue
        errors.extend(_validate_update_item(plan, item, update))

    return errors


def _validate_update_item(
    plan: PlanState,
    item: PlanItem,
    update: UpdateItemOperation,
) -> list[str]:
    errors: list[str] = []
    if not update.reason.strip():
        errors.append(f"Update on {item.id} requires a reason")

    objective = update.objective if update.objective is not None else item.objective
    if not objective.strip():
        errors.append(f"Update on {item.id} would leave an empty objective")

    if (
        update.expected_outputs is not None
        or update.acceptance_criteria is not None
    ) and item.decomposition_status != DecompositionStatus.ACTIONABLE:
        errors.append(
            f"Update on {item.id} may change expected_outputs or acceptance_criteria "
            "only for actionable items"
        )

    deps = update.dependencies if update.dependencies is not None else item.dependencies
    for dep in deps:
        if plan.item_by_id(dep) is None:
            errors.append(f"Update on {item.id} references unknown dependency: {dep}")

    outputs = (
        update.expected_outputs
        if update.expected_outputs is not None
        else item.expected_outputs
    )
    criteria = (
        update.acceptance_criteria
        if update.acceptance_criteria is not None
        else item.acceptance_criteria
    )
    if _is_implementation_goal(plan.source.output_goal):
        if item.decomposition_status == DecompositionStatus.ACTIONABLE:
            if not outputs:
                errors.append(
                    f"Update on {item.id} requires expected_outputs for this output goal"
                )
            if not criteria:
                errors.append(
                    f"Update on {item.id} requires acceptance_criteria "
                    "for this output goal"
                )

    return errors


def _validate_cross_batch_duplicates(plan: PlanState) -> list[str]:
    """Detect duplicate sibling titles introduced across concurrent batches."""
    errors: list[str] = []
    for parent_id in {item.parent_id for item in plan.plan}:
        counts: dict[str, int] = {}
        for child in plan.children_of(parent_id):
            norm = _normalize(child.title)
            counts[norm] = counts.get(norm, 0) + 1
        for norm, count in counts.items():
            if count > 1:
                parent_label = parent_id or "root"
                errors.append(
                    f"Duplicate sibling title under {parent_label}: {norm!r}"
                )
    return errors


def _validate_cumulative_item_limit(
    plan: PlanState,
    operations: list[PlanningOperation],
    *,
    limits: PlanningLimits,
) -> list[str]:
    projected_total = len(plan.plan)
    for operation in operations:
        if isinstance(operation, ExpandOperation):
            projected_total += len(operation.children)
            if projected_total > limits.max_items:
                return [
                    "Operations would exceed max items "
                    f"({projected_total} > {limits.max_items})"
                ]
    return []


def _validate_applied_state(plan: PlanState, response: AgentResponse) -> list[str]:
    try:
        updated = apply_response(plan, response)
    except ValueError as exc:
        return [str(exc)]
    return structural_errors(updated)


def _validate_operation(
    plan: PlanState,
    item: PlanItem,
    operation: PlanningOperation,
    *,
    limits: PlanningLimits,
) -> list[str]:
    if isinstance(operation, ExpandOperation):
        return _validate_expand(plan, item, operation, limits=limits)
    if isinstance(operation, MarkActionableOperation):
        return _validate_actionable(plan, item, operation)
    if isinstance(operation, MarkBlockedOperation):
        return _validate_blocked(item, operation, limits=limits)
    if isinstance(operation, MarkOutOfScopeOperation):
        return _validate_out_of_scope(item, operation)
    return [f"Unsupported operation type for node {item.id}"]


def _validate_revise_actionable(
    plan: PlanState,
    item: PlanItem,
    operation: ReviseActionableOperation,
) -> list[str]:
    errors: list[str] = []
    if not operation.reason.strip():
        errors.append(f"Revise on {item.id} requires a reason")
    deps = (
        operation.dependencies
        if operation.dependencies is not None
        else item.dependencies
    )
    for dep in deps:
        if plan.item_by_id(dep) is None:
            errors.append(f"Revise on {item.id} references unknown dependency: {dep}")
    outputs = (
        operation.expected_outputs
        if operation.expected_outputs is not None
        else item.expected_outputs
    )
    criteria = (
        operation.acceptance_criteria
        if operation.acceptance_criteria is not None
        else item.acceptance_criteria
    )
    objective = operation.objective if operation.objective is not None else item.objective
    if not objective.strip():
        errors.append(f"Revise on {item.id} requires a non-empty objective")
    if _is_implementation_goal(plan.source.output_goal):
        if not outputs:
            errors.append(
                f"Revise on {item.id} requires expected_outputs for this output goal"
            )
        if not criteria:
            errors.append(
                f"Revise on {item.id} requires acceptance_criteria "
                "for this output goal"
            )
    return errors


def _validate_expand(
    plan: PlanState,
    item: PlanItem,
    operation: ExpandOperation,
    *,
    limits: PlanningLimits,
) -> list[str]:
    errors = _validate_root_metadata(
        item,
        title=operation.title,
        objective=operation.objective,
        operation_name="Expand",
    )
    if not operation.children:
        errors.append(f"Expand on {item.id} requires at least one child")
        return errors
    if len(operation.children) > limits.max_children_per_expansion:
        errors.append(
            f"Expand on {item.id} exceeds max children "
            f"({len(operation.children)} > {limits.max_children_per_expansion}). "
            "Do not merge or omit explicitly required siblings to satisfy the limit. "
            "Use mark_blocked with constraint_code=max_children_exceeded and "
            "required_min_children set to the required direct-child count."
        )
    if item.depth + 1 > limits.max_depth:
        errors.append(
            f"Expand on {item.id} would exceed max depth "
            f"({item.depth + 1} > {limits.max_depth})"
        )
    projected_total = len(plan.plan) + len(operation.children)
    if projected_total > limits.max_items:
        errors.append(
            f"Expand on {item.id} would exceed max items "
            f"({projected_total} > {limits.max_items})"
        )

    sibling_titles = {
        _normalize(child.title)
        for child in plan.children_of(item.id)
    }
    refs: set[str] = set()
    all_refs = {
        child.ref or f"child-{index + 1}"
        for index, child in enumerate(operation.children)
    }
    for index, child in enumerate(operation.children):
        norm_title = _normalize(child.title)
        if norm_title in sibling_titles:
            errors.append(
                f"Duplicate sibling title under {item.id}: {child.title!r}"
            )
        sibling_titles.add(norm_title)
        ref = child.ref or f"child-{index + 1}"
        if ref in refs:
            errors.append(f"Duplicate child ref in expand on {item.id}: {ref!r}")
        refs.add(ref)
        for dep in child.dependencies:
            if dep in all_refs or plan.item_by_id(dep) is not None:
                continue
            errors.append(
                f"Unknown dependency {dep!r} for child {child.title!r} under {item.id}"
            )
    return errors


def _validate_actionable(
    plan: PlanState,
    item: PlanItem,
    operation: MarkActionableOperation,
) -> list[str]:
    errors = _validate_root_metadata(
        item,
        title=operation.title,
        objective=operation.objective,
        operation_name="Mark actionable",
    )
    outputs = operation.expected_outputs or item.expected_outputs
    criteria = operation.acceptance_criteria or item.acceptance_criteria
    objective = operation.objective or item.objective
    if not objective.strip():
        errors.append(f"Actionable item {item.id} requires a non-empty objective")
    if _is_implementation_goal(plan.source.output_goal):
        if not outputs:
            errors.append(
                f"Actionable item {item.id} requires expected_outputs for this output goal"
            )
        if not criteria:
            errors.append(
                f"Actionable item {item.id} requires acceptance_criteria "
                "for this output goal"
            )
    for dep in operation.dependencies or item.dependencies:
        if plan.item_by_id(dep) is None:
            errors.append(f"Actionable item {item.id} references unknown dependency: {dep}")
    return errors


def _validate_blocked(
    item: PlanItem,
    operation: MarkBlockedOperation,
    *,
    limits: PlanningLimits,
) -> list[str]:
    errors = _validate_root_metadata(
        item,
        title=operation.title,
        objective=operation.objective,
        operation_name="Mark blocked",
    )
    if not operation.reason.strip():
        errors.append(f"Blocked item {item.id} requires a reason")

    if operation.constraint_code == BlockedConstraintCode.MAX_CHILDREN_EXCEEDED:
        if operation.required_min_children is None:
            errors.append(
                f"Blocked item {item.id} with max_children_exceeded "
                "requires required_min_children"
            )
        elif operation.required_min_children <= limits.max_children_per_expansion:
            errors.append(
                f"Blocked item {item.id} required_min_children "
                f"({operation.required_min_children}) must exceed "
                f"max_children_per_expansion ({limits.max_children_per_expansion})"
            )
        return errors

    if not operation.missing_information.strip():
        errors.append(f"Blocked item {item.id} requires missing_information")
    if not operation.open_question.strip():
        errors.append(f"Blocked item {item.id} requires an open_question")
    return errors


def _validate_out_of_scope(
    item: PlanItem,
    operation: MarkOutOfScopeOperation,
) -> list[str]:
    errors = _validate_root_metadata(
        item,
        title=operation.title,
        objective=operation.objective,
        operation_name="Mark out of scope",
    )
    if not operation.reason.strip():
        errors.append(f"Out-of-scope item {item.id} requires a reason")
    return errors


def _validate_root_metadata(
    item: PlanItem,
    *,
    title: str | None,
    objective: str | None,
    operation_name: str,
) -> list[str]:
    has_title = title is not None
    has_objective = objective is not None
    if item.parent_id is None and not (has_title and has_objective):
        return [
            f"{operation_name} on root item {item.id} requires a generated "
            "title and objective"
        ]
    if item.parent_id is not None and (has_title or has_objective):
        return [
            f"{operation_name} on {item.id} may update title and objective only "
            "for the root item"
        ]
    return []

