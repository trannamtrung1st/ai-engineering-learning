"""CLI discovery command tests for top-down-planning."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from top_down_planning.cli import app
from top_down_planning.schema_docs import PUBLIC_CONTRACTS, show_example, validate_example


runner = CliRunner()


def test_help_lists_discovery_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for token in ("usage", "schema", "example"):
        assert token in result.stdout


def test_usage_json() -> None:
    result = runner.invoke(app, ["usage", "--format", "json"])
    assert result.exit_code == 0
    assert "top-down-planning" in result.stdout


def test_schema_list_and_show() -> None:
    result = runner.invoke(app, ["schema", "list", "--format", "json"])
    assert result.exit_code == 0
    for name in PUBLIC_CONTRACTS:
        show = runner.invoke(app, ["schema", "show", name, "--format", "json"])
        assert show.exit_code == 0
        assert '"schema"' in show.stdout


def test_example_round_trip() -> None:
    result = runner.invoke(app, ["example", "list", "--format", "json"])
    assert result.exit_code == 0
    for name in PUBLIC_CONTRACTS:
        show = runner.invoke(app, ["example", "show", name, "--format", "json"])
        assert show.exit_code == 0
        payload = show_example(name)["example"]
        validate_example(name, payload)


def test_unknown_contract_fails() -> None:
    result = runner.invoke(app, ["schema", "show", "missing"])
    assert result.exit_code != 0
