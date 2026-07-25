"""Driver-owned workspace progress snapshot derived from item YAML and run state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from todos_tool.manifest import Workspace
from todos_tool.models import (
    CommitState,
    ItemStatus,
    Phase,
    RunState,
    TodoItem,
    Transition,
)
from todos_tool.persistence import load_state, write_json
from todos_tool.project_context import ProjectContext
from todos_tool.scheduler import readiness_rows
from todos_tool.validation_runner import resolve_validation_commands

SUPPORTED_PROGRESS_SCHEMA_VERSION = 1

GateStatus = Literal["pending", "passed", "failed", "stall", "n/a"]


@dataclass
class ChecklistProgress:
    done: int
    total: int
    current_step_id: str | None = None
    current_step_text: str | None = None
    open_step_ids: list[str] = field(default_factory=list)
    done_step_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "done": self.done,
            "total": self.total,
        }
        if self.current_step_id is not None:
            payload["current_step_id"] = self.current_step_id
        if self.current_step_text is not None:
            payload["current_step_text"] = self.current_step_text
        if self.open_step_ids:
            payload["open_step_ids"] = list(self.open_step_ids)
        if self.done_step_ids:
            payload["done_step_ids"] = list(self.done_step_ids)
        return payload


@dataclass
class GateSnapshot:
    status: GateStatus
    passed: int = 0
    total: int = 0
    mode: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status}
        if self.mode is not None:
            payload["mode"] = self.mode
        if self.total:
            payload["passed"] = self.passed
            payload["total"] = self.total
        return payload


@dataclass
class ItemProgressRow:
    id: str
    title: str
    status: str
    ready: str
    phase: str
    checklist: ChecklistProgress

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "ready": self.ready,
            "phase": self.phase,
            "checklist": self.checklist.to_dict(),
        }


@dataclass
class CurrentProgress:
    item_id: str
    title: str
    phase: str
    logical_attempt: int
    checklist: ChecklistProgress
    validation: GateSnapshot
    evidence: GateSnapshot

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "title": self.title,
            "phase": self.phase,
            "logical_attempt": self.logical_attempt,
            "checklist": self.checklist.to_dict(),
            "validation": self.validation.to_dict(),
            "evidence": self.evidence.to_dict(),
        }


@dataclass
class ProgressSummary:
    items_done: int
    items_total: int
    items_superseded: int
    checklist_done: int
    checklist_total: int
    status_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "items_done": self.items_done,
            "items_total": self.items_total,
            "items_superseded": self.items_superseded,
            "checklist_done": self.checklist_done,
            "checklist_total": self.checklist_total,
            "status_counts": dict(self.status_counts),
        }


@dataclass
class ProgressSnapshot:
    schema_version: int = SUPPORTED_PROGRESS_SCHEMA_VERSION
    updated_at: datetime | None = None
    summary: ProgressSummary = field(default_factory=lambda: ProgressSummary(0, 0, 0, 0, 0))
    current: CurrentProgress | None = None
    items: list[ItemProgressRow] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        if self.updated_at is None:
            raise ValueError("ProgressSnapshot.updated_at is required")
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "updated_at": self.updated_at.isoformat(),
            "summary": self.summary.to_dict(),
            "items": [row.to_dict() for row in self.items],
        }
        if self.current is not None:
            payload["current"] = self.current.to_dict()
        return payload


def progress_path(workspace: Workspace) -> Path:
    return workspace.todos_dir / "runs" / "progress.json"


def progress_snapshot_rel_path(todos_dir: str = "todos") -> str:
    return f"{todos_dir.rstrip('/')}/runs/progress.json"


def _is_commit_in_progress(state: RunState | None) -> bool:
    return (
        state is not None
        and state.phase == Phase.COMMIT
        and state.commit_state != CommitState.COMPLETED
    )


def _checklist_progress(item: TodoItem) -> ChecklistProgress:
    done_ids = [entry.id for entry in item.checklist if entry.done]
    open_entries = [entry for entry in item.checklist if not entry.done]
    open_ids = [entry.id for entry in open_entries]
    current = open_entries[0] if open_entries else None
    return ChecklistProgress(
        done=len(done_ids),
        total=len(item.checklist),
        current_step_id=current.id if current is not None else None,
        current_step_text=current.text if current is not None else None,
        open_step_ids=open_ids,
        done_step_ids=done_ids,
    )


def _validation_gate_snapshot(
    *,
    validation_commands: list[str],
    state: RunState | None,
) -> GateSnapshot:
    if not validation_commands and not (state and state.validation_results):
        return GateSnapshot(status="n/a")

    if state is None or not state.validation_results:
        return GateSnapshot(status="pending")

    if state.validation_attempt != state.logical_attempt:
        return GateSnapshot(status="pending")

    passed = sum(1 for result in state.validation_results if result.passed)
    total = len(state.validation_results)
    if total == 0:
        return GateSnapshot(status="pending")
    if all(result.passed for result in state.validation_results):
        return GateSnapshot(status="passed", passed=passed, total=total)
    return GateSnapshot(status="failed", passed=passed, total=total)


def _evidence_gate_snapshot(
    item: TodoItem,
    state: RunState | None,
) -> GateSnapshot:
    if not item.evidence.commands:
        return GateSnapshot(status="n/a")

    mode = state.evidence_mode.value if state and state.evidence_mode else None

    if state and state.last_transition == Transition.EVIDENCE_STALL:
        passed = sum(1 for result in state.evidence_results if result.passed)
        total = len(state.evidence_results)
        return GateSnapshot(status="stall", passed=passed, total=total, mode=mode)

    if state is None or not state.evidence_results:
        return GateSnapshot(status="pending", mode=mode)

    passed = sum(1 for result in state.evidence_results if result.passed)
    total = len(state.evidence_results)
    if total == 0:
        return GateSnapshot(status="pending", mode=mode)
    if all(result.passed for result in state.evidence_results):
        return GateSnapshot(status="passed", passed=passed, total=total, mode=mode)
    return GateSnapshot(status="failed", passed=passed, total=total, mode=mode)


def build_progress(
    workspace: Workspace,
    *,
    project_context: ProjectContext | None = None,
) -> ProgressSnapshot:
    """Build a progress snapshot from item YAML and per-item run state."""
    rows_by_id = {row["id"]: row for row in readiness_rows(workspace)}
    active_items = [
        item for item in workspace.items if item.status == ItemStatus.IN_PROGRESS
    ]
    active_item = active_items[0] if active_items else None

    countable_items = [
        item for item in workspace.items if item.status != ItemStatus.SUPERSEDED
    ]
    superseded_count = len(workspace.items) - len(countable_items)
    status_counts: dict[str, int] = {}
    checklist_done = 0
    checklist_total = 0
    items_done = 0

    item_rows: list[ItemProgressRow] = []
    for item in workspace.items:
        status_counts[item.status.value] = status_counts.get(item.status.value, 0) + 1
        checklist = _checklist_progress(item)
        state = load_state(workspace.runs_dir(item.id))
        if item.status != ItemStatus.SUPERSEDED:
            checklist_done += checklist.done
            checklist_total += checklist.total
            if item.status == ItemStatus.DONE and not _is_commit_in_progress(state):
                items_done += 1

        phase = state.phase.value if state else "idle"
        ready = rows_by_id.get(item.id, {}).get("ready", "-")
        item_rows.append(
            ItemProgressRow(
                id=item.id,
                title=item.title,
                status=item.status.value,
                ready=ready,
                phase=phase,
                checklist=checklist,
            )
        )

    current: CurrentProgress | None = None
    if active_item is not None:
        state = load_state(workspace.runs_dir(active_item.id))
        validation_commands = resolve_validation_commands(
            workspace.manifest,
            active_item,
            project_context=project_context,
        )
        current = CurrentProgress(
            item_id=active_item.id,
            title=active_item.title,
            phase=state.phase.value if state else "idle",
            logical_attempt=state.logical_attempt if state else 0,
            checklist=_checklist_progress(active_item),
            validation=_validation_gate_snapshot(
                validation_commands=validation_commands,
                state=state,
            ),
            evidence=_evidence_gate_snapshot(active_item, state),
        )

    return ProgressSnapshot(
        updated_at=datetime.now(timezone.utc),
        summary=ProgressSummary(
            items_done=items_done,
            items_total=len(countable_items),
            items_superseded=superseded_count,
            checklist_done=checklist_done,
            checklist_total=checklist_total,
            status_counts=status_counts,
        ),
        current=current,
        items=item_rows,
    )


def write_progress(
    workspace: Workspace,
    *,
    project_context: ProjectContext | None = None,
) -> ProgressSnapshot:
    """Rebuild and atomically write the workspace progress snapshot."""
    snapshot = build_progress(workspace, project_context=project_context)
    write_json(progress_path(workspace), snapshot.to_dict())
    return snapshot


def format_status_summary(snapshot: ProgressSnapshot) -> str:
    """One-line summary for `todos-tool status`."""
    summary = snapshot.summary
    parts = [
        f"items {summary.items_done}/{summary.items_total} done",
        f"checklist {summary.checklist_done}/{summary.checklist_total}",
    ]
    if summary.items_superseded:
        parts.append(f"superseded {summary.items_superseded}")

    current = snapshot.current
    if current is not None:
        current_bits = [
            current.item_id,
            current.phase,
        ]
        if current.logical_attempt:
            current_bits.append(f"a{current.logical_attempt}")
        if current.checklist.current_step_id:
            step = current.checklist.current_step_id
            if current.checklist.total:
                step = (
                    f"{step} ({current.checklist.done}/{current.checklist.total})"
                )
            current_bits.append(f"step {step}")
        parts.append("current " + " ".join(current_bits))
    return " | ".join(parts)


def format_prompt_progress(
    snapshot: ProgressSnapshot,
    *,
    item_id: str,
    todos_dir: str = "todos",
) -> str:
    """Short markdown block for work/review prompts."""
    summary = snapshot.summary
    lines = [
        "## Workspace progress",
        f"- Items done: {summary.items_done}/{summary.items_total}",
        f"- Checklist done: {summary.checklist_done}/{summary.checklist_total}",
        (
            "- Progress snapshot: driver-owned read-only file at "
            f"`{progress_snapshot_rel_path(todos_dir)}` "
            "(checklist YAML remains authoritative)."
        ),
    ]

    current = snapshot.current
    if current is not None and current.item_id == item_id:
        lines.append(
            f"- Active item `{current.item_id}`: phase `{current.phase}`, "
            f"attempt {current.logical_attempt}."
        )
        if current.checklist.total:
            lines.append(
                f"- Item checklist: {current.checklist.done}/{current.checklist.total} done."
            )
        if current.checklist.current_step_id:
            lines.append(
                f"- Current step: `{current.checklist.current_step_id}` — "
                f"{current.checklist.current_step_text or '(no text)'}."
            )
        if current.checklist.open_step_ids:
            open_ids = ", ".join(f"`{step_id}`" for step_id in current.checklist.open_step_ids)
            lines.append(f"- Open steps: {open_ids}.")
        if current.validation.status != "n/a":
            validation = current.validation
            detail = validation.status
            if validation.total:
                detail = f"{detail} ({validation.passed}/{validation.total})"
            lines.append(f"- Validation gate: {detail}.")
        if current.evidence.status != "n/a":
            evidence = current.evidence
            detail = evidence.status
            if evidence.mode:
                detail = f"{evidence.mode} {detail}"
            if evidence.total:
                detail = f"{detail} ({evidence.passed}/{evidence.total})"
            lines.append(f"- Evidence gate: {detail}.")
    return "\n".join(lines)
