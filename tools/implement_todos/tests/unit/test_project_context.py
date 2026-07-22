"""Tests for project profile and context loading."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from todos_tool.errors import ValidationError
from todos_tool.profile_loader import (
    load_project_context,
    resolve_context_files,
    validate_required_context,
)


def test_neutral_defaults_without_profile(git_project: Path) -> None:
    ctx = load_project_context(git_project)
    assert ctx.source == "defaults"
    assert ctx.git.commit_prefix == "agent:"
    assert ctx.context_files == ()


def test_profile_loads_context_files(git_project: Path) -> None:
    profile = git_project / ".implement-todos.yaml"
    profile.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
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

    ctx = load_project_context(git_project)
    assert ctx.source == "profile"
    assert ctx.git.commit_prefix == "bot:"
    assert len(ctx.context_files) == 2

    resolved = resolve_context_files(git_project, ctx.context_files)
    validate_required_context(resolved)
    assert resolved[0].exists is True
    assert resolved[1].exists is False


def test_required_context_missing_fails(git_project: Path) -> None:
    profile = git_project / ".implement-todos.yaml"
    profile.write_text(
        "schema_version: 1\n"
        "context:\n"
        "  files:\n"
        "    - path: missing-required.md\n"
        "      required: true\n",
        encoding="utf-8",
    )
    ctx = load_project_context(git_project)
    resolved = resolve_context_files(git_project, ctx.context_files)
    with pytest.raises(ValidationError, match="Required context file missing"):
        validate_required_context(resolved)


def test_unsupported_profile_version_fails(git_project: Path) -> None:
    profile = git_project / ".implement-todos.yaml"
    profile.write_text("schema_version: 99\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="Unsupported profile"):
        load_project_context(git_project)
