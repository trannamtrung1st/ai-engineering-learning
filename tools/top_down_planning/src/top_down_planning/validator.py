"""Validate agent operations before applying them to planning state."""

from __future__ import annotations

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
            _validate_cumulative_item_limit(plan, list(op_by_node.values()), limits=limits)
        )

    if not errors:
        errors.extend(_validate_applied_state(plan, response))

    return errors


def validate_wave_responses(
    plan: PlanState,
    batches: list[tuple[list[str], AgentResponse]],
    *,
    limits: PlanningLimits,
    plan_digest: str,
) -> list[str]:
    """Validate independent concurrent batch responses against one plan snapshot."""
    all_operations: list[PlanningOperation] = []
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


def _validate_expand(
    plan: PlanState,
    item: PlanItem,
    operation: ExpandOperation,
    *,
    limits: PlanningLimits,
) -> list[str]:
    errors: list[str] = []
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
    errors: list[str] = []
    outputs = operation.expected_outputs or item.expected_outputs
    criteria = operation.acceptance_criteria or item.acceptance_criteria
    if not item.objective.strip():
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
    errors: list[str] = []
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
    if not operation.reason.strip():
        return [f"Out-of-scope item {item.id} requires a reason"]
    return []

