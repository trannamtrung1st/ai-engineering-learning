"""Cwd-based path resolution for configured filesystem paths."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core_tools.config.errors import ConfigError


@dataclass(frozen=True)
class PathResolutionContext:
    """Base context for resolving relative paths from config values."""

    cwd: Path


def resolve_path(value: str | Path, *, cwd: Path) -> Path:
    """Resolve a configured path against the process working directory."""

    path = Path(value)
    if not path.is_absolute():
        path = cwd / path
    return path.resolve()


def resolve_workspace_path(value: str | Path, *, workspace: Path) -> Path:
    """Resolve a configured path relative to the project workspace."""

    path = Path(value)
    if not path.is_absolute():
        path = workspace / path
    return path.resolve()


def is_path_within_workspace(path: Path, *, workspace: Path) -> bool:
    """Return True when ``path`` resolves inside ``workspace``."""

    try:
        path.resolve().relative_to(workspace.resolve())
        return True
    except ValueError:
        return False


def _configured_workspace_value(
    config: dict[str, Any],
    section: str,
    key: str,
) -> str | None:
    block = config.get(section)
    if not isinstance(block, dict):
        return None
    configured = block.get(key)
    if configured is None:
        return None
    stripped = str(configured).strip()
    return stripped or None


def resolve_workspace(
    config: dict[str, Any],
    *,
    cwd: Path,
    section: str = "project",
    key: str = "workspace",
) -> Path:
    """
    Resolve the canonical project workspace from a configured section/key.

    Relative values resolve against ``cwd``. Omitted or empty values default to
    ``cwd``.
    """

    configured = _configured_workspace_value(config, section, key)
    if configured is None:
        return cwd.resolve()
    return resolve_path(configured, cwd=cwd)


def assert_path_within_workspace(
    resolved: Path,
    *,
    workspace: Path,
    field: str,
    configured_value: str,
) -> None:
    """Raise ``ConfigError`` when ``resolved`` escapes the workspace."""

    if not is_path_within_workspace(resolved, workspace=workspace):
        raise ConfigError(
            f"{field}={configured_value!r} resolves outside project workspace "
            f"{workspace}: {resolved}",
            path=field,
        )
