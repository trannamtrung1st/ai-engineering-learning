"""Unit tests for resource and skill loading primitives."""

from __future__ import annotations

from pathlib import Path

import pytest

from core_tools.config import (
    ConfigError,
    load_skills,
    resolve_expanded_path_list,
    resolve_provider_model,
)


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


def test_resolve_expanded_path_list_file(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    resource = workspace / "README.md"
    resource.write_text("readme", encoding="utf-8")
    paths = resolve_expanded_path_list(
        ["README.md"],
        workspace=workspace,
        field="resources",
    )
    assert paths == [resource.resolve()]


def test_resolve_expanded_path_list_directory(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    docs = workspace / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("a", encoding="utf-8")
    (docs / "b.md").write_text("b", encoding="utf-8")
    paths = resolve_expanded_path_list(
        ["docs"],
        workspace=workspace,
        field="resources",
    )
    assert paths == [
        (docs / "a.md").resolve(),
        (docs / "b.md").resolve(),
    ]


def test_load_skills_from_directory(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    skill_dir = workspace / ".agents" / "skills" / "common"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("# Common skill", encoding="utf-8")
    skills = load_skills(
        [".agents/skills/common"],
        workspace=workspace,
        field="skills",
    )
    assert len(skills) == 1
    assert skills[0].path == skill_file.resolve()
    assert "Common skill" in skills[0].content


def test_resolve_provider_model_role_over_default() -> None:
    agent_context = {
        "default": {"model": "default-model"},
        "planner": {"model": "planner-model"},
    }
    assert resolve_provider_model(agent_context, "planner") == "planner-model"
    assert resolve_provider_model(agent_context, "producer") == "default-model"


def test_resolve_provider_model_skips_auto() -> None:
    agent_context = {
        "default": {"model": "auto"},
        "planner": {"model": "auto"},
    }
    assert resolve_provider_model(agent_context, "planner") is None


def test_resolve_expanded_path_list_missing_raises(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    with pytest.raises(ConfigError, match="not found in workspace"):
        resolve_expanded_path_list(
            ["missing.md"],
            workspace=workspace,
            field="resources",
        )
