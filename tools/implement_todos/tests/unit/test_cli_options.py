"""CLI flag parsing tests."""

from __future__ import annotations

import pytest
import typer
from typer.testing import CliRunner

from todos_tool.cli import _parse_optional_bool, app


def test_parse_optional_bool_values() -> None:
    assert _parse_optional_bool(None, name="auto-commit") is None
    assert _parse_optional_bool("true", name="auto-commit") is True
    assert _parse_optional_bool("false", name="auto-commit") is False
    assert _parse_optional_bool("TRUE", name="auto-commit") is True
    assert _parse_optional_bool("0", name="auto-commit") is False


def test_parse_optional_bool_rejects_invalid() -> None:
    with pytest.raises(typer.BadParameter, match="Invalid value"):
        _parse_optional_bool("maybe", name="auto-commit")


def test_run_auto_commit_flag_parsing(tmp_path, monkeypatch) -> None:
    """--auto-commit accepts explicit true/false values (not --no-auto-commit)."""
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "--auto-commit" in result.stdout
    assert "--no-auto-commit" not in result.stdout
    assert "true/false" in result.stdout

    bad = runner.invoke(app, ["run", "--auto-commit", "maybe"])
    assert bad.exit_code != 0
