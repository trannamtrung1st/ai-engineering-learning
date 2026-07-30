"""Effective agent context resolution and context digest payloads."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from core_tools.config import (
    SkillEntry,
    load_skills,
    resolve_expanded_path_list,
    resolve_provider_model as _resolve_provider_model,
)
from core_tools.persistence.digests import digest_file, digest_text

from top_down_planning.persistence.digests import compute_context_digest

AgentRole = Literal["planner", "producer", "reviewer"]

__all__ = [
    "AgentRole",
    "EffectiveRoleContext",
    "build_agent_context_manifest_payload",
    "build_context_digest_payload",
    "compute_context_digest_from_config",
    "resolve_effective_role_context",
    "resolve_provider_model",
]


@dataclass(frozen=True)
class EffectiveRoleContext:
    role: str
    model: str | None
    resources: tuple[Path, ...]
    skills: tuple[SkillEntry, ...]


def resolve_provider_model(config: dict[str, Any], role: str) -> str | None:
    """Resolve the effective provider model for a role."""

    agent_context = config.get("agent_context")
    if not isinstance(agent_context, dict):
        agent_context = {}
    return _resolve_provider_model(agent_context, role)


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
