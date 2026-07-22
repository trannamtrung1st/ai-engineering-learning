"""CLI flag parsing tests."""

from __future__ import annotations

import subprocess
import sys

import pytest

from todos_tool.cli import main
from todos_tool.flags import parse_optional_bool
from tests.helpers import write_todos


def test_parse_optional_bool_values() -> None:
    assert parse_optional_bool(None, name="auto-commit") is None
    assert parse_optional_bool("true", name="auto-commit") is True
    assert parse_optional_bool("false", name="auto-commit") is False
    assert parse_optional_bool("TRUE", name="auto-commit") is True
    assert parse_optional_bool("0", name="auto-commit") is False


def test_parse_optional_bool_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="Invalid value"):
        parse_optional_bool("maybe", name="auto-commit")


def test_run_auto_commit_flag_parsing(capsys) -> None:
    """--auto-commit accepts explicit true/false values."""
    with pytest.raises(SystemExit) as exc:
        main(["run", "--help"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "--auto-commit" in captured.out
    assert "--no-auto-commit" not in captured.out
    assert "true/false" in captured.out

    with pytest.raises(SystemExit) as bad:
        main(["run", "--auto-commit", "maybe"])
    assert bad.value.code != 0


def test_validate_status_and_version(tmp_path, sample_item, git_project) -> None:
    write_todos(git_project, [sample_item])
    assert main(["validate", "--workspace", str(git_project)]) == 0
    assert (
        main(["status", "--workspace", str(git_project), "--no-color"]) == 0
    )
    with pytest.raises(SystemExit) as version_exc:
        main(["--version"])
    assert version_exc.value.code == 0


def test_run_new_flags_in_help(capsys) -> None:
    with pytest.raises(SystemExit):
        main(["run", "--help"])
    captured = capsys.readouterr()
    for flag in (
        "--config",
        "--commit-hint",
        "--commit-hint-file",
        "--project-config",
        "--context-file",
        "--skip-commit",
        "--no-auto-repair-yaml",
        "--max-yaml-repair-attempts",
        "--dry-run",
        "--dry-run-prompts",
        "--evidence-mode",
        "--max-identical-evidence-failures",
        "--evidence-batch-timeout-seconds",
        "--force-reset",
        "--notify",
        "--no-notify",
        "--notify-per-item",
        "--no-notify-per-item",
    ):
        assert flag in captured.out
    assert "--allow-dirty" not in captured.out


def test_installed_entry_point_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "todos_tool", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "validate" in result.stdout
