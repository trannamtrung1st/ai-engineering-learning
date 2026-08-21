"""Slice 10 evidence matrix: every required scenario maps to an executable test."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.packaging_wheelhouse import PackagingWheelhouseError, resolve_packaging_wheelhouse
from tests.support.slice10 import SLICE10_SCENARIO_EVIDENCE

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = Path(__file__).resolve().parents[4] / ".github" / "workflows" / "tdp.yml"


def test_slice10_matrix_covers_all_twenty_review_plan_scenarios() -> None:
    assert set(SLICE10_SCENARIO_EVIDENCE) == set(range(1, 21))
    for number, (relative, test_name, must_contain) in SLICE10_SCENARIO_EVIDENCE.items():
        path = _PACKAGE_ROOT / relative
        assert path.is_file(), f"scenario {number} evidence file missing: {relative}"
        source = path.read_text(encoding="utf-8")
        marker = f"def {test_name}("
        assert marker in source, (
            f"scenario {number} has no executable test {test_name} in {relative}"
        )
        start = source.index(marker)
        nxt = source.find("\ndef test_", start + 1)
        body = source[start:] if nxt < 0 else source[start:nxt]
        assert must_contain in body, (
            f"scenario {number} evidence {test_name} does not prove "
            f"{must_contain!r}"
        )


def test_slice10_freeze_workflow_builds_wheelhouse_and_forbids_packaging_skip() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")
    assert "build_packaging_wheelhouse.py" in workflow
    assert "TDP_PACKAGING_WHEELHOUSE" in workflow
    assert "TDP_SLICE10_FREEZE" in workflow
    packaging_block = next(
        block
        for block in workflow.split("- name:")
        if "Packaging install smoke" in block or "Slice 10 packaging" in block
    )
    assert "TDP_SLICE10_FREEZE" in packaging_block
    assert "-m packaging" in packaging_block
    assert (
        "tests/unit/test_slice10_scenario_matrix.py::"
        "test_slice10_installed_artifact_gate_executes_when_freeze_requested"
        in packaging_block
    )


def test_slice10_installed_artifact_gate_executes_when_freeze_requested() -> None:
    freeze = os.environ.get("TDP_SLICE10_FREEZE") == "1"
    if not freeze and not os.environ.get("TDP_PACKAGING_WHEELHOUSE"):
        pytest.skip(
            "scenario 14 is proven only when the packaging freeze gate supplies "
            "TDP_PACKAGING_WHEELHOUSE"
        )
    try:
        wheelhouse = resolve_packaging_wheelhouse()
    except PackagingWheelhouseError as exc:
        if freeze:
            raise AssertionError(
                "Slice 10 freeze forbids skipping the installed-artifact gate"
            ) from exc
        raise
    assert wheelhouse.is_dir()
    assert any(wheelhouse.glob("*.whl")), wheelhouse
