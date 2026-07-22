"""Portability tests for standalone tool startup."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.helpers import write_todos
from todos_tool.cli import main


def test_import_without_external_pythonpath() -> None:
    env = {
        key: value
        for key, value in __import__("os").environ.items()
        if key != "PYTHONPATH"
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import todos_tool; from todos_tool.orchestrator import Orchestrator",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_help_validate_status_with_neutral_defaults(
    git_project: Path,
    sample_item: dict,
) -> None:
    write_todos(git_project, [sample_item])
    assert main(["validate", "--workspace", str(git_project)]) == 0
    assert main(["status", "--workspace", str(git_project), "--no-color"]) == 0


def test_dry_run_reports_repair_need(git_project: Path) -> None:
    todos = git_project / "todos"
    todos.mkdir(parents=True)
    (todos / "manifest.yaml").write_text("not: [valid\n", encoding="utf-8")

    rc = main(
        [
            "run",
            "--workspace",
            str(git_project),
            "--dry-run",
            "--no-color",
        ]
    )
    assert rc == 1
