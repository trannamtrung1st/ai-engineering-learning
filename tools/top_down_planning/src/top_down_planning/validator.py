"""Validate agent operations before applying them to planning state."""

from __future__ import annotations

from top_down_planning.generation_context import select_patchable_node_ids
from top_down_planning.models import (
    AgentResponse,
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
from top_down_planning.completeness import is_leaf, structural_errors
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
    output_goal_text: str,
    limits: PlanningLimits,
    eligible_ids: set[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    selected_set = set(selected_ids)
    op_by_node: dict[str, PlanningOperation] = {}

    errors.extend(_validate_eligible_selection(selected_ids, eligible_ids))
    if errors:
        return errors

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
        errors.extend(
            _validate_operation(
                plan,
                item,
                operation,
                limits=limits,
                output_goal_text=output_goal_text,
            )
        )

    if not errors:
        errors.extend(
            _validate_updates(
                plan,
                response.updates,
                selected_ids=selected_set,
                output_goal_text=output_goal_text,
            )
        )

    if not errors:
        errors.extend(_validate_applied_state(plan, response))

    return errors


def validate_amend_response(
    plan: PlanState,
    response: AgentResponse,
    *,
    selected_ids: list[str],
    output_goal_text: str,
    eligible_ids: set[str] | None = None,
) -> list[str]:
    """Validate in-place revision operations for actionable items."""
    errors: list[str] = []
    selected_set = set(selected_ids)
    op_by_node: dict[str, PlanningOperation] = {}

    errors.extend(_validate_eligible_selection(selected_ids, eligible_ids))
    if errors:
        return errors

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
        errors.extend(
            _validate_revise_actionable(
                plan,
                item,
                operation,
                output_goal_text=output_goal_text,
            )
        )

    if not errors:
        errors.extend(_validate_applied_state(plan, response))

    return errors


def validate_amend_wave_responses(
    plan: PlanState,
    batches: list[tuple[list[str], AgentResponse]],
    *,
    plan_digest: str,
    output_goal_text: str,
    eligible_ids: set[str] | None = None,
) -> list[str]:
    """Validate concurrent amend batch responses against one plan snapshot."""
    updated = plan
    for selected_ids, response in batches:
        if response.plan_digest != plan_digest:
            return [
                f"Transaction plan_digest mismatch: expected {plan_digest}, "
                f"got {response.plan_digest}"
            ]
        errors = validate_amend_response(
            updated,
            response,
            selected_ids=selected_ids,
            output_goal_text=output_goal_text,
            eligible_ids=eligible_ids,
        )
        if errors:
            return errors
        try:
            updated = apply_response(updated, response)
        except ValueError as exc:
            return [str(exc)]

    return structural_errors(updated)


def validate_wave_responses(
    plan: PlanState,
    batches: list[tuple[list[str], AgentResponse]],
    *,
    plan_digest: str,
    output_goal_text: str,
    limits: PlanningLimits,
    eligible_ids: set[str] | None = None,
) -> list[str]:
    """Validate one or more batch responses against cumulative plan state."""
    all_update_targets: list[str] = []
    updated = plan
    for selected_ids, response in batches:
        if response.plan_digest != plan_digest:
            return [
                f"Transaction plan_digest mismatch: expected {plan_digest}, "
                f"got {response.plan_digest}"
            ]
        errors = validate_response(
            updated,
            response,
            selected_ids=selected_ids,
            output_goal_text=output_goal_text,
            limits=limits,
            eligible_ids=eligible_ids,
        )
        if errors:
            return errors
        all_update_targets.extend(update.node_id for update in response.updates)
        try:
            updated = apply_response(updated, response)
        except ValueError as exc:
            return [str(exc)]

    errors = _validate_cross_batch_update_conflicts(all_update_targets)
    if errors:
        return errors

    return structural_errors(updated)


def validate_patch_only_response(
    plan: PlanState,
    response: AgentResponse,
    *,
    plan_digest: str,
    output_goal_text: str,
    disposition_only: bool = False,
) -> list[str]:
    """Validate transactions that patch existing items without primary operations."""
    if response.plan_digest != plan_digest:
        return [
            f"Transaction plan_digest mismatch: expected {plan_digest}, "
            f"got {response.plan_digest}"
        ]
    if not response.updates:
        return ["Patch-only transaction must include at least one update"]
    if disposition_only and response.operations:
        return ["Disposition transactions must not include planning operations"]

    if disposition_only:
        errors = _validate_disposition_updates(
            plan,
            response.updates,
            output_goal_text=output_goal_text,
        )
    else:
        selected_set = set(response.selected_items)
        if not selected_set:
            return [
                "Patch-only batch transactions require selected_items from select-batch"
            ]
        errors = _validate_updates(
            plan,
            response.updates,
            selected_ids=selected_set,
            output_goal_text=output_goal_text,
        )
    if errors:
        return errors
    return _validate_applied_state(plan, response)


def _validate_disposition_updates(
    plan: PlanState,
    updates: list[UpdateItemOperation],
    *,
    output_goal_text: str,
) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for update in updates:
        node_id = update.node_id
        if node_id in seen:
            errors.append(f"Duplicate update for node: {node_id}")
            continue
        seen.add(node_id)
        item = plan.item_by_id(node_id)
        if item is None:
            errors.append(f"Unknown update node id: {node_id}")
            continue
        errors.extend(
            _validate_update_item(
                plan,
                item,
                update,
                output_goal_text=output_goal_text,
            )
        )
    return errors


def _validate_eligible_selection(
    selected_ids: list[str],
    eligible_ids: set[str] | None,
) -> list[str]:
    if eligible_ids is None:
        return []
    invalid = set(selected_ids) - eligible_ids
    if not invalid:
        return []
    return [
        "Selected nodes are not eligible in this iteration: "
        + ", ".join(sorted(invalid))
    ]


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
    del plan, batches
    return []


def _validate_updates(
    plan: PlanState,
    updates: list[UpdateItemOperation],
    *,
    selected_ids: set[str],
    output_goal_text: str,
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
        errors.extend(
            _validate_update_item(
                plan,
                item,
                update,
                output_goal_text=output_goal_text,
            )
        )

    return errors


def _validate_update_item(
    plan: PlanState,
    item: PlanItem,
    update: UpdateItemOperation,
    *,
    output_goal_text: str,
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
    if _is_implementation_goal(output_goal_text):
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
    output_goal_text: str,
) -> list[str]:
    if isinstance(operation, ExpandOperation):
        return _validate_expand(plan, item, operation, limits=limits)
    if isinstance(operation, MarkActionableOperation):
        return _validate_actionable(
            plan,
            item,
            operation,
            output_goal_text=output_goal_text,
        )
    if isinstance(operation, MarkBlockedOperation):
        return _validate_blocked(item, operation)
    if isinstance(operation, MarkOutOfScopeOperation):
        return _validate_out_of_scope(item, operation)
    return [f"Unsupported operation type for node {item.id}"]


def _validate_revise_actionable(
    plan: PlanState,
    item: PlanItem,
    operation: ReviseActionableOperation,
    *,
    output_goal_text: str,
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
    if _is_implementation_goal(output_goal_text):
        if not outputs:
            errors.append(
                f"Revise on {item.id} requires expected_outputs for this output goal"
            )
        if not criteria:
            errors.append(
                f"Revise on {item.id} requires acceptance_criteria "
                "for this output goal"
            )
    if not is_leaf(plan, item.id):
        errors.append(
            f"Revise on {item.id} must target an actionable leaf; use reopen "
            "when the branch structure must change"
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

    if item.depth >= limits.max_depth:
        errors.append(
            f"Expand on {item.id} is not allowed at depth {item.depth} "
            f"(max_depth={limits.max_depth}). Use mark_actionable and capture "
            "remaining detail in notes, expected_outputs, acceptance_criteria, "
            "risks, or open_questions."
        )

    if len(operation.children) > limits.max_children_per_expansion:
        errors.append(
            f"Expand on {item.id} exceeds max children "
            f"({len(operation.children)} > {limits.max_children_per_expansion}). "
            "Group related concerns into fewer children or use mark_actionable with "
            "rich notes, expected_outputs, acceptance_criteria, risks, or "
            "open_questions for ancillary detail."
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
    *,
    output_goal_text: str,
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
    if _is_implementation_goal(output_goal_text):
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
    if not is_leaf(plan, item.id):
        errors.append(
            f"Actionable item {item.id} must be a leaf; expand it instead"
        )
    return errors


def _validate_blocked(
    item: PlanItem,
    operation: MarkBlockedOperation,
) -> list[str]:
    errors = _validate_root_metadata(
        item,
        title=operation.title,
        objective=operation.objective,
        operation_name="Mark blocked",
    )
    if not operation.reason.strip():
        errors.append(f"Blocked item {item.id} requires a reason")

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
    return []

