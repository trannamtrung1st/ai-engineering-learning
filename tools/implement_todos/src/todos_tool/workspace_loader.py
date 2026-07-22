"""Repair-aware workspace loading for mutating reload boundaries."""

from __future__ import annotations

from dataclasses import dataclass

from todos_tool.console_renderer import ConsoleRenderer
from todos_tool.cursor_client import CursorClient
from todos_tool.errors import ValidationError
from todos_tool.manifest import Workspace, load_workspace
from todos_tool.run_config import RunConfig
from todos_tool.profile_loader import ResolvedContextFile
from todos_tool.project_context import ProjectContext
from todos_tool.yaml_repair import (
    Recoverability,
    YamlRepairCoordinator,
    classify_validation_error,
)


@dataclass
class DryRunReport:
    repair_required: bool = False
    diagnostic: str | None = None


async def load_workspace_repairable(
    config: RunConfig,
    *,
    allow_repair: bool,
    dry_run_report: DryRunReport | None = None,
    client: CursorClient | None = None,
    project_context: ProjectContext | None = None,
    resolved_context_files: list[ResolvedContextFile] | None = None,
    renderer: ConsoleRenderer | None = None,
) -> Workspace:
    """Load the workspace, optionally invoking bounded YAML repair."""
    try:
        return load_workspace(config.workspace_root, config.todos_dir)
    except ValidationError as exc:
        if dry_run_report is not None:
            dry_run_report.repair_required = True
            dry_run_report.diagnostic = str(exc)

        if config.dry_run:
            raise exc

        if not allow_repair or config.no_auto_repair_yaml:
            raise exc

        if classify_validation_error(exc) != Recoverability.REPAIRABLE:
            raise exc

        if config.max_yaml_repair_attempts <= 0:
            raise exc

        if client is None:
            raise exc

        if renderer is None:
            renderer = ConsoleRenderer(no_color=config.no_color)

        set_name = config.todos_dir.rstrip("/").rsplit("/", 1)[-1] or "todos"
        coordinator = YamlRepairCoordinator(
            workspace_root=config.workspace_root,
            todos_dir=config.todos_dir,
            client=client,
            project_context=project_context or ProjectContext.neutral(),
            resolved_context_files=resolved_context_files or [],
            renderer=renderer,
            max_attempts=config.max_yaml_repair_attempts,
            set_name=set_name,
        )
        return await coordinator.repair(exc)
