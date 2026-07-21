"""Path containment and identifier validation tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.helpers import write_todos
from todos_tool.errors import ValidationError
from todos_tool.manifest import load_workspace
from todos_tool.paths import resolve_within, validate_item_id, validate_relative_path


def test_validate_item_id_rejects_unsafe() -> None:
    with pytest.raises(ValueError, match="filename-safe"):
        validate_item_id("../TASK-001")


def test_validate_relative_path_rejects_traversal() -> None:
    with pytest.raises(ValueError, match="\\.\\."):
        validate_relative_path("../items/x.yaml", label="file")


def test_resolve_within_rejects_escape(tmp_path: Path) -> None:
    base = tmp_path / "todos"
    base.mkdir()
    with pytest.raises(ValueError, match="\\.\\."):
        resolve_within(base, "../secret.txt")


def test_custom_todos_dir(git_project: Path, sample_item: dict) -> None:
    custom = git_project / "backlog"
    write_todos(git_project, [sample_item], settings={"max_attempts": 5})
    (git_project / "todos").rename(custom)
    ws = load_workspace(git_project, "backlog")
    assert ws.todos_dir.name == "backlog"


def test_manifest_unknown_field_rejected(git_project: Path, sample_item: dict) -> None:
    write_todos(git_project, [sample_item])
    manifest_path = git_project / "todos/manifest.yaml"
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    raw["unexpected"] = True
    manifest_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_workspace(git_project)
