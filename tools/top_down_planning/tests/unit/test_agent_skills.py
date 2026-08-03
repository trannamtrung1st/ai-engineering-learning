"""Tests for bundled TDP agent skills shipped in the package."""

from __future__ import annotations

from pathlib import Path

from core_tools.config.resources import load_skills

from top_down_planning.config import resolve_config, resolve_effective_role_context
from top_down_planning.config.bundled_skills import (
    BUNDLED_SKILL_BINDING_PREFIX,
    bundled_skill_binding_key,
    bundled_skills_root,
    load_bundled_skills_for_role,
)
from top_down_planning.config.context import build_context_snapshot_payload
from tests.helpers import minimal_resolved_config, write_config


def test_bundled_skills_root_is_package_local() -> None:
    root = bundled_skills_root()
    assert root.name == "tdp-agent"
    assert (root / "SKILL.md").is_file()
    assert (root / "planner" / "SKILL.md").is_file()


def test_bundled_skills_auto_injected_for_planner(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = minimal_resolved_config()

    context = resolve_effective_role_context(config, "planner", workspace=workspace)
    contents = [entry.content.lower() for entry in context.skills]
    assert len(context.skills) == 2
    assert any("tdp agent" in content for content in contents)
    assert any("plan apply" in content for content in contents)


def test_bundled_skills_opt_out(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = minimal_resolved_config()
    config["agent_context"]["bundled_skills"] = False

    context = resolve_effective_role_context(config, "planner", workspace=workspace)
    assert context.skills == ()


def test_bundled_skills_use_stable_binding_keys(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = minimal_resolved_config()

    binding = build_context_snapshot_payload(config, workspace=workspace)
    keys = set(binding["skill_digests"])
    assert f"{BUNDLED_SKILL_BINDING_PREFIX}SKILL.md" in keys
    assert f"{BUNDLED_SKILL_BINDING_PREFIX}planner/SKILL.md" in keys
    assert f"{BUNDLED_SKILL_BINDING_PREFIX}producer/SKILL.md" in keys
    assert f"{BUNDLED_SKILL_BINDING_PREFIX}reviewer/SKILL.md" in keys


def test_bundled_skill_binding_key_ignores_non_bundled_paths(tmp_path: Path) -> None:
    workspace_skill = tmp_path / "skills" / "demo" / "SKILL.md"
    workspace_skill.parent.mkdir(parents=True)
    workspace_skill.write_text("demo", encoding="utf-8")
    assert bundled_skill_binding_key(workspace_skill) is None


def test_load_bundled_skills_for_role_returns_shared_and_role_specific() -> None:
    entries = load_bundled_skills_for_role("reviewer")
    assert len(entries) == 2
    assert entries[0].path.name == "SKILL.md"
    assert entries[1].path.parent.name == "reviewer"


def test_configured_skills_merge_with_bundled_skills(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    custom_skill_dir = workspace / "skills" / "custom"
    custom_skill_dir.mkdir(parents=True)
    (custom_skill_dir / "SKILL.md").write_text("custom skill", encoding="utf-8")

    config = resolve_config(
        write_config(
            tmp_path / "base.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  planner:
    skills:
      - skills/custom
""",
        ),
        cwd=workspace,
    )

    context = resolve_effective_role_context(config, "planner", workspace=workspace)
    assert len(context.skills) == 3
    assert "custom skill" in context.skills[-1].content


def test_user_configured_skills_load_from_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skill_dir = workspace / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# demo\n\nbody\n", encoding="utf-8")

    config = resolve_config(
        write_config(
            tmp_path / "base.yaml",
            """
run:
  output_goal: Goal.
agent_context:
  bundled_skills: false
  producer:
    skills:
      - skills/demo
""",
        ),
        cwd=workspace,
    )

    loaded = load_skills(
        config["agent_context"]["producer"]["skills"],
        workspace=workspace,
        field="skills",
    )
    assert loaded[0].path.name == "SKILL.md"
    assert "demo" in loaded[0].content.lower()

    context = resolve_effective_role_context(config, "producer", workspace=workspace)
    assert len(context.skills) == 1
