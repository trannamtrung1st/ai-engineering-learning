"""Packaging and install smoke tests (wheel assembly + documented editable install)."""

from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path

import pytest

pytest.importorskip("build")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CORE_TOOLS_ROOT = _PROJECT_ROOT.parent / "core_tools"


def _venv_python(venv_dir: Path) -> Path:
    candidate = venv_dir / "bin" / "python"
    if candidate.is_file():
        return candidate
    windows = venv_dir / "Scripts" / "python.exe"
    assert windows.is_file(), f"venv python not found under {venv_dir}"
    return windows


def _run_python(
    python: Path | str,
    code: str,
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(python), "-c", code],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_module(
    python: Path | str,
    argv: list[str],
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(python), "-m", "top_down_planning", *argv],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _assert_bundled_skills_load(python: Path | str, env: dict[str, str] | None = None) -> None:
    result = _run_python(
        python,
        (
            "from top_down_planning.config.bundled_skills import load_bundled_skills_for_role; "
            "roles = ('planner', 'producer', 'reviewer'); "
            "assert all(len(load_bundled_skills_for_role(role)) == 2 for role in roles); "
            "assert all("
            "entries[0].path.name == 'SKILL.md' and "
            "'tdp agent' in entries[0].content.lower() and "
            "entries[1].path.parent.name == role and "
            "entries[1].content.strip() "
            "for role in roles "
            "for entries in [load_bundled_skills_for_role(role)]"
            ")"
        ),
        env=env,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def _assert_planner_protocol_renders(python: Path | str, env: dict[str, str] | None = None) -> None:
    result = _run_python(
        python,
        (
            "from top_down_planning.orchestrator.planner_session import "
            "build_planner_protocol_instructions; "
            "protocol = build_planner_protocol_instructions(); "
            "assert isinstance(protocol, str); "
            "assert 'TDP planner' in protocol"
        ),
        env=env,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def _assert_cli_surfaces(python: Path | str, env: dict[str, str] | None = None) -> None:
    help_result = _run_module(python, ["--help"], env=env)
    assert help_result.returncode == 0, help_result.stderr or help_result.stdout
    assert "run" in help_result.stdout.lower()

    readme_result = _run_module(python, ["agent", "readme"], env=env)
    assert readme_result.returncode == 0, readme_result.stderr or readme_result.stdout
    assert "tdp agent" in readme_result.stdout.lower()

    schema_result = _run_module(python, ["agent", "schema", "plan-transaction"], env=env)
    assert schema_result.returncode == 0, schema_result.stderr or schema_result.stdout

    example_result = _run_module(python, ["agent", "example", "expand-branch"], env=env)
    assert example_result.returncode == 0, example_result.stderr or example_result.stdout


@pytest.fixture(scope="session")
def packaging_wheelhouse(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Local wheelhouse: sibling packages plus runtime deps (no index during install)."""

    from build import ProjectBuilder

    wheelhouse = tmp_path_factory.mktemp("wheelhouse")
    ProjectBuilder(_CORE_TOOLS_ROOT).build("wheel", wheelhouse)
    ProjectBuilder(_PROJECT_ROOT).build("wheel", wheelhouse)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "jinja2",
            "pathspec",
            "-w",
            str(wheelhouse),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return wheelhouse


@pytest.fixture
def installed_wheel_site(packaging_wheelhouse: Path, tmp_path: Path) -> tuple[Path, str]:
    """Install built wheels into an isolated target dir using only the local wheelhouse."""

    site = tmp_path / "site"
    site.mkdir()
    python = sys.executable

    for wheel in sorted(packaging_wheelhouse.glob("*.whl")):
        subprocess.run(
            [
                python,
                "-m",
                "pip",
                "install",
                "--quiet",
                "--no-index",
                "--find-links",
                str(packaging_wheelhouse),
                "--no-deps",
                str(wheel),
                "-t",
                str(site),
            ],
            check=True,
        )

    return site, python


@pytest.mark.integration
def test_documented_editable_install_smoke(tmp_path: Path) -> None:
    """Documented monorepo editable install runs core CLI and bundled-skill surfaces."""

    venv_dir = tmp_path / "venv"
    venv.create(venv_dir, with_pip=True)
    python = _venv_python(venv_dir)

    subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet", "-e", str(_CORE_TOOLS_ROOT)],
        check=True,
    )
    subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet", "-e", f"{_PROJECT_ROOT}[dev]"],
        check=True,
    )

    _assert_cli_surfaces(python)
    _assert_bundled_skills_load(python)
    _assert_planner_protocol_renders(python)


@pytest.mark.integration
def test_installed_wheel_smoke(installed_wheel_site: tuple[Path, str]) -> None:
    """Assembled wheel artifact exposes the same CLI, skill, and prompt surfaces."""

    site, python = installed_wheel_site
    env = os.environ.copy()
    env["PYTHONPATH"] = str(site)

    _assert_cli_surfaces(python, env=env)
    _assert_bundled_skills_load(python, env=env)
    _assert_planner_protocol_renders(python, env=env)
