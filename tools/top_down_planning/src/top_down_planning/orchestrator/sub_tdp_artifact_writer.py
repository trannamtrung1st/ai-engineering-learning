"""Write Sub-TDP child workspace artifacts (orchestration I/O)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core_tools.persistence import dump_yaml

from top_down_planning.domain.sub_tdp_artifacts import (
    build_child_config,
    build_child_task_markdown,
    orchestration_root_relative,
)
from top_down_planning.domain.sub_tdp_units import SubTdpUnit


def write_sub_tdp_artifacts(
    workspace: Path,
    units: list[SubTdpUnit],
    *,
    parent_config: dict[str, Any],
    state_file: str | None = None,
    parent_input_hint: str = "parent run input_refs",
) -> Path:
    root_rel = orchestration_root_relative(state_file)
    root_dir = workspace / root_rel
    root_dir.mkdir(parents=True, exist_ok=True)

    for unit in units:
        unit_rel = f"{root_rel}/{unit.directory}"
        unit_dir = workspace / unit_rel
        unit_dir.mkdir(parents=True, exist_ok=True)
        (unit_dir / "runs").mkdir(exist_ok=True)

        task_path = unit_dir / "task.md"
        task_path.write_text(
            build_child_task_markdown(unit, parent_input_hint=parent_input_hint),
            encoding="utf-8",
        )
        goal_path = unit_dir / "output-goal.md"
        goal_path.write_text(unit.outcome.strip() + "\n", encoding="utf-8")

        child_config = build_child_config(
            parent_config,
            unit=unit,
            unit_relative_dir=unit_rel.replace("\\", "/"),
            workspace=workspace,
        )
        config_path = unit_dir / "config.yaml"
        config_path.write_text(dump_yaml(child_config) + "\n", encoding="utf-8")

    return root_dir


__all__ = ["write_sub_tdp_artifacts"]
