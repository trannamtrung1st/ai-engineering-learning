"""Durable planning-state artifact management."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from top_down_planning.digest import digest_text
from top_down_planning.models import (
    BranchStatus,
    CoverageMapping,
    DiscoveredConstraint,
    FindingDispositionRecord,
    FrozenDecision,
    PlanningAssumption,
    PlanningState,
    PlanningStateUpdate,
    RejectedAlternative,
    CrossBranchDependency,
    CheckpointFinding,
)


def new_planning_state() -> PlanningState:
    return PlanningState()


def compute_planning_state_digest(state: PlanningState) -> str:
    payload = state.model_dump(mode="json", exclude={"updated_at"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return digest_text(canonical)


def merge_planning_state_update(
    state: PlanningState,
    update: PlanningStateUpdate | None,
) -> PlanningState:
    if update is None:
        return state
    merged = state.model_copy(deep=True)
    merged.frozen_decisions = _merge_by_id(
        merged.frozen_decisions,
        update.frozen_decisions,
        key="id",
    )
    merged.assumptions = _merge_by_id(
        merged.assumptions,
        update.assumptions,
        key="id",
    )
    merged.open_questions = _dedupe_strings(
        merged.open_questions + update.open_questions
    )
    merged.coverage_map = _merge_by_key(
        merged.coverage_map,
        update.coverage_map,
        key_fn=lambda item: item.requirement,
    )
    merged.branch_status = _merge_by_key(
        merged.branch_status,
        update.branch_status,
        key_fn=lambda item: item.branch_id,
    )
    merged.cross_branch_dependencies = _merge_by_key(
        merged.cross_branch_dependencies,
        update.cross_branch_dependencies,
        key_fn=lambda item: (item.from_branch, item.to_branch, item.kind),
    )
    merged.rejected_alternatives = _merge_by_id(
        merged.rejected_alternatives,
        update.rejected_alternatives,
        key="id",
    )
    merged.discovered_constraints = _merge_by_id(
        merged.discovered_constraints,
        update.discovered_constraints,
        key="id",
    )
    merged.review_findings = _merge_by_id(
        merged.review_findings,
        update.review_findings,
        key="id",
    )
    merged.finding_dispositions = _merge_by_key(
        merged.finding_dispositions,
        update.finding_dispositions,
        key_fn=lambda item: item.finding_id,
    )
    merged.updated_at = datetime.now(timezone.utc)
    return merged


def format_planning_state_yaml(state: PlanningState) -> str:
    import yaml

    payload = state.model_dump(mode="json")
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def unresolved_finding_ids(state: PlanningState) -> list[str]:
    disposition_ids = {record.finding_id for record in state.finding_dispositions}
    return [
        finding.id
        for finding in state.review_findings
        if finding.id not in disposition_ids
    ]


def _merge_by_id(existing: list, incoming: list, *, key: str) -> list:
    if not incoming:
        return existing
    index = {getattr(item, key): item for item in existing}
    for item in incoming:
        index[getattr(item, key)] = item
    return list(index.values())


def _merge_by_key(existing: list, incoming: list, *, key_fn) -> list:
    if not incoming:
        return existing
    index = {key_fn(item): item for item in existing}
    for item in incoming:
        index[key_fn(item)] = item
    return list(index.values())


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        stripped = value.strip()
        if not stripped or stripped in seen:
            continue
        seen.add(stripped)
        result.append(stripped)
    return result


__all__ = [
    "BranchStatus",
    "CheckpointFinding",
    "CoverageMapping",
    "CrossBranchDependency",
    "DiscoveredConstraint",
    "FindingDispositionRecord",
    "FrozenDecision",
    "PlanningAssumption",
    "PlanningState",
    "PlanningStateUpdate",
    "RejectedAlternative",
    "compute_planning_state_digest",
    "format_planning_state_yaml",
    "merge_planning_state_update",
    "new_planning_state",
    "unresolved_finding_ids",
]
