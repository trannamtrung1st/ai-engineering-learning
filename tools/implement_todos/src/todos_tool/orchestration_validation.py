"""Deterministic pre-finalization checks for orchestration state."""

from __future__ import annotations

from todos_tool.implementation_state import WorkspaceRunState
from todos_tool.models import RunState


def validate_item_ready_for_finalize(
    state: RunState,
    workspace_state: WorkspaceRunState | None = None,
) -> list[str]:
    issues: list[str] = []
    if state.validation_results and not all(
        result.passed for result in state.validation_results
    ):
        issues.append("validation results are not all passing")
    if state.evidence_results and not all(
        result.passed for result in state.evidence_results
    ):
        issues.append("evidence results are not all passing")
    if workspace_state is not None:
        unresolved = _unresolved_finding_ids(workspace_state)
        if unresolved:
            issues.append(
                f"unresolved reviewer findings: {', '.join(unresolved)}"
            )
    return issues


def _unresolved_finding_ids(state: WorkspaceRunState) -> list[str]:
    disposition_ids = {record.finding_id for record in state.finding_dispositions}
    return [
        finding.id
        for finding in state.reviewer_findings
        if finding.accepted and finding.id not in disposition_ids
    ]
