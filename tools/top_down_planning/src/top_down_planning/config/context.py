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
    resolve_workspace_path,
)
from core_tools.config.errors import ConfigError
from core_tools.persistence.digests import digest_file, digest_text

from top_down_planning.config.resolve import resolve_output_goal_text

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
    input_refs: tuple[Path, ...]
    output_goal: str
    resources: tuple[Path, ...]
    skills: tuple[SkillEntry, ...]


def resolve_provider_model(config: dict[str, Any], role: str) -> str | None:
    """Resolve the effective provider model for a role."""

    agent_context = config.get("agent_context")
    if not isinstance(agent_context, dict):
        agent_context = {}
    return _resolve_provider_model(agent_context, role)


def _resolve_input_ref_paths(
    config: dict[str, Any],
    *,
    workspace: Path,
) -> tuple[Path, ...]:
    run_section = config.get("run")
    if not isinstance(run_section, dict):
        run_section = {}

    return tuple(
        resolve_expanded_path_list(
            list(run_section.get("input_refs") or []),
            workspace=workspace,
            field="run.input_refs",
        )
    )


def _excluded_supporting_paths(
    config: dict[str, Any],
    *,
    workspace: Path,
) -> set[Path]:
    """Paths that must not appear as supporting resources (output-goal file)."""

    run_section = config.get("run")
    if not isinstance(run_section, dict):
        return set()

    file_ref = str(run_section.get("output_goal_file") or "").strip()
    if not file_ref:
        return set()

    return {resolve_workspace_path(file_ref, workspace=workspace).resolve()}


def _resolve_supporting_resources(
    entries: list[Any],
    *,
    workspace: Path,
    forbidden: set[Path],
    field: str,
) -> tuple[Path, ...]:
    if not entries:
        return ()

    resolved = resolve_expanded_path_list(
        entries,
        workspace=workspace,
        field=field,
    )
    overlaps = sorted(
        {path.resolve() for path in resolved} & forbidden,
        key=lambda path: str(path),
    )
    if overlaps:
        joined = ", ".join(str(path) for path in overlaps)
        raise ConfigError(
            f"{field} must not repeat run contracts or other supporting resources: {joined}",
            path=field,
        )
    return tuple(resolved)


def resolve_effective_role_context(
    config: dict[str, Any],
    role: AgentRole,
    *,
    workspace: Path,
    output_goal: str | None = None,
) -> EffectiveRoleContext:
    """Resolve authoritative run contracts and supporting role context."""

    agent_context = config.get("agent_context")
    if not isinstance(agent_context, dict):
        agent_context = {}

    role_section = agent_context.get(role)
    if not isinstance(role_section, dict):
        role_section = {}

    default_section = agent_context.get("default")
    if not isinstance(default_section, dict):
        default_section = {}

    input_refs = _resolve_input_ref_paths(config, workspace=workspace)
    goal_text = output_goal if output_goal is not None else resolve_output_goal_text(
        config,
        base_dir=workspace,
    )

    forbidden = set(input_refs) | _excluded_supporting_paths(config, workspace=workspace)

    default_resources = _resolve_supporting_resources(
        list(default_section.get("resources") or []),
        workspace=workspace,
        forbidden=forbidden,
        field="agent_context.default.resources",
    )
    forbidden |= set(default_resources)

    role_resources = _resolve_supporting_resources(
        list(role_section.get("resources") or []),
        workspace=workspace,
        forbidden=forbidden,
        field=f"agent_context.{role}.resources",
    )
    resources = default_resources + role_resources

    skill_entries: list[Any] = []
    skill_entries.extend(default_section.get("skills") or [])
    skill_entries.extend(role_section.get("skills") or [])

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
        input_refs=input_refs,
        output_goal=goal_text,
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


def _role_context_digest_payload(context: EffectiveRoleContext) -> dict[str, Any]:
    """Digest payload for supporting agent context only (not run contracts)."""

    return {
        "model": context.model,
        "resources": [str(path) for path in context.resources],
        "skills": [str(entry.path) for entry in context.skills],
        "resource_digests": _resource_digest_entries(context.resources),
        "skill_digests": _skill_digest_entries(context.skills),
    }


def build_context_digest_payload(
    config: dict[str, Any],
    *,
    workspace: Path,
) -> dict[str, Any]:
    """Build deterministic supporting-context payload for ``digests.context`` binding."""

    roles_payload: dict[str, Any] = {}
    for role in ("planner", "producer", "reviewer"):
        context = resolve_effective_role_context(config, role, workspace=workspace)
        roles_payload[role] = _role_context_digest_payload(context)

    return {
        "workspace": str(workspace.resolve()),
        "roles": roles_payload,
    }


def compute_context_digest_from_config(
    config: dict[str, Any],
    *,
    workspace: Path,
) -> str:
    """Compute the context digest for a resolved configuration."""

    from top_down_planning.persistence.digests import compute_context_digest

    payload = build_context_digest_payload(config, workspace=workspace)
    return compute_context_digest(payload)
