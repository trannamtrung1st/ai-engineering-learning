"""CLI discovery command tests."""

from __future__ import annotations

import json

import pytest

from todos_tool.cli import main
from todos_tool.discoverability import PUBLIC_CONTRACTS, show_example, show_schema
from todos_tool.models import validate_manifest, validate_todo_item


def test_help_lists_discovery_commands(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    for token in ("usage", "schema", "example"):
        assert token in captured.out


def test_usage_json() -> None:
    code = main(["usage", "--format", "json"])
    assert code == 0


def test_schema_list_and_show() -> None:
    assert main(["schema", "list", "--format", "json"]) == 0
    for name in PUBLIC_CONTRACTS:
        assert main(["schema", "show", name, "--format", "json"]) == 0


def test_example_list_and_show_round_trip() -> None:
    assert main(["example", "list", "--format", "json"]) == 0
    for name in PUBLIC_CONTRACTS:
        assert main(["example", "show", name, "--format", "json"]) == 0
        payload = show_example(name)["example"]
        if name == "manifest":
            validate_manifest(payload)
        elif name == "item":
            validate_todo_item(payload)
        elif name == "review-decision":
            assert payload["schema_version"] == 1
            assert "acceptance_criteria" in payload


def test_unknown_contract_returns_error(capsys) -> None:
    assert main(["schema", "show", "missing", "--format", "json"]) == 2
    captured = capsys.readouterr()
    assert "Unknown contract" in captured.err


def test_schema_metadata() -> None:
    manifest = show_schema("manifest")
    assert manifest["format"] == "contract"
    assert manifest["authority"].endswith("validate_manifest")
