"""Workspace-level durable orchestration state for cross-TODO handoff."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from todos_tool.errors import PersistenceError
from todos_tool.models import (
    CompletionReport,
    FindingDisposition,
    ReviewerFinding,
)
from todos_tool.persistence import _atomic_write_json


WORKSPACE_RUN_STATE_SCHEMA_VERSION = 1
WORKSPACE_RUN_STATE_FILENAME = "run-state.json"


@dataclass
class DependencyOutput:
    item_id: str
    summary: str
    commit_sha: str | None = None
    changed_paths: list[str] = field(default_factory=list)
    accepted_decisions: list[str] = field(default_factory=list)
    verification_evidence: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DependencyOutput:
        if not isinstance(data, dict):
            raise ValueError("dependency output must be a mapping")
        return cls(
            item_id=str(data["item_id"]),
            summary=str(data.get("summary", "")),
            commit_sha=data.get("commit_sha"),
            changed_paths=list(data.get("changed_paths") or []),
            accepted_decisions=list(data.get("accepted_decisions") or []),
            verification_evidence=str(data.get("verification_evidence", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "summary": self.summary,
            "commit_sha": self.commit_sha,
            "changed_paths": list(self.changed_paths),
            "accepted_decisions": list(self.accepted_decisions),
            "verification_evidence": self.verification_evidence,
        }


@dataclass
class WorkspaceRunState:
    schema_version: int = WORKSPACE_RUN_STATE_SCHEMA_VERSION
    todo_status: dict[str, str] = field(default_factory=dict)
    dependency_outputs: dict[str, DependencyOutput] = field(default_factory=dict)
    accepted_decisions: list[str] = field(default_factory=list)
    changed_surfaces: dict[str, list[str]] = field(default_factory=dict)
    verification_results: dict[str, Any] = field(default_factory=dict)
    reviewer_findings: list[ReviewerFinding] = field(default_factory=list)
    finding_dispositions: list[FindingDisposition] = field(default_factory=list)
    active_worker_chat_id: str | None = None
    active_execution_group_id: str | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkspaceRunState:
        if not isinstance(data, dict):
            raise ValueError("workspace run state must be a mapping")
        raw_version = data.get("schema_version", WORKSPACE_RUN_STATE_SCHEMA_VERSION)
        if raw_version != WORKSPACE_RUN_STATE_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported workspace run state schema version {raw_version!r}"
            )
        dependency_outputs: dict[str, DependencyOutput] = {}
        for key, value in (data.get("dependency_outputs") or {}).items():
            dependency_outputs[str(key)] = DependencyOutput.from_dict(value)
        return cls(
            schema_version=WORKSPACE_RUN_STATE_SCHEMA_VERSION,
            todo_status={
                str(key): str(value)
                for key, value in (data.get("todo_status") or {}).items()
            },
            dependency_outputs=dependency_outputs,
            accepted_decisions=list(data.get("accepted_decisions") or []),
            changed_surfaces={
                str(key): list(value)
                for key, value in (data.get("changed_surfaces") or {}).items()
            },
            verification_results=dict(data.get("verification_results") or {}),
            reviewer_findings=[
                ReviewerFinding.from_dict(entry)
                for entry in data.get("reviewer_findings") or []
            ],
            finding_dispositions=[
                FindingDisposition.from_dict(entry)
                for entry in data.get("finding_dispositions") or []
            ],
            active_worker_chat_id=data.get("active_worker_chat_id"),
            active_execution_group_id=data.get("active_execution_group_id"),
            updated_at=_parse_datetime(data.get("updated_at")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "todo_status": dict(self.todo_status),
            "dependency_outputs": {
                key: value.to_dict() for key, value in self.dependency_outputs.items()
            },
            "accepted_decisions": list(self.accepted_decisions),
            "changed_surfaces": {
                key: list(value) for key, value in self.changed_surfaces.items()
            },
            "verification_results": dict(self.verification_results),
            "reviewer_findings": [
                finding.to_dict() for finding in self.reviewer_findings
            ],
            "finding_dispositions": [
                disposition.to_dict() for disposition in self.finding_dispositions
            ],
            "active_worker_chat_id": self.active_worker_chat_id,
            "active_execution_group_id": self.active_execution_group_id,
            "updated_at": (
                self.updated_at.isoformat() if self.updated_at is not None else None
            ),
        }


def workspace_run_state_path(runs_root: Path) -> Path:
    return runs_root / WORKSPACE_RUN_STATE_FILENAME


def load_workspace_run_state(runs_root: Path) -> WorkspaceRunState:
    path = workspace_run_state_path(runs_root)
    if not path.is_file():
        return WorkspaceRunState()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return WorkspaceRunState.from_dict(data)
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise PersistenceError(
            f"Failed to load workspace run state from {path}: {exc}"
        ) from exc


def save_workspace_run_state(runs_root: Path, state: WorkspaceRunState) -> None:
    runs_root.mkdir(parents=True, exist_ok=True)
    state.updated_at = datetime.now(timezone.utc)
    _atomic_write_json(workspace_run_state_path(runs_root), state.to_dict())


def record_item_completion(
    runs_root: Path,
    report: CompletionReport,
    *,
    item_status: str,
) -> WorkspaceRunState:
    state = load_workspace_run_state(runs_root)
    state.todo_status[report.item_id] = item_status
    state.dependency_outputs[report.item_id] = DependencyOutput(
        item_id=report.item_id,
        summary=report.summary,
        commit_sha=report.commit_sha,
        changed_paths=list(report.changed_paths),
        accepted_decisions=list(report.accepted_decisions),
        verification_evidence=report.verification_evidence,
    )
    state.changed_surfaces[report.item_id] = list(report.changed_paths)
    for decision in report.accepted_decisions:
        if decision not in state.accepted_decisions:
            state.accepted_decisions.append(decision)
    save_workspace_run_state(runs_root, state)
    return state


def dependency_handoff_for_item(
    runs_root: Path,
    depends_on: list[str],
) -> list[DependencyOutput]:
    state = load_workspace_run_state(runs_root)
    outputs: list[DependencyOutput] = []
    for dep_id in depends_on:
        output = state.dependency_outputs.get(dep_id)
        if output is not None:
            outputs.append(output)
    return outputs


def record_reviewer_findings(
    runs_root: Path,
    findings: list[ReviewerFinding],
) -> WorkspaceRunState:
    state = load_workspace_run_state(runs_root)
    index = {finding.id: finding for finding in state.reviewer_findings}
    for finding in findings:
        index[finding.id] = finding
    state.reviewer_findings = list(index.values())
    save_workspace_run_state(runs_root, state)
    return state


def record_finding_dispositions(
    runs_root: Path,
    dispositions: list[FindingDisposition],
) -> WorkspaceRunState:
    state = load_workspace_run_state(runs_root)
    index = {record.finding_id: record for record in state.finding_dispositions}
    for record in dispositions:
        index[record.finding_id] = record
    state.finding_dispositions = list(index.values())
    save_workspace_run_state(runs_root, state)
    return state


def clear_active_worker_chat(
    runs_root: Path,
    *,
    group_id: str | None = None,
) -> None:
    state = load_workspace_run_state(runs_root)
    state.active_worker_chat_id = None
    if group_id is None or state.active_execution_group_id == group_id:
        state.active_execution_group_id = None
    save_workspace_run_state(runs_root, state)


def set_active_worker_chat(
    runs_root: Path,
    chat_id: str,
    *,
    group_id: str | None = None,
) -> None:
    state = load_workspace_run_state(runs_root)
    state.active_worker_chat_id = chat_id
    state.active_execution_group_id = group_id
    save_workspace_run_state(runs_root, state)


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    raise ValueError("updated_at must be an ISO-8601 timestamp")
