"""Schema validation, dependencies, and scheduling tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.helpers import write_todos
from todos_tool.errors import SchedulingError, ValidationError
from todos_tool.manifest import load_workspace
from todos_tool.model_config import resolve_model
from todos_tool.models import DEFAULT_CURSOR_MODEL, ItemStatus
from todos_tool.scheduler import _format_commit, list_ready, next_ready, readiness_rows


def test_load_valid_workspace(git_project: Path, sample_item: dict) -> None:
    write_todos(git_project, [sample_item])
    ws = load_workspace(git_project)
    assert len(ws.items) == 1
    assert ws.items[0].id == "TASK-001"
    assert ws.manifest.settings.model == DEFAULT_CURSOR_MODEL


def test_manifest_model_default_when_omitted(git_project: Path, sample_item: dict) -> None:
    write_todos(git_project, [sample_item], settings={"max_attempts": 5})
    manifest_path = git_project / "todos/manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["settings"].pop("model", None)
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    ws = load_workspace(git_project)
    assert ws.manifest.settings.model == DEFAULT_CURSOR_MODEL


def test_manifest_auto_commit_default_when_omitted(
    git_project: Path, sample_item: dict
) -> None:
    write_todos(git_project, [sample_item], settings={"max_attempts": 5})
    manifest_path = git_project / "todos/manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["settings"].pop("auto_commit", None)
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    ws = load_workspace(git_project)
    assert ws.manifest.settings.auto_commit is True


def test_manifest_auto_format_default_when_omitted(
    git_project: Path, sample_item: dict
) -> None:
    write_todos(git_project, [sample_item], settings={"max_attempts": 5})
    manifest_path = git_project / "todos/manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["settings"].pop("auto_format_before_validation", None)
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    ws = load_workspace(git_project)
    assert ws.manifest.settings.auto_format_before_validation is True


def test_manifest_model_setting(git_project: Path, sample_item: dict) -> None:
    write_todos(
        git_project,
        [sample_item],
        settings={"model": "gpt-5.2", "max_attempts": 5},
    )
    ws = load_workspace(git_project)
    assert ws.manifest.settings.model == "gpt-5.2"


def test_manifest_project_check_setting(git_project: Path, sample_item: dict) -> None:
    write_todos(
        git_project,
        [sample_item],
        settings={"project_check": "bash scripts/check", "max_attempts": 5},
    )
    ws = load_workspace(git_project)
    assert ws.manifest.settings.project_check == "bash scripts/check"


def test_manifest_allows_zero_validation_repairs(
    git_project: Path,
    sample_item: dict,
) -> None:
    write_todos(
        git_project,
        [sample_item],
        settings={"max_validation_repairs_per_attempt": 0, "max_attempts": 5},
    )
    ws = load_workspace(git_project)
    assert ws.manifest.settings.max_validation_repairs_per_attempt == 0


def test_manifest_missing_project_check_rejected(
    git_project: Path,
    sample_item: dict,
) -> None:
    write_todos(git_project, [sample_item], settings={"project_check": ""})
    with pytest.raises(ValidationError):
        load_workspace(git_project)


def test_resolve_model_cli_overrides_manifest() -> None:
    assert (
        resolve_model("cli-model", manifest_model="manifest-model", workspace_loaded=True)
        == "cli-model"
    )
    assert (
        resolve_model(None, manifest_model="manifest-model", workspace_loaded=True)
        == "manifest-model"
    )
    assert (
        resolve_model("", manifest_model="manifest-model", workspace_loaded=True)
        == "manifest-model"
    )
    assert resolve_model(None, manifest_model=None, workspace_loaded=True) is None
    assert (
        resolve_model(None, manifest_model=None, workspace_loaded=False)
        == DEFAULT_CURSOR_MODEL
    )


def test_resolve_auto_commit_cli_overrides_manifest() -> None:
    from todos_tool.orchestrator import _resolve_auto_commit

    assert _resolve_auto_commit(cli_auto_commit=True, manifest_auto_commit=False) is True
    assert _resolve_auto_commit(cli_auto_commit=False, manifest_auto_commit=True) is False
    assert _resolve_auto_commit(cli_auto_commit=None, manifest_auto_commit=True) is True
    assert _resolve_auto_commit(cli_auto_commit=None, manifest_auto_commit=False) is False
    assert _resolve_auto_commit(cli_auto_commit=None, manifest_auto_commit=None) is True


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
    a["priority"] = 50
    write_todos(git_project, [a, {**b, "_file": "items/002.yaml"}])
    ws = load_workspace(git_project)
    ready = list_ready(ws)
    assert [i.id for i in ready] == ["TASK-001"]
    rows = readiness_rows(ws)
    assert rows[1]["ready"].startswith("waiting:")


def test_priority_breaks_ties_after_dependencies(git_project: Path, sample_item: dict) -> None:
    a = dict(sample_item)
    b = dict(sample_item)
    c = dict(sample_item)
    b["id"] = "TASK-002"
    b["priority"] = 50
    c["id"] = "TASK-003"
    c["priority"] = 10
    write_todos(
        git_project,
        [a, {**b, "_file": "items/002.yaml"}, {**c, "_file": "items/003.yaml"}],
    )
    ws = load_workspace(git_project)
    ready = list_ready(ws)
    assert [item.id for item in ready] == ["TASK-003", "TASK-002", "TASK-001"]


def test_format_commit(git_project: Path, sample_item: dict) -> None:
    write_todos(git_project, [sample_item])
    ws = load_workspace(git_project)
    item = ws.get("TASK-001")
    assert item is not None
    assert _format_commit(item) == "-"

    item.status = ItemStatus.DONE
    assert _format_commit(item) == "uncommitted"

    item.result.commit_sha = "abcdef1234567890"
    assert _format_commit(item) == "abcdef12"


def test_next_ready_specific(git_project: Path, sample_item: dict) -> None:
    write_todos(git_project, [sample_item])
    ws = load_workspace(git_project)
    item = next_ready(ws, "TASK-001")
    assert item.id == "TASK-001"
    with pytest.raises(SchedulingError):
        next_ready(ws, "TASK-404")
