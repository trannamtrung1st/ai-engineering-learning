"""Pure Sub-TDP artifact builders (no filesystem or outer-layer I/O)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from top_down_planning.domain.sub_tdp_units import SubTdpUnit

SUB_TDP_ORCHESTRATION_ROOT = "temp/sub-tdps"


def orchestration_root_relative(state_file: str | None) -> str:
    if state_file:
        path = Path(state_file)
        if path.name == "state.yaml":
            return str(path.parent).replace("\\", "/") or SUB_TDP_ORCHESTRATION_ROOT
        return str(path).replace("\\", "/")
    return SUB_TDP_ORCHESTRATION_ROOT


def build_child_task_markdown(unit: SubTdpUnit, *, parent_input_hint: str) -> str:
    return (
        f"# Sub-TDP: {unit.title}\n\n"
        "## Parent context\n\n"
        f"This is a Sub-TDP of the parent objective. "
        f"Authoritative parent input: `{parent_input_hint}`.\n\n"
        "## Local outcome\n\n"
        f"{unit.outcome}\n"
    )


def build_child_config(
    parent_config: dict[str, Any],
    *,
    unit: SubTdpUnit,
    unit_relative_dir: str,
    workspace: Path,
) -> dict[str, Any]:
    child = copy.deepcopy(parent_config)
    child.pop("execution", None)
    runtime = dict(child.get("runtime") or {})
    runtime["runs_dir"] = f"{unit_relative_dir}/runs"
    child["runtime"] = runtime
    project = dict(child.get("project") or {})
    project["workspace"] = str(workspace.resolve())
    child["project"] = project
    run_section = dict(child.get("run") or {})
    task_ref = f"{unit_relative_dir}/task.md"
    goal_ref = f"{unit_relative_dir}/output-goal.md"
    run_section["input_refs"] = [task_ref]
    run_section.pop("output_goal", None)
    run_section["output_goal_file"] = goal_ref
    child["run"] = run_section
    return child


__all__ = [
    "SUB_TDP_ORCHESTRATION_ROOT",
    "build_child_config",
    "build_child_task_markdown",
    "orchestration_root_relative",
]
