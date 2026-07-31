"""Effective agent context resolution and context spec/snapshot digest payloads."""

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
from core_tools.config.paths import assert_path_within_workspace
from core_tools.persistence.digests import digest_file, digest_text

from top_down_planning.config.resolve import resolve_output_goal_text

AgentRole = Literal["planner", "producer", "reviewer"]

MISSING_RESOURCE_FILE_DIGEST = digest_text("<missing-resource-file>")

__all__ = [
    "AgentRole",
    "EffectiveRoleContext",
    "build_agent_context_manifest_payload",
    "build_context_spec_payload",
    "build_context_snapshot_payload",
    "compute_context_snapshot_digest_from_config",
    "compute_context_snapshot_digest_from_payload",
    "compute_context_spec_digest_from_config",
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


def _path_has_glob_metacharacters(value: str) -> bool:
    return any(char in value for char in "*?[]")


def _normalize_resource_selection(
    entries: list[Any],
    *,
    workspace: Path,
    field: str,
) -> tuple[str, ...]:
    """Normalize configured resource path selection/order without expanding contents.

    Directory entries remain directory paths. File entries remain file paths. Glob
    patterns remain the configured pattern string. This is the context **spec**
    binding surface for resource selection.
    """

    selected: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        configured_value = str(entry).strip()
        if not configured_value:
            continue

        if _path_has_glob_metacharacters(configured_value):
            key = configured_value
        else:
            candidate = resolve_workspace_path(configured_value, workspace=workspace)
            assert_path_within_workspace(
                candidate,
                workspace=workspace,
                field=field,
                configured_value=configured_value,
            )
            key = str(candidate.resolve())

        if key in seen:
            continue
        seen.add(key)
        selected.append(key)
    return tuple(selected)


def _agent_context_sections(
    config: dict[str, Any],
    role: AgentRole,
) -> tuple[dict[str, Any], dict[str, Any]]:
    agent_context = config.get("agent_context")
    if not isinstance(agent_context, dict):
        agent_context = {}

    role_section = agent_context.get(role)
    if not isinstance(role_section, dict):
        role_section = {}

    default_section = agent_context.get("default")
    if not isinstance(default_section, dict):
        default_section = {}

    return default_section, role_section


def _resource_selection_for_role(
    config: dict[str, Any],
    role: AgentRole,
    *,
    workspace: Path,
) -> tuple[str, ...]:
    default_section, role_section = _agent_context_sections(config, role)
    default_entries = list(default_section.get("resources") or [])
    role_entries = list(role_section.get("resources") or [])
    return _normalize_resource_selection(
        default_entries,
        workspace=workspace,
        field="agent_context.default.resources",
    ) + _normalize_resource_selection(
        role_entries,
        workspace=workspace,
        field=f"agent_context.{role}.resources",
    )


def _skills_for_role(
    config: dict[str, Any],
    role: AgentRole,
    *,
    workspace: Path,
) -> tuple[SkillEntry, ...]:
    default_section, role_section = _agent_context_sections(config, role)
    skill_entries: list[Any] = []
    skill_entries.extend(default_section.get("skills") or [])
    skill_entries.extend(role_section.get("skills") or [])
    return tuple(
        load_skills(
            skill_entries,
            workspace=workspace,
            field="skills",
        )
    )


def _role_context_spec_from_config(
    config: dict[str, Any],
    role: AgentRole,
    *,
    workspace: Path,
) -> dict[str, Any]:
    """Stable agent-context declaration: models, resource selection, skill paths."""

    skills = _skills_for_role(config, role, workspace=workspace)
    return {
        "model": resolve_provider_model(config, role),
        "resources": list(_resource_selection_for_role(config, role, workspace=workspace)),
        "skills": [str(entry.path) for entry in skills],
    }


def _collect_materialized_resource_files(
    config: dict[str, Any],
    *,
    workspace: Path,
) -> list[Path]:
    """Union of supporting resource file paths for snapshot binding.

    Expands globs and directories like effective agent context. Missing file
    paths are retained so drift (including deletions) is detectable at resume.
    """

    workspace_resolved = workspace.resolve()
    seen: set[str] = set()
    collected: list[Path] = []

    def add_path(path: Path) -> None:
        key = str(path.resolve())
        if key in seen:
            return
        seen.add(key)
        collected.append(path.resolve())

    for role in ("planner", "producer", "reviewer"):
        default_section, role_section = _agent_context_sections(config, role)
        entries: list[Any] = []
        entries.extend(default_section.get("resources") or [])
        entries.extend(role_section.get("resources") or [])
        field = f"agent_context.{role}.resources"
        for entry in entries:
            configured_value = str(entry).strip()
            if not configured_value:
                continue
            if _path_has_glob_metacharacters(configured_value):
                for match in sorted(workspace_resolved.glob(configured_value)):
                    if match.is_file():
                        add_path(match)
                continue
            candidate = resolve_workspace_path(configured_value, workspace=workspace)
            assert_path_within_workspace(
                candidate,
                workspace=workspace,
                field=field,
                configured_value=configured_value,
            )
            if candidate.is_file():
                add_path(candidate)
                continue
            if candidate.is_dir():
                for file_path in sorted(candidate.rglob("*")):
                    if file_path.is_file():
                        add_path(file_path)
                continue
            add_path(candidate)
    return collected


def _all_skill_digest_entries(
    config: dict[str, Any],
    *,
    workspace: Path,
) -> list[dict[str, str]]:
    seen: set[str] = set()
    entries: list[dict[str, str]] = []
    for role in ("planner", "producer", "reviewer"):
        for entry in _skills_for_role(config, role, workspace=workspace):
            key = str(entry.path)
            if key in seen:
                continue
            seen.add(key)
            entries.append({"path": key, "digest": digest_text(entry.content)})
    return sorted(entries, key=lambda item: item["path"])


def build_context_spec_payload(
    config: dict[str, Any],
    *,
    workspace: Path,
) -> dict[str, Any]:
    """Build deterministic context **spec** payload (declarations, not resource bytes)."""

    roles_payload: dict[str, Any] = {}
    for role in ("planner", "producer", "reviewer"):
        roles_payload[role] = _role_context_spec_from_config(
            config,
            role,
            workspace=workspace,
        )

    return {
        "workspace": str(workspace.resolve()),
        "roles": roles_payload,
    }


def build_context_snapshot_payload(
    config: dict[str, Any],
    *,
    workspace: Path,
) -> dict[str, Any]:
    """Build materialized context snapshot: resource file digests and skill contents."""

    resource_digests = [
        {
            "path": str(path),
            "digest": digest_file(path) if path.is_file() else MISSING_RESOURCE_FILE_DIGEST,
        }
        for path in _collect_materialized_resource_files(config, workspace=workspace)
    ]
    resource_digests.sort(key=lambda entry: entry["path"])
    return {
        "workspace": str(workspace.resolve()),
        "resource_digests": resource_digests,
        "skill_digests": _all_skill_digest_entries(config, workspace=workspace),
    }


def compute_context_spec_digest_from_config(
    config: dict[str, Any],
    *,
    workspace: Path,
) -> str:
    from top_down_planning.persistence.digests import digest_binding_payload

    payload = build_context_spec_payload(config, workspace=workspace)
    return digest_binding_payload(payload)


def compute_context_snapshot_digest_from_payload(payload: dict[str, Any]) -> str:
    from top_down_planning.persistence.digests import digest_binding_payload

    return digest_binding_payload(payload)


def compute_context_snapshot_digest_from_config(
    config: dict[str, Any],
    *,
    workspace: Path,
) -> str:
    payload = build_context_snapshot_payload(config, workspace=workspace)
    return compute_context_snapshot_digest_from_payload(payload)


def resolve_effective_role_context(
    config: dict[str, Any],
    role: AgentRole,
    *,
    workspace: Path,
    output_goal: str | None = None,
) -> EffectiveRoleContext:
    """Resolve authoritative run contracts and supporting role context."""

    default_section, role_section = _agent_context_sections(config, role)

    input_refs = _resolve_input_ref_paths(config, workspace=workspace)
    goal_text = output_goal if output_goal is not None else resolve_output_goal_text(
        config,
        base_dir=workspace,
    )

    forbidden = set(input_refs) | _excluded_supporting_paths(config, workspace=workspace)

    default_entries = list(default_section.get("resources") or [])
    role_entries = list(role_section.get("resources") or [])

    default_resources = _resolve_supporting_resources(
        default_entries,
        workspace=workspace,
        forbidden=forbidden,
        field="agent_context.default.resources",
    )
    forbidden |= set(default_resources)

    role_resources = _resolve_supporting_resources(
        role_entries,
        workspace=workspace,
        forbidden=forbidden,
        field=f"agent_context.{role}.resources",
    )
    resources = default_resources + role_resources
    skills = _skills_for_role(config, role, workspace=workspace)

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
