"""Effective agent context resolution and context digest payloads."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from core_tools.config.errors import ConfigError
from core_tools.persistence.digests import digest_file, digest_text

from top_down_planning.config.defaults import ALLOWED_AGENT_CONTEXT_ROLES
from top_down_planning.config.paths import (
    assert_path_within_workspace,
    resolve_workspace_path,
)
from top_down_planning.persistence.digests import compute_context_digest

AgentRole = Literal["planner", "producer", "reviewer"]

__all__ = [
    "AgentRole",
    "EffectiveRoleContext",
    "SkillEntry",
    "build_agent_context_manifest_payload",
    "build_context_digest_payload",
    "compute_context_digest_from_config",
    "load_skills",
    "resolve_effective_role_context",
    "resolve_expanded_path_list",
    "resolve_provider_model",
]


@dataclass(frozen=True)
class SkillEntry:
    path: Path
    content: str


@dataclass(frozen=True)
class EffectiveRoleContext:
    role: str
    model: str | None
    resources: tuple[Path, ...]
    skills: tuple[SkillEntry, ...]


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
            base = workspace.resolve()
            matches = sorted(
                path.resolve()
                for path in base.glob(configured_value)
                if path.is_file()
            )
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


def resolve_provider_model(config: dict[str, Any], role: str) -> str | None:
    """Resolve the effective provider model for a role."""

    agent_context = config.get("agent_context")
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


def resolve_effective_role_context(
    config: dict[str, Any],
    role: AgentRole,
    *,
    workspace: Path,
) -> EffectiveRoleContext:
    """Resolve additive resources/skills and role-specific model selection."""

    agent_context = config.get("agent_context")
    if not isinstance(agent_context, dict):
        agent_context = {}

    role_section = agent_context.get(role)
    if not isinstance(role_section, dict):
        role_section = {}

    default_section = agent_context.get("default")
    if not isinstance(default_section, dict):
        default_section = {}

    project_section = config.get("project")
    if not isinstance(project_section, dict):
        project_section = {}

    resource_entries: list[Any] = []
    resource_entries.extend(project_section.get("resources") or [])
    resource_entries.extend(default_section.get("resources") or [])
    resource_entries.extend(role_section.get("resources") or [])

    skill_entries: list[Any] = []
    skill_entries.extend(default_section.get("skills") or [])
    skill_entries.extend(role_section.get("skills") or [])

    resources = tuple(
        resolve_expanded_path_list(
            resource_entries,
            workspace=workspace,
            field="resources",
        )
    )
    skills = tuple(
        load_skills(
            skill_entries,
            workspace=workspace,
            field="skills",
        )
    )

    return EffectiveRoleContext(
        role=role,
        model=resolve_provider_model(config, role),
        resources=resources,
        skills=skills,
    )


def build_agent_context_manifest_payload(
    context: EffectiveRoleContext,
) -> dict[str, Any]:
    """Build the manifest fragment attached to fresh agent sessions."""

    return {
        "agent_context": {
            "role": context.role,
            "resources": [str(path) for path in context.resources],
            "skills": [
                {"path": str(entry.path), "content": entry.content}
                for entry in context.skills
            ],
        }
    }


def _resource_digest_entries(paths: tuple[Path, ...]) -> list[dict[str, str]]:
    return [
        {"path": str(path), "digest": digest_file(path)}
        for path in paths
    ]


def _skill_digest_entries(skills: tuple[SkillEntry, ...]) -> list[dict[str, str]]:
    return [
        {"path": str(entry.path), "digest": digest_text(entry.content)}
        for entry in skills
    ]


def build_context_digest_payload(
    config: dict[str, Any],
    *,
    workspace: Path,
) -> dict[str, Any]:
    """Build deterministic context payload for digest binding."""

    project_section = config.get("project")
    if not isinstance(project_section, dict):
        project_section = {}

    project_resources = tuple(
        resolve_expanded_path_list(
            list(project_section.get("resources") or []),
            workspace=workspace,
            field="project.resources",
        )
    )

    roles_payload: dict[str, Any] = {}
    for role in ("planner", "producer", "reviewer"):
        context = resolve_effective_role_context(config, role, workspace=workspace)
        roles_payload[role] = {
            "model": context.model,
            "resources": [str(path) for path in context.resources],
            "skills": [str(entry.path) for entry in context.skills],
            "resource_digests": _resource_digest_entries(context.resources),
            "skill_digests": _skill_digest_entries(context.skills),
        }

    return {
        "workspace": str(workspace.resolve()),
        "project_resources": [str(path) for path in project_resources],
        "project_resource_digests": _resource_digest_entries(project_resources),
        "roles": roles_payload,
    }


def compute_context_digest_from_config(
    config: dict[str, Any],
    *,
    workspace: Path,
) -> str:
    """Compute the context digest for a resolved configuration."""

    payload = build_context_digest_payload(config, workspace=workspace)
    return compute_context_digest(payload)
