"""Cwd-based path resolution for configured filesystem paths."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


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


def resolve_workspace(config: dict[str, Any], *, cwd: Path) -> Path:
    """
    Resolve the provider workspace from ``run.workspace`` or process cwd.

    Relative ``run.workspace`` values resolve against ``cwd``. Omitted or empty
    values default to ``cwd``.
    """

    run_section = config.get("run")
    if not isinstance(run_section, dict):
        return cwd.resolve()

    configured = run_section.get("workspace")
    if configured is None:
        return cwd.resolve()

    stripped = str(configured).strip()
    if not stripped:
        return cwd.resolve()

    return resolve_path(stripped, cwd=cwd)
