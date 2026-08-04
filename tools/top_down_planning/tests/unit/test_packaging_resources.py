"""Packaging tests for bundled prompt templates."""

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


def _bundled_template_paths() -> list[str]:
    return sorted(
        path.relative_to(_TEMPLATE_ROOT).as_posix()
        for path in _TEMPLATE_ROOT.rglob("*.md.j2")
    )


def test_built_wheel_includes_all_prompt_templates(tmp_path: Path) -> None:
    from build import ProjectBuilder

    project_root = Path(__file__).resolve().parents[2]
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    ProjectBuilder(project_root).build("wheel", dist_dir)

    wheels = list(dist_dir.glob("*.whl"))
    assert len(wheels) == 1

    expected = _bundled_template_paths()
    assert expected, "expected at least one bundled prompt template"

    with zipfile.ZipFile(wheels[0]) as archive:
        names = archive.namelist()
        for relative_path in expected:
            suffix = f"prompts/templates/{relative_path}"
            assert any(name.endswith(suffix) for name in names), suffix
