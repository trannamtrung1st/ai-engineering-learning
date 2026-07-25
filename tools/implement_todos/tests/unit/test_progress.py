"""Unit tests for workspace progress snapshots."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from tests.helpers import write_todos
from todos_tool.cli import main
from todos_tool.manifest import load_workspace
from todos_tool.models import (
    CommitState,
    EvidenceCommandResult,
    EvidenceMode,
    ItemStatus,
    ItemType,
    Phase,
    TodoItem,
    Transition,
    ValidationCommandResult,
)
from todos_tool.persistence import new_run_state, record_transition, save_state
from todos_tool.progress import (
    ChecklistProgress,
    CurrentProgress,
    GateSnapshot,
    ProgressSnapshot,
    ProgressSummary,
    build_progress,
    format_prompt_progress,
    format_status_summary,
    progress_path,
    write_progress,
)
from todos_tool.prompts import build_review_prompt, build_work_prompt


def _sample_items() -> list[dict]:
    return [
        {
            "version": 1,
            "id": "SETUP-001",
            "title": "Setup",
            "type": "feature",
            "status": "done",
            "priority": 10,
            "depends_on": [],
            "description": "Bootstrap.",
            "acceptance_criteria": ["Ready."],
            "checklist": [
                {"id": "ck-a", "text": "First", "done": True},
                {"id": "ck-b", "text": "Second", "done": True},
            ],
            "_file": "items/000-setup.yaml",
        },
        {
            "version": 1,
            "id": "TASK-001",
            "title": "Feature",
            "type": "feature",
            "status": "in_progress",
            "priority": 100,
            "depends_on": ["SETUP-001"],
            "description": "Build feature.",
            "acceptance_criteria": ["Works."],
            "checklist": [
                {"id": "ck-layout", "text": "Inspect layout", "done": True},
                {"id": "ck-module", "text": "Add module", "done": False},
                {"id": "ck-tests", "text": "Add tests", "done": False},
            ],
            "validation": {"commands": ["pytest"]},
            "evidence": {
                "commands": [
                    {"command": "pytest", "cwd": "."},
                ]
            },
            "_file": "items/001-feature.yaml",
        },
        {
            "version": 1,
            "id": "TASK-002",
            "title": "Follow-up",
            "type": "fix",
            "status": "pending",
            "priority": 200,
            "depends_on": ["TASK-001"],
            "description": "Fix bug.",
            "acceptance_criteria": ["Fixed."],
            "_file": "items/002-fix.yaml",
        },
        {
            "version": 1,
            "id": "TASK-OLD",
            "title": "Superseded",
            "type": "refactor",
            "status": "superseded",
            "priority": 300,
            "depends_on": [],
            "description": "Old work.",
            "acceptance_criteria": ["N/A."],
            "checklist": [
                {"id": "ck-old", "text": "Old step", "done": False},
            ],
            "_file": "items/003-old.yaml",
        },
    ]


def test_build_progress_counts_and_current_step(tmp_path: Path) -> None:
    write_todos(tmp_path, _sample_items())
    ws = load_workspace(tmp_path)

    snapshot = build_progress(ws)

    assert snapshot.summary.items_done == 1
    assert snapshot.summary.items_total == 3
    assert snapshot.summary.items_superseded == 1
    assert snapshot.summary.checklist_done == 3
    assert snapshot.summary.checklist_total == 5
    assert snapshot.summary.status_counts["done"] == 1
    assert snapshot.summary.status_counts["in_progress"] == 1
    assert snapshot.summary.status_counts["superseded"] == 1

    assert snapshot.current is not None
    assert snapshot.current.item_id == "TASK-001"
    assert snapshot.current.checklist.done == 1
    assert snapshot.current.checklist.total == 3
    assert snapshot.current.checklist.current_step_id == "ck-module"
    assert snapshot.current.checklist.open_step_ids == ["ck-module", "ck-tests"]


def test_build_progress_reflects_validation_and_evidence_state(tmp_path: Path) -> None:
    write_todos(tmp_path, _sample_items())
    ws = load_workspace(tmp_path)
    runs_dir = ws.runs_dir("TASK-001")
    state = new_run_state("TASK-001", "abc123")
    state.phase = Phase.WORK
    state.logical_attempt = 2
    state.validation_attempt = 2
    state.evidence_mode = EvidenceMode.DRIVER
    state.validation_results = [
        ValidationCommandResult(command="pytest", passed=False, exit_code=1),
    ]
    state.evidence_results = [
        EvidenceCommandResult(
            command="pytest",
            cwd=".",
            passed=True,
            source="driver",
            exit_code=0,
        )
    ]
    record_transition(runs_dir, state, Transition.VALIDATION_FAILED)
    save_state(runs_dir, state)

    snapshot = build_progress(ws)
    assert snapshot.current is not None
    assert snapshot.current.validation.status == "failed"
    assert snapshot.current.validation.passed == 0
    assert snapshot.current.validation.total == 1
    assert snapshot.current.evidence.status == "passed"
    assert snapshot.current.evidence.mode == "driver"
    assert snapshot.current.evidence.passed == 1
    assert snapshot.current.evidence.total == 1


def test_build_progress_marks_evidence_stall(tmp_path: Path) -> None:
    write_todos(tmp_path, _sample_items())
    ws = load_workspace(tmp_path)
    runs_dir = ws.runs_dir("TASK-001")
    state = new_run_state("TASK-001", "abc123")
    state.evidence_mode = EvidenceMode.CAPTURED
    state.evidence_results = [
        EvidenceCommandResult(
            command="pytest",
            cwd=".",
            passed=False,
            source="captured",
            exit_code=1,
        )
    ]
    record_transition(runs_dir, state, Transition.EVIDENCE_STALL)
    save_state(runs_dir, state)

    snapshot = build_progress(ws)
    assert snapshot.current is not None
    assert snapshot.current.evidence.status == "stall"


def test_build_progress_marks_validation_pending_for_manifest_project_check(
    tmp_path: Path,
) -> None:
    items = _sample_items()
    items[1]["validation"] = {"commands": []}
    write_todos(tmp_path, items, settings={"project_check": "pytest"})
    ws = load_workspace(tmp_path)

    snapshot = build_progress(ws)
    assert snapshot.current is not None
    assert snapshot.current.validation.status == "pending"


def test_build_progress_ignores_stale_validation_results(tmp_path: Path) -> None:
    write_todos(tmp_path, _sample_items())
    ws = load_workspace(tmp_path)
    runs_dir = ws.runs_dir("TASK-001")
    state = new_run_state("TASK-001", "abc123")
    state.logical_attempt = 2
    state.validation_attempt = 1
    state.validation_results = [
        ValidationCommandResult(command="pytest", passed=True, exit_code=0),
    ]
    save_state(runs_dir, state)

    snapshot = build_progress(ws)
    assert snapshot.current is not None
    assert snapshot.current.validation.status == "pending"


def test_build_progress_excludes_committing_item_from_done_count(tmp_path: Path) -> None:
    write_todos(tmp_path, _sample_items())
    ws = load_workspace(tmp_path)
    item = ws.get("SETUP-001")
    assert item is not None
    item.status = ItemStatus.DONE
    runs_dir = ws.runs_dir("SETUP-001")
    state = new_run_state("SETUP-001", "abc123")
    state.phase = Phase.COMMIT
    state.commit_state = CommitState.STARTED
    save_state(runs_dir, state)

    snapshot = build_progress(ws)
    assert snapshot.summary.items_done == 0


def test_build_progress_blocked_item_shows_idle_phase(tmp_path: Path) -> None:
    write_todos(tmp_path, _sample_items())
    ws = load_workspace(tmp_path)
    item = ws.get("TASK-001")
    assert item is not None
    item.status = ItemStatus.BLOCKED
    runs_dir = ws.runs_dir("TASK-001")
    state = new_run_state("TASK-001", "abc123")
    state.phase = Phase.IDLE
    record_transition(runs_dir, state, Transition.ITEM_BLOCKED)
    save_state(runs_dir, state)

    snapshot = build_progress(ws)
    row = next(row for row in snapshot.items if row.id == "TASK-001")
    assert row.status == "blocked"
    assert row.phase == "idle"
    assert snapshot.current is None


def test_format_prompt_progress_uses_custom_todos_dir(tmp_path: Path) -> None:
    write_todos(tmp_path, _sample_items())
    ws = load_workspace(tmp_path)
    snapshot = build_progress(ws)

    text = format_prompt_progress(
        snapshot,
        item_id="TASK-001",
        todos_dir="backlog",
    )
    assert "`backlog/runs/progress.json`" in text


def test_write_progress_creates_json_file(tmp_path: Path) -> None:
    write_todos(tmp_path, _sample_items())
    ws = load_workspace(tmp_path)

    snapshot = write_progress(ws)
    path = progress_path(ws)
    assert path.is_file()

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["summary"]["items_done"] == snapshot.summary.items_done
    assert payload["current"]["item_id"] == "TASK-001"


def test_format_status_summary_includes_current_step() -> None:
    snapshot = ProgressSnapshot(
        summary=ProgressSummary(
            items_done=1,
            items_total=3,
            items_superseded=1,
            checklist_done=3,
            checklist_total=5,
        ),
        current=CurrentProgress(
            item_id="TASK-001",
            title="Feature",
            phase="work",
            logical_attempt=2,
            checklist=ChecklistProgress(
                done=1,
                total=3,
                current_step_id="ck-module",
            ),
            validation=GateSnapshot(status="failed", passed=0, total=1),
            evidence=GateSnapshot(status="pending", mode="driver"),
        ),
    )

    summary = format_status_summary(snapshot)
    assert "items 1/3 done" in summary
    assert "checklist 3/5" in summary
    assert "current TASK-001 work a2 step ck-module (1/3)" in summary


def test_format_prompt_progress_for_active_item(tmp_path: Path) -> None:
    write_todos(tmp_path, _sample_items())
    ws = load_workspace(tmp_path)
    snapshot = build_progress(ws)

    text = format_prompt_progress(snapshot, item_id="TASK-001")
    assert "## Workspace progress" in text
    assert "Items done: 1/3" in text
    assert "Current step: `ck-module`" in text
    assert "Open steps: `ck-module`, `ck-tests`" in text
    assert "driver-owned read-only" in text


def test_work_prompt_includes_progress_section() -> None:
    item = TodoItem(
        id="TASK-001",
        title="Feature",
        type=ItemType.FEATURE,
        description="Build feature.",
        acceptance_criteria=["Works."],
    )
    progress = "## Workspace progress\n- Items done: 1/3"

    prompt = build_work_prompt(
        item,
        logical_attempt=1,
        resolved_commands=[],
        progress_section=progress,
    )

    assert progress in prompt
    assert prompt.index("## Workspace progress") < prompt.index("## Hard constraints")


def test_review_prompt_includes_progress_section() -> None:
    item = TodoItem(
        id="TASK-001",
        title="Feature",
        type=ItemType.FEATURE,
        description="Build feature.",
        acceptance_criteria=["Works."],
    )
    progress = "## Workspace progress\n- Items done: 1/3"

    prompt = build_review_prompt(
        item,
        logical_attempt=1,
        work_summary="Implemented module.",
        git_diff="",
        git_status="",
        resolved_commands=[],
        progress_section=progress,
    )

    assert progress in prompt


def test_status_cli_prints_summary_and_checklist_column(tmp_path: Path) -> None:
    write_todos(tmp_path, _sample_items())
    stdout = StringIO()
    with patch("sys.stdout", stdout):
        code = main(
            [
                "status",
                "--workspace",
                str(tmp_path),
            ]
        )
    assert code == 0
    output = stdout.getvalue()
    assert "items 1/3 done" in output
    assert "checklist 3/5" in output
    assert "Checklist" in output
    assert "1/3" in output
    assert progress_path(load_workspace(tmp_path)).is_file()
