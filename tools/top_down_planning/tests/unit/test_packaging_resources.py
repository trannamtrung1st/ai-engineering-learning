"""Fast unit checks that built wheels include the expected packaged resources."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

pytest.importorskip("build")

_TEMPLATE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "top_down_planning"
    / "prompts"
    / "templates"
)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_BUNDLED_SKILLS_ROOT = (
    _PROJECT_ROOT / "src" / "top_down_planning" / "bundled_skills" / "tdp-agent"
)


def _production_template_paths() -> list[str]:
    return sorted(
        path.relative_to(_TEMPLATE_ROOT).as_posix()
        for path in _TEMPLATE_ROOT.rglob("*.md.j2")
    )


def _bundled_skill_paths() -> list[str]:
    return sorted(
        path.relative_to(_BUNDLED_SKILLS_ROOT).as_posix()
        for path in _BUNDLED_SKILLS_ROOT.rglob("SKILL.md")
    )


@pytest.fixture(scope="session")
def built_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from build import ProjectBuilder

    dist_dir = tmp_path_factory.mktemp("packaging-dist")
    ProjectBuilder(_PROJECT_ROOT).build("wheel", dist_dir)
    wheels = list(dist_dir.glob("*.whl"))
    assert len(wheels) == 1
    return wheels[0]


def test_built_wheel_includes_production_prompt_templates(built_wheel: Path) -> None:
    expected = _production_template_paths()
    assert expected, "expected at least one production prompt template"

    with zipfile.ZipFile(built_wheel) as archive:
        names = archive.namelist()
        for relative_path in expected:
            suffix = f"prompts/templates/{relative_path}"
            assert any(name.endswith(suffix) for name in names), suffix


def test_built_wheel_excludes_test_prompt_templates(built_wheel: Path) -> None:
    with zipfile.ZipFile(built_wheel) as archive:
        names = archive.namelist()
        assert not any("prompts/templates/test/" in name for name in names)


def test_built_wheel_includes_bundled_agent_skills(built_wheel: Path) -> None:
    expected = _bundled_skill_paths()
    assert expected, "expected packaged bundled agent skills"

    with zipfile.ZipFile(built_wheel) as archive:
        names = archive.namelist()
        for relative_path in expected:
            suffix = f"bundled_skills/tdp-agent/{relative_path}"
            assert any(name.endswith(suffix) for name in names), suffix
