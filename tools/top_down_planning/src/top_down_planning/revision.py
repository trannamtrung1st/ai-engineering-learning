"""Targeted branch revision helpers."""

from __future__ import annotations

import copy

from top_down_planning.models import (
    DecompositionStatus,
    PlanState,
    ReadinessStatus,
    ReviewFinding,
)


def descendant_ids(plan: PlanState, node_id: str) -> set[str]:
    children_by_parent: dict[str | None, list[str]] = {}
    for item in plan.plan:
        children_by_parent.setdefault(item.parent_id, []).append(item.id)
    result: set[str] = set()
    stack = list(children_by_parent.get(node_id, []))
    while stack:
        current = stack.pop()
        if current in result:
            continue
        result.add(current)
        stack.extend(children_by_parent.get(current, []))
    return result


def collapse_revision_targets(
    plan: PlanState,
    node_ids: list[str],
) -> list[str]:
    """Return minimal set of reopen roots, dropping descendants of other targets."""
    unique = list(dict.fromkeys(node_ids))
    id_set = set(unique)
    kept = [
        node_id
        for node_id in unique
        if not any(
            node_id in descendant_ids(plan, other)
            for other in id_set
            if other != node_id
        )
    ]
    kept.sort(key=lambda item_id: (_depth(plan, item_id), item_id))
    return kept


def revision_targets_from_findings(
    plan: PlanState,
    findings: list[ReviewFinding],
) -> list[str]:
    node_ids: list[str] = []
    for finding in findings:
        node_ids.extend(finding.node_ids)
    if not node_ids:
        return []
    return collapse_revision_targets(plan, node_ids)


def reopen_branch(plan: PlanState, node_id: str) -> PlanState:
    """Remove descendants of node_id and mark the node for re-expansion."""
    updated = copy.deepcopy(plan)
    item = updated.item_by_id(node_id)
    if item is None:
        raise ValueError(f"Unknown node id: {node_id}")

    remove_ids = descendant_ids(updated, node_id)
    if remove_ids:
        updated.plan = [entry for entry in updated.plan if entry.id not in remove_ids]
        for remaining in updated.plan:
            remaining.dependencies = [
                dep for dep in remaining.dependencies if dep not in remove_ids
            ]

    item.decomposition_status = DecompositionStatus.NEEDS_EXPANSION
    item.readiness_status = ReadinessStatus.PENDING
    item.expected_outputs = []
    item.acceptance_criteria = []
    item.dependencies = []
    item.notes = []
    item.risks = []
    item.open_questions = []
    item.blocked_reason = None
    item.blocked_constraint_code = None
    item.blocked_required_min_children = None
    item.out_of_scope_reason = None
    return updated


def validate_reopen_branch(plan: PlanState, node_id: str) -> list[str]:
    item = plan.item_by_id(node_id)
    if item is None:
        return [f"Unknown node id: {node_id}"]
    if item.decomposition_status == DecompositionStatus.NEEDS_EXPANSION:
        return [f"Node {node_id} is already needs_expansion"]
    return []


def _depth(plan: PlanState, node_id: str) -> int:
    item = plan.item_by_id(node_id)
    return item.depth if item is not None else 0
