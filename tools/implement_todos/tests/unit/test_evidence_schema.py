"""Evidence command schema validation."""

from __future__ import annotations

import pytest

from todos_tool.models import ItemEvidence, TodoItem, ItemType


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
