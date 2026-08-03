"""Tests for bundled TDP agent skills shipped in the package."""

from __future__ import annotations

import shutil
from pathlib import Path

from core_tools.config.resources import load_skills


def test_bundled_agent_skills_resolve_from_workspace(tmp_path: Path) -> None:
    package_root = Path(__file__).resolve().parents[2]
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    shutil.copytree(
        package_root / "skills",
        workspace / "tools" / "top_down_planning" / "skills",
    )

    shared = load_skills(
        ["tools/top_down_planning/skills/tdp-agent"],
        workspace=workspace,
        field="skills",
    )
    planner = load_skills(
        ["tools/top_down_planning/skills/tdp-agent/planner"],
        workspace=workspace,
        field="skills",
    )

    assert shared[0].path.name == "SKILL.md"
    assert "tdp agent" in shared[0].content.lower()
    assert planner[0].path.name == "SKILL.md"
    assert "plan apply" in planner[0].content.lower()
