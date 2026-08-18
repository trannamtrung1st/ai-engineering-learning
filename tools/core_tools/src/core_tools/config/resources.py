"""Workspace-relative resource and skill loading primitives."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core_tools.config.errors import ConfigError
from core_tools.config.paths import assert_path_within_workspace, resolve_workspace_path


@dataclass(frozen=True)
class SkillEntry:
    path: Path
    content: str


def _path_has_glob_metacharacters(value: str) -> bool:
    return any(char in value for char in "*?[]")


def _expand_directory_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        raise ConfigError(
            f"path is not a directory: {directory}",
            path="resources",
        )
    files = sorted(
        path.resolve()
        for path in directory.rglob("*")
        if path.is_file()
    )
    if not files:
        raise ConfigError(
            f"directory contains no files: {directory}",
            path="resources",
        )
    return files


def resolve_expanded_path_list(
    entries: list[Any],
    *,
    workspace: Path,
    field: str,
    require_exists: bool = True,
) -> list[Path]:
    """Resolve, expand, deduplicate, and validate configured path entries."""

    resolved: list[Path] = []
    seen: set[Path] = set()

    for entry in entries:
        configured_value = str(entry).strip()
        if not configured_value:
            continue

        candidates: list[Path]
        if _path_has_glob_metacharacters(configured_value):
            if Path(configured_value).is_absolute():
                raise ConfigError(
                    f"{field}={configured_value!r} glob must be workspace-relative",
                    path=field,
                )
            base = workspace.resolve()
            try:
                matches = sorted(
                    path.resolve()
                    for path in base.glob(configured_value)
                    if path.is_file()
                )
            except (NotImplementedError, ValueError) as exc:
                raise ConfigError(
                    f"{field}={configured_value!r} is not a valid workspace glob",
                    path=field,
                ) from exc
            if not matches:
                raise ConfigError(
                    f"{field}={configured_value!r} matched no files in workspace "
                    f"{workspace}",
                    path=field,
                )
            candidates = matches
        else:
            candidate = resolve_workspace_path(configured_value, workspace=workspace)
            assert_path_within_workspace(
                candidate,
                workspace=workspace,
                field=field,
                configured_value=configured_value,
            )
            if candidate.is_dir():
                candidates = _expand_directory_files(candidate)
            elif candidate.is_file():
                candidates = [candidate]
            elif require_exists:
                raise ConfigError(
                    f"{field}={configured_value!r} not found in workspace "
                    f"{workspace}: {candidate}",
                    path=field,
                )
            else:
                candidates = [candidate]

        for candidate in candidates:
            assert_path_within_workspace(
                candidate,
                workspace=workspace,
                field=field,
                configured_value=configured_value,
            )
            if candidate in seen:
                continue
            seen.add(candidate)
            resolved.append(candidate)

    return resolved


def load_skills(
    entries: list[Any],
    *,
    workspace: Path,
    field: str,
) -> list[SkillEntry]:
    """Load configured skill files preserving configured order."""

    loaded: list[SkillEntry] = []
    seen_paths: set[Path] = set()

    for entry in entries:
        configured_value = str(entry).strip()
        if not configured_value:
            continue

        candidate = resolve_workspace_path(configured_value, workspace=workspace)
        assert_path_within_workspace(
            candidate,
            workspace=workspace,
            field=field,
            configured_value=configured_value,
        )

        if candidate.is_file():
            skill_path = candidate
        elif candidate.is_dir():
            skill_path = candidate / "SKILL.md"
        else:
            raise ConfigError(
                f"{field}={configured_value!r} not found in workspace "
                f"{workspace}: {candidate}",
                path=field,
            )

        if not skill_path.is_file():
            raise ConfigError(
                f"{field}={configured_value!r} requires SKILL.md at {skill_path}",
                path=field,
            )

        try:
            content = skill_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(
                f"failed to read skill file {skill_path} for {field}={configured_value!r}",
                path=field,
            ) from exc

        if not content.strip():
            raise ConfigError(
                f"skill file is empty: {skill_path}",
                path=field,
            )

        resolved_path = skill_path.resolve()
        if resolved_path in seen_paths:
            continue
        seen_paths.add(resolved_path)
        loaded.append(SkillEntry(path=resolved_path, content=content))

    return loaded


def resolve_provider_model(agent_context: dict[str, Any] | None, role: str) -> str | None:
    """Resolve the effective provider model for a role from an agent_context mapping."""

    if not isinstance(agent_context, dict):
        agent_context = {}

    role_section = agent_context.get(role)
    if not isinstance(role_section, dict):
        role_section = {}

    default_section = agent_context.get("default")
    if not isinstance(default_section, dict):
        default_section = {}

    for source in (
        role_section.get("model"),
        default_section.get("model"),
    ):
        if source is None:
            continue
        model = str(source).strip()
        if not model or model.lower() == "auto":
            continue
        return model
    return None
