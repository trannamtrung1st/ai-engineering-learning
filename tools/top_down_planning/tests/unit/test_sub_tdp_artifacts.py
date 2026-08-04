"""Tests for Sub-TDP artifact generation."""

from __future__ import annotations

import copy
from pathlib import Path

import yaml

from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.domain.sub_tdp_artifacts import build_child_config
from top_down_planning.orchestrator.sub_tdp_artifact_writer import write_sub_tdp_artifacts
from top_down_planning.domain.sub_tdp_units import derive_sub_tdp_units
from tests.unit.test_sub_tdp_units import _plan_with_root_children


def test_write_sub_tdp_artifacts_creates_files_within_workspace(tmp_path: Path) -> None:
    plan = _plan_with_root_children()
    units = derive_sub_tdp_units(plan)
    parent_config = copy.deepcopy(DEFAULT_CONFIG)
    parent_config["project"]["workspace"] = str(tmp_path.resolve())
    parent_config["run"]["output_goal"] = "Parent goal."
    parent_config["runtime"] = {"runs_dir": str((tmp_path / ".tdp" / "runs").resolve())}

    root_dir = write_sub_tdp_artifacts(
        tmp_path,
        units,
        parent_config=parent_config,
        state_file="temp/sub-tdps/state.yaml",
    )
    assert root_dir.is_dir()
    unit_dir = root_dir / units[0].directory
    assert (unit_dir / "task.md").is_file()
    assert (unit_dir / "output-goal.md").is_file()
    config_path = unit_dir / "config.yaml"
    assert config_path.is_file()
    child_cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert child_cfg.get("execution", {}).get("mode", "single") == "single"
    assert child_cfg["runtime"]["runs_dir"].endswith("runs")
    refs = child_cfg["run"]["input_refs"]
    assert any("task.md" in str(ref) for ref in refs)


def test_build_child_config_omits_execution_section() -> None:
    parent = copy.deepcopy(DEFAULT_CONFIG)
    parent["execution"] = {"mode": "sub_tdps"}
    unit = derive_sub_tdp_units(_plan_with_root_children())[0]
    child = build_child_config(
        parent,
        unit=unit,
        unit_relative_dir="temp/sub-tdps/01-test",
        workspace=Path("/tmp/ws"),
    )
    assert "execution" not in child
