"""Targeted branch revision helpers."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from top_down_planning.completeness import is_leaf
from top_down_planning.models import (
    DecompositionStatus,
    PlanState,
    ReadinessStatus,
    ReviewFinding,
    RevisionMode,
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


def _collapse_node_targets(plan: PlanState, node_ids: list[str]) -> list[str]:
    """Return minimal node-id set, dropping descendants of other cited ids."""
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
    node_ids = [
        node_id
        for finding in findings
        if finding.revision_mode == RevisionMode.REOPEN
        for node_id in finding.node_ids
    ]
    if not node_ids:
        return []
    return _collapse_node_targets(plan, node_ids)


def amend_targets_from_findings(findings: list[ReviewFinding]) -> list[str]:
    node_ids = [
        node_id
        for finding in findings
        if finding.revision_mode == RevisionMode.AMEND
        for node_id in finding.node_ids
    ]
    return list(dict.fromkeys(node_ids))


@dataclass
class RevisionApplyResult:
    plan: PlanState
    reopened_nodes: list[str] = field(default_factory=list)
    amend_node_ids: list[str] = field(default_factory=list)
    annotated_node_ids: list[str] = field(default_factory=list)


def apply_annotations_to_plan(
    plan: PlanState,
    findings: list[ReviewFinding],
) -> tuple[PlanState, list[str]]:
    updated = copy.deepcopy(plan)
    annotated: list[str] = []
    for finding in findings:
        if finding.revision_mode != RevisionMode.ANNOTATE:
            continue
        note = f"[Review {finding.severity.value}/{finding.category.value}] "
        note += finding.description.strip()
        if finding.recommended_change.strip():
            note += f" Recommended: {finding.recommended_change.strip()}"
        if not finding.node_ids:
            continue
        for node_id in finding.node_ids:
            item = updated.item_by_id(node_id)
            if item is None:
                continue
            item.notes.append(note)
            if node_id not in annotated:
                annotated.append(node_id)
    return updated, annotated


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


def validate_amend_target(plan: PlanState, node_id: str) -> list[str]:
    item = plan.item_by_id(node_id)
    if item is None:
        return [f"Unknown node id: {node_id}"]
    if item.decomposition_status != DecompositionStatus.ACTIONABLE:
        return [
            f"Node {node_id} is not amendable "
            f"(status={item.decomposition_status.value}); use revision_mode=reopen "
            "when the branch structure must change"
        ]
    if not is_leaf(plan, node_id):
        return [
            f"Node {node_id} is not amendable because it is not a leaf; "
            "use revision_mode=reopen when the branch structure must change"
        ]
    return []


def filter_amend_targets_after_reopen(
    *,
    pre_reopen_plan: PlanState,
    post_reopen_plan: PlanState,
    amend_targets: list[str],
    reopened_nodes: list[str],
) -> list[str]:
    removed: set[str] = set()
    for node_id in reopened_nodes:
        removed.add(node_id)
        removed.update(descendant_ids(pre_reopen_plan, node_id))
    kept: list[str] = []
    for node_id in amend_targets:
        if node_id in removed:
            continue
        item = post_reopen_plan.item_by_id(node_id)
        if item is None or item.decomposition_status != DecompositionStatus.ACTIONABLE:
            continue
        if not is_leaf(post_reopen_plan, node_id):
            continue
        kept.append(node_id)
    return kept


def apply_revision_from_findings(
    plan: PlanState,
    findings: list[ReviewFinding],
) -> RevisionApplyResult:
    """Apply annotate, reopen, and amend targeting from review findings."""
    updated, annotated = apply_annotations_to_plan(plan, findings)
    pre_reopen_plan = copy.deepcopy(updated)

    reopen_targets = revision_targets_from_findings(updated, findings)
    reopened: list[str] = []
    for node_id in reopen_targets:
        errors = validate_reopen_branch(updated, node_id)
        if errors:
            raise ValueError("; ".join(errors))
        updated = reopen_branch(updated, node_id)
        reopened.append(node_id)

    amend_targets = amend_targets_from_findings(findings)
    amend_targets = filter_amend_targets_after_reopen(
        pre_reopen_plan=pre_reopen_plan,
        post_reopen_plan=updated,
        amend_targets=amend_targets,
        reopened_nodes=reopened,
    )
    for node_id in amend_targets:
        errors = validate_amend_target(updated, node_id)
        if errors:
            raise ValueError("; ".join(errors))

    return RevisionApplyResult(
        plan=updated,
        reopened_nodes=reopened,
        amend_node_ids=amend_targets,
        annotated_node_ids=annotated,
    )


def _depth(plan: PlanState, node_id: str) -> int:
    item = plan.item_by_id(node_id)
    return item.depth if item is not None else 0
