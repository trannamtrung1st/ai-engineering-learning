"""Packaging smoke is a separate gate, not a hidden full-suite prerequisite."""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

import tests.integration.test_packaging_smoke as packaging_smoke

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _mark_names(fn: object) -> set[str]:
    raw = getattr(fn, "pytestmark", [])
    if not isinstance(raw, list):
        raw = [raw]
    return {str(getattr(mark, "name", "") or "") for mark in raw}


def _packaging_smoke_tests() -> list[object]:
    tests = [
        getattr(packaging_smoke, name)
        for name in dir(packaging_smoke)
        if name.startswith("test_") and callable(getattr(packaging_smoke, name))
    ]
    assert tests, "expected packaging smoke tests"
    return tests


def test_packaging_smoke_tests_use_packaging_marker_not_integration() -> None:
    for fn in _packaging_smoke_tests():
        names = _mark_names(fn)
        assert "packaging" in names
        assert "integration" not in names


def test_default_addopts_exclude_packaging_from_unit_and_review_suites() -> None:
    data = tomllib.loads((_PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    addopts = data["tool"]["pytest"]["ini_options"]["addopts"]
    joined = " ".join(addopts) if isinstance(addopts, list) else str(addopts)
    assert "not integration" in joined
    assert "not packaging" in joined
    markers = data["tool"]["pytest"]["ini_options"]["markers"]
    assert any(str(marker).startswith("packaging:") for marker in markers)


def test_review_plan_no_addopts_full_suite_collects_packaging_without_wheelhouse_env() -> None:
    env = {key: value for key, value in os.environ.items() if key != "TDP_PACKAGING_WHEELHOUSE"}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-o",
            "addopts=",
            "--collect-only",
            "-q",
            "tests",
        ],
        cwd=_PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "test_installed_wheel_smoke" in result.stdout
    assert "test_documented_editable_install_smoke" in result.stdout


def test_packaging_session_fixture_uses_ensure_when_wheelhouse_env_is_unset() -> None:
    import inspect

    source = inspect.getsource(packaging_smoke.packaging_wheelhouse)
    assert "ensure_packaging_wheelhouse" in source
    assert "resolve_packaging_wheelhouse" not in source
