"""Run configuration for the todos orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class RunConfig:
    workspace_root: Path
    todos_dir: str = "todos"
    allow_dirty: bool = True
    no_color: bool = False
    model: str | None = None
    stop_on_failure: bool | None = None
    auto_commit: bool | None = None
    agent_bin: str | None = None
    skip_probe: bool = False
    dry_run_prompts: bool = False
    dry_run: bool = False
    project_config: Path | None = None
    context_files: tuple[str, ...] = ()
    skip_commit: bool = False
    no_auto_repair_yaml: bool = False
    max_yaml_repair_attempts: int = 2
