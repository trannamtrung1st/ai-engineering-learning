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


def test_profile_required_commands_precede_manifest_and_item() -> None:
    from todos_tool.project_context import EvidencePolicy, GitPolicy, ProjectContext

    manifest = Manifest(settings=ManifestSettings(project_check="make lint"))
    ctx = ProjectContext(
        schema_version=1,
        context_files=(),
        instructions=(),
        authority=ProjectContext.neutral().authority,
        evidence=EvidencePolicy(required_commands=("pytest",)),
        git=GitPolicy(),
    )
    item = _item(commands=["make test"])
    assert resolve_validation_commands(manifest, item, project_context=ctx) == [
        "pytest",
        "make lint",
        "make test",
    ]


def test_deduplicates_normalized_commands() -> None:
    manifest = Manifest(settings=ManifestSettings(project_check="pytest"))
    item = _item(commands=["  pytest  "])
    assert resolve_validation_commands(manifest, item) == ["pytest"]


def test_project_check_optional_when_absent() -> None:
    manifest = Manifest(settings=ManifestSettings())
    assert resolve_validation_commands(manifest, _item()) == []
