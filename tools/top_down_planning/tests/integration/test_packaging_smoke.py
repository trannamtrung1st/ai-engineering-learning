"""Packaging and install smoke tests (offline wheelhouse + isolated interpreters)."""

from __future__ import annotations

import subprocess
import venv
from pathlib import Path

import pytest

from tests.packaging_wheelhouse import PackagingWheelhouseError, resolve_packaging_wheelhouse

pytest.importorskip("build")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _venv_python(venv_dir: Path) -> Path:
    candidate = venv_dir / "bin" / "python"
    if candidate.is_file():
        return candidate
    windows = venv_dir / "Scripts" / "python.exe"
    assert windows.is_file(), f"venv python not found under {venv_dir}"
    return windows


def _isolated_venv(base: Path) -> Path:
    venv_dir = base / "venv"
    venv.create(venv_dir, with_pip=True, system_site_packages=False)
    return _venv_python(venv_dir)


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


def _assert_bundled_skills_load(python: Path | str) -> None:
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
    )
    assert result.returncode == 0, result.stderr or result.stdout


def _assert_planner_protocol_renders(python: Path | str) -> None:
    result = _run_python(
        python,
        (
            "from top_down_planning.orchestrator.planner_session import "
            "build_planner_protocol_instructions; "
            "protocol = build_planner_protocol_instructions(); "
            "assert isinstance(protocol, str); "
            "assert 'TDP planner' in protocol"
        ),
    )
    assert result.returncode == 0, result.stderr or result.stdout


def _assert_cli_surfaces(python: Path | str) -> None:
    help_result = _run_module(python, ["--help"])
    assert help_result.returncode == 0, help_result.stderr or help_result.stdout
    assert "run" in help_result.stdout.lower()

    readme_result = _run_module(python, ["agent", "readme"])
    assert readme_result.returncode == 0, readme_result.stderr or readme_result.stdout
    assert "tdp agent" in readme_result.stdout.lower()

    schema_result = _run_module(python, ["agent", "schema", "plan-transaction"])
    assert schema_result.returncode == 0, schema_result.stderr or schema_result.stdout

    example_result = _run_module(python, ["agent", "example", "expand-branch"])
    assert example_result.returncode == 0, example_result.stderr or example_result.stdout


def _pip_offline(
    python: Path | str,
    wheelhouse: Path,
    args: list[str],
    *,
    cwd: Path | None = None,
) -> None:
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--quiet",
            "--no-index",
            "--find-links",
            str(wheelhouse),
            *args,
        ],
        cwd=str(cwd) if cwd is not None else None,
        check=True,
    )


def _install_all_wheels_offline(python: Path | str, wheelhouse: Path) -> None:
    wheels = sorted(wheelhouse.glob("*.whl"))
    if not wheels:
        raise AssertionError(f"packaging wheelhouse has no wheels: {wheelhouse}")
    for wheel in wheels:
        _pip_offline(python, wheelhouse, ["--no-deps", str(wheel)])


@pytest.fixture(scope="session")
def packaging_wheelhouse() -> Path:
    """Require a pre-built offline wheelhouse from TDP_PACKAGING_WHEELHOUSE."""

    try:
        return resolve_packaging_wheelhouse()
    except PackagingWheelhouseError as exc:
        pytest.fail(str(exc))


@pytest.mark.integration
def test_documented_editable_install_smoke(
    packaging_wheelhouse: Path,
    tmp_path: Path,
) -> None:
    """README install commands from tools/top_down_planning with an offline wheelhouse."""

    python = _isolated_venv(tmp_path)
    _pip_offline(python, packaging_wheelhouse, ["build", "hatchling"])
    _pip_offline(
        python,
        packaging_wheelhouse,
        ["-e", "../core_tools"],
        cwd=_PROJECT_ROOT,
    )
    _pip_offline(
        python,
        packaging_wheelhouse,
        ["-e", ".[dev]"],
        cwd=_PROJECT_ROOT,
    )

    _assert_cli_surfaces(python)
    _assert_bundled_skills_load(python)
    _assert_planner_protocol_renders(python)


@pytest.mark.integration
def test_installed_wheel_smoke(
    packaging_wheelhouse: Path,
    tmp_path: Path,
) -> None:
    """Assembled wheels run in an isolated venv without the test runner site-packages."""

    python = _isolated_venv(tmp_path)
    _install_all_wheels_offline(python, packaging_wheelhouse)

    _assert_cli_surfaces(python)
    _assert_bundled_skills_load(python)
    _assert_planner_protocol_renders(python)
