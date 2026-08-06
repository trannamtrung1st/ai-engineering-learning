"""Packaging tests for bundled prompt templates."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
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
_CORE_TOOLS_ROOT = _PROJECT_ROOT.parent / "core_tools"


def _production_template_paths() -> list[str]:
    return sorted(
        path.relative_to(_TEMPLATE_ROOT).as_posix()
        for path in _TEMPLATE_ROOT.rglob("*.md.j2")
    )


def _pip_python() -> str:
    candidates = [
        "/Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14",
        shutil.which("python3"),
        sys.executable,
    ]
    for candidate in candidates:
        if not candidate:
            continue
        probe = subprocess.run(
            [candidate, "-m", "pip", "--version"],
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0:
            return candidate
    pytest.skip("pip-enabled python required for wheel install test")


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


def test_installed_wheel_renders_planner_protocol(
    built_wheel: Path,
    tmp_path: Path,
) -> None:
    """Installed distribution must import and render bundled planner protocol."""

    site = tmp_path / "site"
    site.mkdir()
    python = _pip_python()

    subprocess.run(
        [
            python,
            "-m",
            "pip",
            "install",
            "--quiet",
            "--no-deps",
            str(_CORE_TOOLS_ROOT),
            "-t",
            str(site),
        ],
        check=True,
    )
    subprocess.run(
        [
            python,
            "-m",
            "pip",
            "install",
            "--quiet",
            "jinja2",
            "pathspec",
            "-t",
            str(site),
        ],
        check=True,
    )
    subprocess.run(
        [
            python,
            "-m",
            "pip",
            "install",
            "--quiet",
            "--no-deps",
            str(built_wheel),
            "-t",
            str(site),
        ],
        check=True,
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str(site)
    result = subprocess.run(
        [
            python,
            "-c",
            (
                "from top_down_planning.orchestrator.planner_session import "
                "build_planner_protocol_instructions; "
                "protocol = build_planner_protocol_instructions(); "
                "assert isinstance(protocol, str); "
                "assert 'TDP planner' in protocol"
            ),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
