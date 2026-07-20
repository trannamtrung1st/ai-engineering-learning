"""Schema validation, dependencies, and scheduling tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.helpers import write_todos
from todos_tool.errors import SchedulingError, ValidationError
from todos_tool.manifest import load_workspace
from todos_tool.scheduler import list_ready, next_ready, readiness_rows


def test_load_valid_workspace(git_project: Path, sample_item: dict) -> None:
    write_todos(git_project, [sample_item])
    ws = load_workspace(git_project)
    assert len(ws.items) == 1
    assert ws.items[0].id == "TASK-001"


def test_duplicate_ids(git_project: Path, sample_item: dict) -> None:
    other = dict(sample_item)
    other["id"] = "TASK-001"
    write_todos(
        git_project,
        [sample_item, {**other, "title": "dup", "_file": "items/002.yaml"}],
    )
    # Force duplicate in manifest
    manifest = yaml.safe_load((git_project / "todos/manifest.yaml").read_text())
    manifest["items"] = [
        {"id": "TASK-001", "file": "items/001.yaml"},
        {"id": "TASK-001", "file": "items/002.yaml"},
    ]
    (git_project / "todos/manifest.yaml").write_text(
        yaml.safe_dump(manifest), encoding="utf-8"
    )
    with pytest.raises(ValidationError) as exc:
        load_workspace(git_project)
    assert any("Duplicate" in e for e in exc.value.errors)


def test_cycle_detection(git_project: Path, sample_item: dict) -> None:
    a = dict(sample_item)
    b = dict(sample_item)
    b["id"] = "TASK-002"
    b["depends_on"] = ["TASK-001"]
    a["depends_on"] = ["TASK-002"]
    write_todos(
        git_project,
        [a, {**b, "_file": "items/002.yaml"}],
    )
    with pytest.raises(ValidationError) as exc:
        load_workspace(git_project)
    assert any("cycle" in e.lower() for e in exc.value.errors)


def test_missing_dependency(git_project: Path, sample_item: dict) -> None:
    item = dict(sample_item)
    item["depends_on"] = ["TASK-999"]
    write_todos(git_project, [item])
    with pytest.raises(ValidationError) as exc:
        load_workspace(git_project)
    assert any("unknown item" in e for e in exc.value.errors)


def test_dependency_order(git_project: Path, sample_item: dict) -> None:
    a = dict(sample_item)
    b = dict(sample_item)
    b["id"] = "TASK-002"
    b["title"] = "Second"
    b["depends_on"] = ["TASK-001"]
    b["priority"] = 1
    write_todos(git_project, [a, {**b, "_file": "items/002.yaml"}])
    ws = load_workspace(git_project)
    ready = list_ready(ws)
    assert [i.id for i in ready] == ["TASK-001"]
    rows = readiness_rows(ws)
    assert rows[1]["ready"].startswith("waiting:")


def test_next_ready_specific(git_project: Path, sample_item: dict) -> None:
    write_todos(git_project, [sample_item])
    ws = load_workspace(git_project)
    item = next_ready(ws, "TASK-001")
    assert item.id == "TASK-001"
    with pytest.raises(SchedulingError):
        next_ready(ws, "TASK-404")
