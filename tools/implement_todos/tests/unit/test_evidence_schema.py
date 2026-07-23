"""Evidence command schema validation."""

from __future__ import annotations

import pytest

from todos_tool.models import (
    DEFAULT_ALLOW_EMPTY_COMMIT,
    ItemEvidence,
    ItemType,
    TodoItem,
    validate_todo_item,
)


def test_plain_string_evidence_command_rejected() -> None:
    with pytest.raises(ValueError, match="plain string"):
        ItemEvidence.from_dict({"commands": ["pytest"]})


def test_invalid_absolute_cwd_rejected() -> None:
    with pytest.raises(ValueError, match="relative"):
        ItemEvidence.from_dict(
            {"commands": [{"command": "pytest", "cwd": "/tmp"}]}
        )


def test_parent_traversal_cwd_rejected() -> None:
    with pytest.raises(ValueError, match="\\.\\."):
        ItemEvidence.from_dict(
            {"commands": [{"command": "pytest", "cwd": "../secrets"}]}
        )


def test_mapping_evidence_command_parses() -> None:
    evidence = ItemEvidence.from_dict(
        {
            "commands": [
                {
                    "command": "pytest tests/unit",
                    "cwd": "subdir",
                    "timeout_seconds": 120,
                }
            ]
        }
    )
    assert evidence.commands[0].command == "pytest tests/unit"
    assert evidence.commands[0].cwd == "subdir"
    assert evidence.commands[0].timeout_seconds == 120


def test_item_roundtrip_preserves_mapping_evidence() -> None:
    item = TodoItem(
        id="TASK-001",
        title="Example",
        type=ItemType.FEATURE,
        description="desc",
        acceptance_criteria=["ok"],
        evidence={
            "commands": [{"command": "echo hi", "cwd": "src"}],
        },
    )
    payload = item.to_dict()
    assert payload["evidence"]["commands"][0]["command"] == "echo hi"


def test_item_defaults_allow_empty_commit() -> None:
    assert DEFAULT_ALLOW_EMPTY_COMMIT is True
    item = TodoItem(
        id="TASK-001",
        title="Example",
        type=ItemType.FEATURE,
        description="desc",
        acceptance_criteria=["ok"],
    )
    assert item.allow_empty_commit is True
    assert "allow_empty_commit" not in item.to_dict()


def test_item_from_dict_allow_empty_commit_defaults_and_opt_out() -> None:
    base = {
        "version": 1,
        "id": "TASK-001",
        "title": "Example",
        "type": "feature",
        "description": "desc",
        "acceptance_criteria": ["ok"],
    }
    defaulted = TodoItem.from_dict(base)
    assert defaulted.allow_empty_commit is True

    strict = TodoItem.from_dict({**base, "allow_empty_commit": False})
    assert strict.allow_empty_commit is False
    assert strict.to_dict()["allow_empty_commit"] is False


def test_validate_todo_item_rejects_non_boolean_allow_empty_commit() -> None:
    with pytest.raises(ValueError, match="allow_empty_commit must be a boolean"):
        validate_todo_item(
            {
                "version": 1,
                "id": "TASK-001",
                "title": "Example",
                "type": "feature",
                "description": "desc",
                "acceptance_criteria": ["ok"],
                "allow_empty_commit": "false",
            }
        )
