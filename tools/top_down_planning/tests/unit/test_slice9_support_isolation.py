"""Slice 9: stable test-support imports and Darwin CLI-cancel CI coverage."""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_BOUNDARIES = Path(__file__).resolve().parent / "test_slice7_rereview_boundaries.py"


def test_slice7_rereview_boundaries_does_not_import_sibling_test_modules() -> None:
    source = _BOUNDARIES.read_text(encoding="utf-8")
    assert "from tests.unit.test_" not in source
    assert "from tests.support." in source


def test_darwin_ci_runs_cli_os_process_cancel_serially() -> None:
    workflow = (_REPO_ROOT / ".github" / "workflows" / "tdp.yml").read_text(encoding="utf-8")
    darwin = workflow.split("darwin-janitor:")[1]
    assert "test_cli_os_process_cancel.py" in darwin
    assert "-p no:xdist" in darwin
    assert "-o addopts=''" in darwin
