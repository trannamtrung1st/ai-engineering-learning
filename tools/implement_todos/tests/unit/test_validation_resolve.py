"""Validation command resolution tests."""

from __future__ import annotations

import pytest

from todos_tool.models import ItemType, Manifest, ManifestSettings, TodoItem
from todos_tool.validation_runner import resolve_validation_commands


def _item(*, commands: list[str] | None = None) -> TodoItem:
    return TodoItem(
        id="TASK-001",
        title="Example",
        type=ItemType.FEATURE,
        description="desc",
        acceptance_criteria=["ok"],
        validation={"commands": commands or []},
    )


def test_project_check_only_when_item_has_no_extra_commands() -> None:
    manifest = Manifest(settings=ManifestSettings(project_check="pytest"))
    assert resolve_validation_commands(manifest, _item()) == ["pytest"]


def test_project_check_precedes_item_commands() -> None:
    manifest = Manifest(
        settings=ManifestSettings(project_check="bash scripts/check")
    )
    item = _item(commands=["pytest -k smoke"])
    assert resolve_validation_commands(manifest, item) == [
        "bash scripts/check",
        "pytest -k smoke",
    ]


def test_deduplicates_normalized_commands() -> None:
    manifest = Manifest(settings=ManifestSettings(project_check="pytest"))
    item = _item(commands=["  pytest  "])
    assert resolve_validation_commands(manifest, item) == ["pytest"]


def test_manifest_requires_project_check() -> None:
    with pytest.raises(Exception):
        ManifestSettings()
