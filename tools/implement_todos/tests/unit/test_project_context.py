"""Project context loading from unified run config."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from todos_tool.config_loader import build_run_config
from todos_tool.context_files import resolve_context_files, validate_required_context
from todos_tool.errors import TodosToolError, ValidationError
from todos_tool.project_context import ProjectContext


def test_neutral_defaults_without_config(git_project: Path) -> None:
    config = build_run_config(workspace=git_project)
    ctx = config.project_context
    assert ctx.source == "defaults"
    assert ctx.git.commit_prefix == "agent:"
    assert ctx.context_files == ()


def test_run_config_loads_context_files(git_project: Path) -> None:
    (git_project / "README.md").write_text("# Example\n", encoding="utf-8")
    config_path = git_project / "run.config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "workspace": ".",
                "context": {
                    "files": [
                        {"path": "README.md", "required": True},
                        {"path": "missing.md", "required": False},
                    ],
                    "instructions": ["Follow repository conventions."],
                },
                "git": {"commit_prefix": "bot:"},
            }
        ),
        encoding="utf-8",
    )

    config = build_run_config(config_path=config_path, workspace=git_project)
    ctx = config.project_context
    assert ctx.source == "config"
    assert ctx.git.commit_prefix == "bot:"
    assert len(ctx.context_files) == 2

    resolved = resolve_context_files(git_project, ctx.context_files)
    validate_required_context(resolved)
    assert resolved[0].exists is True
    assert resolved[1].exists is False


def test_required_context_missing_fails(git_project: Path) -> None:
    config_path = git_project / "run.config.yaml"
    config_path.write_text(
        "workspace: .\n"
        "context:\n"
        "  files:\n"
        "    - path: missing-required.md\n"
        "      required: true\n",
        encoding="utf-8",
    )
    config = build_run_config(config_path=config_path, workspace=git_project)
    resolved = resolve_context_files(git_project, config.project_context.context_files)
    with pytest.raises(ValidationError, match="Required context file missing"):
        validate_required_context(resolved)


def test_rejects_legacy_project_config_key(git_project: Path) -> None:
    config_path = git_project / "run.config.yaml"
    config_path.write_text("project_config: .implement-todos.yaml\n", encoding="utf-8")
    with pytest.raises(TodosToolError, match="Unsupported config keys"):
        build_run_config(config_path=config_path, workspace=git_project)


def test_neutral_project_context_factory() -> None:
    ctx = ProjectContext.neutral()
    assert ctx.source == "defaults"
