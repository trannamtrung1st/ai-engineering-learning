"""Effective agent context resolution and context spec/snapshot digest payloads."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from core_tools.config import (
    SkillEntry,
    load_skills,
    resolve_expanded_path_list,
    resolve_workspace_path,
)
from core_tools.config.errors import ConfigError
from core_tools.config.paths import assert_path_within_workspace
from core_tools.persistence.digests import digest_file, digest_text

from top_down_planning.config.activities import (
    ALLOWED_AGENT_ACTIVITIES,
    ALLOWED_AGENT_ROLES,
    AgentActivity,
    assert_valid_activity_role_pair,
    role_for_activity,
)
from top_down_planning.config.bundled_skills import (
    bundled_skill_binding_key,
    bundled_skills_enabled,
    load_bundled_skills_for_role,
)
from top_down_planning.config.resolve import resolve_output_goal_text
from top_down_planning.config.snapshot_policy import (
    _has_glob_metacharacters,
    expand_workspace_resource_glob,
)

AgentRole = Literal["planner", "producer", "reviewer"]

MISSING_RESOURCE_FILE_DIGEST = digest_text("<missing-resource-file>")
MISSING_GUIDANCE_FILE_DIGEST = digest_text("<missing-guidance-file>")
_GUIDANCE_ENTRY_KEYS = frozenset({"text", "file"})

__all__ = [
    "AgentActivity",
    "AgentRole",
    "EffectiveActivityContext",
    "GuidanceEntry",
    "build_agent_context_manifest_payload",
    "build_context_spec_payload",
    "build_context_snapshot_payload",
    "build_context_snapshot_payload_with_diagnostics",
    "compute_context_snapshot_digest_from_config",
    "compute_context_snapshot_digest_from_payload",
    "compute_context_spec_digest_from_config",
    "compute_effective_context_digest",
    "resolve_effective_activity_context",
    "resolve_provider_model",
    "resolve_provider_model_for_activity",
    "validate_guidance_for_binding",
]


@dataclass(frozen=True)
class GuidanceEntry:
    """One resolved advisory guidance string, optionally bound to a source file."""

    text: str
    path: Path | None = None


@dataclass(frozen=True)
class EffectiveActivityContext:
    role: str
    activity: str
    model: str | None
    input_refs: tuple[Path, ...]
    output_goal: str
    guidance: tuple[str, ...]
    resources: tuple[Path, ...]
    skills: tuple[SkillEntry, ...]
    context_digest: str


def _agent_context_root(config: dict[str, Any]) -> dict[str, Any]:
    agent_context = config.get("agent_context")
    if not isinstance(agent_context, dict):
        return {}
    return agent_context


def _default_overlay_section(config: dict[str, Any]) -> dict[str, Any]:
    section = _agent_context_root(config).get("default")
    return section if isinstance(section, dict) else {}


def _role_overlay_section(config: dict[str, Any], role: AgentRole) -> dict[str, Any]:
    roles = _agent_context_root(config).get("roles")
    if not isinstance(roles, dict):
        return {}
    section = roles.get(role)
    return section if isinstance(section, dict) else {}


def _activity_overlay_section(
    config: dict[str, Any],
    activity: AgentActivity,
) -> dict[str, Any]:
    activities = _agent_context_root(config).get("activities")
    if not isinstance(activities, dict):
        return {}
    section = activities.get(activity)
    return section if isinstance(section, dict) else {}


def _overlay_sections(
    config: dict[str, Any],
    role: AgentRole,
    activity: AgentActivity,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    return (
        _default_overlay_section(config),
        _role_overlay_section(config, role),
        _activity_overlay_section(config, activity),
    )


def _resolve_model_from_sections(*sections: dict[str, Any]) -> str | None:
    for section in reversed(sections):
        source = section.get("model")
        if source is None:
            continue
        model = str(source).strip()
        if not model or model.lower() == "auto":
            continue
        return model
    return None


def resolve_provider_model_for_activity(
    config: dict[str, Any],
    role: AgentRole,
    activity: AgentActivity,
) -> str | None:
    """Resolve effective model for a role/activity pair (default → role → activity)."""

    assert_valid_activity_role_pair(role, activity)
    default_section, role_section, activity_section = _overlay_sections(
        config,
        role,
        activity,
    )
    return _resolve_model_from_sections(
        default_section,
        role_section,
        activity_section,
    )


def resolve_provider_model(config: dict[str, Any], role: str) -> str | None:
    """Resolve model from default and role overlays only (no activity layer)."""

    default_section = _default_overlay_section(config)
    role_section = _role_overlay_section(config, role)  # type: ignore[arg-type]
    return _resolve_model_from_sections(default_section, role_section)


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

        if _has_glob_metacharacters(configured_value):
            expand_workspace_resource_glob(
                configured_value,
                workspace=workspace,
                field=field,
            )
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


def _merge_supporting_resource_selection(
    default_selection: tuple[str, ...],
    role_selection: tuple[str, ...],
) -> tuple[str, ...]:
    """Merge default then role resource keys, deduping role repeats of default."""

    merged = list(default_selection)
    seen = set(default_selection)
    for item in role_selection:
        if item in seen:
            continue
        seen.add(item)
        merged.append(item)
    return tuple(merged)


def _merge_resolved_resource_paths(
    default_resources: tuple[Path, ...],
    role_resources: tuple[Path, ...],
) -> tuple[Path, ...]:
    """Merge default then role paths, deduping role repeats of default."""

    seen = {path.resolve() for path in default_resources}
    merged = list(default_resources)
    for path in role_resources:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        merged.append(path)
    return tuple(merged)


def _merge_resolved_resource_paths_multi(
    *layers: tuple[Path, ...],
) -> tuple[Path, ...]:
    seen: set[Path] = set()
    merged: list[Path] = []
    for layer in layers:
        for path in layer:
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            merged.append(path)
    return tuple(merged)


def _merge_supporting_resource_selection_multi(
    *layers: tuple[str, ...],
) -> tuple[str, ...]:
    merged: list[str] = []
    seen: set[str] = set()
    for layer in layers:
        for item in layer:
            if item in seen:
                continue
            seen.add(item)
            merged.append(item)
    return tuple(merged)


def _resource_selection_for_overlay(
    config: dict[str, Any],
    *,
    workspace: Path,
    default_section: dict[str, Any],
    middle_section: dict[str, Any],
    middle_field: str,
    leaf_section: dict[str, Any] | None = None,
    leaf_field: str | None = None,
) -> tuple[str, ...]:
    layers = [
        _normalize_resource_selection(
            list(default_section.get("resources") or []),
            workspace=workspace,
            field="agent_context.default.resources",
        ),
        _normalize_resource_selection(
            list(middle_section.get("resources") or []),
            workspace=workspace,
            field=middle_field,
        ),
    ]
    if leaf_section is not None and leaf_field is not None:
        layers.append(
            _normalize_resource_selection(
                list(leaf_section.get("resources") or []),
                workspace=workspace,
                field=leaf_field,
            )
        )
    return _merge_supporting_resource_selection_multi(*layers)


def _resource_selection_for_role(
    config: dict[str, Any],
    role: AgentRole,
    *,
    workspace: Path,
) -> tuple[str, ...]:
    default_section, role_section = (
        _default_overlay_section(config),
        _role_overlay_section(config, role),
    )
    return _resource_selection_for_overlay(
        config,
        workspace=workspace,
        default_section=default_section,
        middle_section=role_section,
        middle_field=f"agent_context.roles.{role}.resources",
    )


def _resource_selection_for_activity(
    config: dict[str, Any],
    role: AgentRole,
    activity: AgentActivity,
    *,
    workspace: Path,
) -> tuple[str, ...]:
    default_section, role_section, activity_section = _overlay_sections(
        config,
        role,
        activity,
    )
    return _resource_selection_for_overlay(
        config,
        workspace=workspace,
        default_section=default_section,
        middle_section=role_section,
        middle_field=f"agent_context.roles.{role}.resources",
        leaf_section=activity_section,
        leaf_field=f"agent_context.activities.{activity}.resources",
    )


def _dedupe_skill_entries(entries: list[SkillEntry]) -> list[SkillEntry]:
    seen: set[Path] = set()
    deduped: list[SkillEntry] = []
    for entry in entries:
        resolved = entry.path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(entry)
    return deduped


def _skill_digest_key(entry: SkillEntry, *, workspace: Path) -> str:
    from top_down_planning.config.snapshot_policy import canonicalize_workspace_path

    bundled_key = bundled_skill_binding_key(entry.path)
    if bundled_key is not None:
        return bundled_key
    return canonicalize_workspace_path(entry.path, workspace=workspace)


def _skills_for_overlay(
    config: dict[str, Any],
    role: AgentRole,
    *,
    workspace: Path,
    default_section: dict[str, Any],
    middle_section: dict[str, Any],
    leaf_section: dict[str, Any] | None = None,
) -> tuple[SkillEntry, ...]:
    loaded: list[SkillEntry] = []
    if bundled_skills_enabled(config):
        loaded.extend(load_bundled_skills_for_role(role))

    configured_entries: list[Any] = []
    configured_entries.extend(default_section.get("skills") or [])
    configured_entries.extend(middle_section.get("skills") or [])
    if leaf_section is not None:
        configured_entries.extend(leaf_section.get("skills") or [])
    if configured_entries:
        loaded.extend(
            load_skills(
                configured_entries,
                workspace=workspace,
                field="skills",
            )
        )
    return tuple(_dedupe_skill_entries(loaded))


def _skills_for_role(
    config: dict[str, Any],
    role: AgentRole,
    *,
    workspace: Path,
) -> tuple[SkillEntry, ...]:
    default_section = _default_overlay_section(config)
    role_section = _role_overlay_section(config, role)
    return _skills_for_overlay(
        config,
        role,
        workspace=workspace,
        default_section=default_section,
        middle_section=role_section,
    )


def _skills_for_activity(
    config: dict[str, Any],
    role: AgentRole,
    activity: AgentActivity,
    *,
    workspace: Path,
) -> tuple[SkillEntry, ...]:
    default_section, role_section, activity_section = _overlay_sections(
        config,
        role,
        activity,
    )
    return _skills_for_overlay(
        config,
        role,
        workspace=workspace,
        default_section=default_section,
        middle_section=role_section,
        leaf_section=activity_section,
    )


def _validate_guidance_entry(
    entry: object,
    *,
    entry_field: str,
) -> tuple[bool, str]:
    """Return (is_text, normalized text or configured file path)."""

    if not isinstance(entry, dict):
        raise ConfigError(
            f"{entry_field} must be an object",
            path=entry_field,
        )

    extra_keys = sorted(set(entry) - _GUIDANCE_ENTRY_KEYS)
    if extra_keys:
        joined = ", ".join(extra_keys)
        raise ConfigError(
            f"{entry_field} has unsupported properties: {joined}",
            path=entry_field,
        )

    has_text = "text" in entry
    has_file = "file" in entry
    if has_text == has_file:
        raise ConfigError(
            f"{entry_field} must contain exactly one of text or file",
            path=entry_field,
        )

    if has_text:
        raw_text = entry.get("text")
        if not isinstance(raw_text, str) or not raw_text.strip():
            raise ConfigError(
                f"{entry_field}.text must not be empty",
                path=f"{entry_field}.text",
            )
        return True, raw_text.strip()

    raw_file = entry.get("file")
    if not isinstance(raw_file, str) or not raw_file.strip():
        raise ConfigError(
            f"{entry_field}.file must not be empty",
            path=f"{entry_field}.file",
        )
    return False, raw_file.strip()


def _resolve_guidance_file_path(
    configured_value: str,
    *,
    workspace: Path,
    field: str,
) -> Path:
    candidate = resolve_workspace_path(configured_value, workspace=workspace)
    assert_path_within_workspace(
        candidate,
        workspace=workspace,
        field=field,
        configured_value=configured_value,
    )
    return candidate.resolve()


def _read_guidance_file_content(
    path: Path,
    *,
    entry_field: str,
) -> str:
    if not path.is_file():
        raise ConfigError(
            f"{entry_field}.file does not exist: {path}",
            path=f"{entry_field}.file",
        )
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(
            f"{entry_field}.file cannot be read: {path}",
            path=f"{entry_field}.file",
        ) from exc
    except UnicodeDecodeError as exc:
        raise ConfigError(
            f"{entry_field}.file must be UTF-8 text: {path}",
            path=f"{entry_field}.file",
        ) from exc
    normalized = content.strip()
    if not normalized:
        raise ConfigError(
            f"{entry_field}.file must not be empty after trimming",
            path=f"{entry_field}.file",
        )
    return normalized


def _resolve_guidance_entries(
    entries: list[Any],
    *,
    workspace: Path,
    field: str,
    allow_missing_files: bool = False,
) -> tuple[GuidanceEntry, ...]:
    """Validate and resolve guidance entries as exactly one of text|file each.

    When ``allow_missing_files`` is true, missing or unreadable file entries are
    retained with empty text so snapshot digest comparison can surface drift.
    """

    if not isinstance(entries, list):
        raise ConfigError(f"{field} must be a list", path=field)

    resolved: list[GuidanceEntry] = []
    for index, entry in enumerate(entries):
        entry_field = f"{field}[{index}]"
        is_text, value = _validate_guidance_entry(entry, entry_field=entry_field)
        if is_text:
            resolved.append(GuidanceEntry(text=value))
            continue

        candidate = _resolve_guidance_file_path(
            value,
            workspace=workspace,
            field=f"{entry_field}.file",
        )
        if allow_missing_files:
            if not candidate.is_file():
                resolved.append(GuidanceEntry(text="", path=candidate))
                continue
            try:
                content = _read_guidance_file_content(candidate, entry_field=entry_field)
            except (ConfigError, OSError):
                resolved.append(GuidanceEntry(text="", path=candidate))
                continue
            resolved.append(GuidanceEntry(text=content, path=candidate))
            continue
        content = _read_guidance_file_content(candidate, entry_field=entry_field)
        resolved.append(GuidanceEntry(text=content, path=candidate))
    return tuple(resolved)


def _guidance_entries_for_overlay(
    *,
    workspace: Path,
    default_section: dict[str, Any],
    middle_section: dict[str, Any],
    middle_field: str,
    leaf_section: dict[str, Any] | None = None,
    leaf_field: str | None = None,
    allow_missing_files: bool = False,
) -> tuple[GuidanceEntry, ...]:
    entries = _resolve_guidance_entries(
        list(default_section.get("guidance") or []),
        workspace=workspace,
        field="agent_context.default.guidance",
        allow_missing_files=allow_missing_files,
    ) + _resolve_guidance_entries(
        list(middle_section.get("guidance") or []),
        workspace=workspace,
        field=middle_field,
        allow_missing_files=allow_missing_files,
    )
    if leaf_section is not None and leaf_field is not None:
        entries += _resolve_guidance_entries(
            list(leaf_section.get("guidance") or []),
            workspace=workspace,
            field=leaf_field,
            allow_missing_files=allow_missing_files,
        )
    return entries


def _guidance_entries_for_role(
    config: dict[str, Any],
    role: AgentRole,
    *,
    workspace: Path,
    allow_missing_files: bool = False,
) -> tuple[GuidanceEntry, ...]:
    default_section = _default_overlay_section(config)
    role_section = _role_overlay_section(config, role)
    return _guidance_entries_for_overlay(
        workspace=workspace,
        default_section=default_section,
        middle_section=role_section,
        middle_field=f"agent_context.roles.{role}.guidance",
        allow_missing_files=allow_missing_files,
    )


def _guidance_entries_for_activity(
    config: dict[str, Any],
    role: AgentRole,
    activity: AgentActivity,
    *,
    workspace: Path,
    allow_missing_files: bool = False,
) -> tuple[GuidanceEntry, ...]:
    default_section, role_section, activity_section = _overlay_sections(
        config,
        role,
        activity,
    )
    return _guidance_entries_for_overlay(
        workspace=workspace,
        default_section=default_section,
        middle_section=role_section,
        middle_field=f"agent_context.roles.{role}.guidance",
        leaf_section=activity_section,
        leaf_field=f"agent_context.activities.{activity}.guidance",
        allow_missing_files=allow_missing_files,
    )


def validate_guidance_for_binding(
    config: dict[str, Any],
    *,
    workspace: Path,
) -> None:
    """Strictly validate all configured guidance before persisting a new run binding."""

    for role in ALLOWED_AGENT_ROLES:
        _guidance_entries_for_role(
            config,
            role,  # type: ignore[arg-type]
            workspace=workspace,
            allow_missing_files=False,
        )
    for activity in ALLOWED_AGENT_ACTIVITIES:
        _guidance_entries_for_activity(
            config,
            role_for_activity(activity),  # type: ignore[arg-type]
            activity,  # type: ignore[arg-type]
            workspace=workspace,
            allow_missing_files=False,
        )


def _guidance_declarations_for_section(
    *,
    workspace: Path,
    sections: list[tuple[str, list[Any]]],
) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for field, configured in sections:
        for index, entry in enumerate(configured):
            entry_field = f"{field}[{index}]"
            is_text, value = _validate_guidance_entry(entry, entry_field=entry_field)
            if is_text:
                entries.append({"text": value})
                continue
            path = _resolve_guidance_file_path(
                value,
                workspace=workspace,
                field=f"{entry_field}.file",
            )
            entries.append({"file": str(path)})
    return entries


def _guidance_declarations_for_role(
    config: dict[str, Any],
    role: AgentRole,
    *,
    workspace: Path,
) -> list[dict[str, str]]:
    default_section = _default_overlay_section(config)
    role_section = _role_overlay_section(config, role)
    return _guidance_declarations_for_section(
        workspace=workspace,
        sections=[
            ("agent_context.default.guidance", list(default_section.get("guidance") or [])),
            (f"agent_context.roles.{role}.guidance", list(role_section.get("guidance") or [])),
        ],
    )


def _guidance_declarations_for_activity(
    config: dict[str, Any],
    role: AgentRole,
    activity: AgentActivity,
    *,
    workspace: Path,
) -> list[dict[str, str]]:
    default_section, role_section, activity_section = _overlay_sections(
        config,
        role,
        activity,
    )
    return _guidance_declarations_for_section(
        workspace=workspace,
        sections=[
            ("agent_context.default.guidance", list(default_section.get("guidance") or [])),
            (f"agent_context.roles.{role}.guidance", list(role_section.get("guidance") or [])),
            (
                f"agent_context.activities.{activity}.guidance",
                list(activity_section.get("guidance") or []),
            ),
        ],
    )


def _guidance_snapshot_entry(
    entry: GuidanceEntry,
    *,
    workspace: Path,
) -> dict[str, str]:
    from top_down_planning.config.snapshot_policy import canonicalize_workspace_path

    if entry.path is not None:
        relative = canonicalize_workspace_path(entry.path, workspace=workspace)
        if entry.path.is_file():
            return {
                "path": relative,
                "text": entry.text,
                "digest": digest_file(entry.path),
            }
        return {
            "path": relative,
            "text": "",
            "digest": MISSING_GUIDANCE_FILE_DIGEST,
        }
    return {
        "text": entry.text,
        "digest": digest_text(entry.text),
    }


def _skill_declarations_for_section(
    config: dict[str, Any],
    role: AgentRole,
    *,
    sections: list[dict[str, Any]],
    include_bundled: bool,
) -> list[str]:
    declarations: list[str] = []
    if include_bundled and bundled_skills_enabled(config):
        for entry in load_bundled_skills_for_role(role):
            binding_key = bundled_skill_binding_key(entry.path)
            if binding_key is not None:
                declarations.append(binding_key)
    for section in sections:
        for configured in list(section.get("skills") or []):
            value = str(configured).strip()
            if value and value not in declarations:
                declarations.append(value)
    return declarations


def _skill_declarations_for_role(
    config: dict[str, Any],
    role: AgentRole,
    *,
    workspace: Path,
) -> list[str]:
    del workspace
    return _skill_declarations_for_section(
        config,
        role,
        sections=[
            _default_overlay_section(config),
            _role_overlay_section(config, role),
        ],
        include_bundled=True,
    )


def _skill_declarations_for_activity(
    config: dict[str, Any],
    role: AgentRole,
    activity: AgentActivity,
    *,
    workspace: Path,
) -> list[str]:
    del workspace
    default_section, role_section, activity_section = _overlay_sections(
        config,
        role,
        activity,
    )
    return _skill_declarations_for_section(
        config,
        role,
        sections=[default_section, role_section, activity_section],
        include_bundled=False,
    )


def _overlay_context_spec_from_section(
    section: dict[str, Any],
) -> dict[str, Any]:
    model_raw = section.get("model")
    model: str | None
    if model_raw is None:
        model = None
    else:
        text = str(model_raw).strip()
        model = None if not text or text.lower() == "auto" else text
    return {
        "model": model,
        "guidance": list(section.get("guidance") or []),
        "resources": list(section.get("resources") or []),
        "skills": list(section.get("skills") or []),
    }


def _role_context_spec_from_config(
    config: dict[str, Any],
    role: AgentRole,
    *,
    workspace: Path,
) -> dict[str, Any]:
    return {
        "model": resolve_provider_model(config, role),
        "guidance": _guidance_declarations_for_role(config, role, workspace=workspace),
        "resources": list(_resource_selection_for_role(config, role, workspace=workspace)),
        "skills": _skill_declarations_for_role(config, role, workspace=workspace),
    }


def _activity_context_spec_from_config(
    config: dict[str, Any],
    activity: AgentActivity,
    *,
    workspace: Path,
) -> dict[str, Any]:
    role = role_for_activity(activity)  # type: ignore[arg-type]
    return {
        "model": resolve_provider_model_for_activity(config, role, activity),
        "guidance": _guidance_declarations_for_activity(
            config,
            role,
            activity,
            workspace=workspace,
        ),
        "resources": list(
            _resource_selection_for_activity(config, role, activity, workspace=workspace)
        ),
        "skills": _skill_declarations_for_activity(
            config,
            role,
            activity,
            workspace=workspace,
        ),
    }


def _configured_resource_entries(
    config: dict[str, Any],
) -> list[tuple[str, str]]:
    """Return ordered (field, configured_value) resource declarations."""

    entries: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _append(field: str, raw_entries: list[Any]) -> None:
        for entry in raw_entries:
            configured_value = str(entry).strip()
            if not configured_value or configured_value in seen:
                continue
            seen.add(configured_value)
            entries.append((field, configured_value))

    default_section = _default_overlay_section(config)
    _append(
        "agent_context.default.resources",
        list(default_section.get("resources") or []),
    )
    roles = _agent_context_root(config).get("roles")
    if isinstance(roles, dict):
        for role in ALLOWED_AGENT_ROLES:
            role_section = roles.get(role)
            if isinstance(role_section, dict):
                _append(
                    f"agent_context.roles.{role}.resources",
                    list(role_section.get("resources") or []),
                )
    activities = _agent_context_root(config).get("activities")
    if isinstance(activities, dict):
        for activity in ALLOWED_AGENT_ACTIVITIES:
            activity_section = activities.get(activity)
            if isinstance(activity_section, dict):
                _append(
                    f"agent_context.activities.{activity}.resources",
                    list(activity_section.get("resources") or []),
                )
    return entries


def _materialize_resource_digests(
    config: dict[str, Any],
    *,
    workspace: Path,
) -> tuple[dict[str, str], "SnapshotDiagnostics"]:
    """Materialize resource snapshot digests via SnapshotPolicy.collect (§10).

    Direct files (including missing) always bind; directory walks and glob expansion
    filter discovered files. Skills/guidance are not handled here.
    """

    from top_down_planning.config.snapshot_diagnostics import SnapshotDiagnostics
    from top_down_planning.config.snapshot_policy import CanonicalPathError, SnapshotPolicy

    policy = SnapshotPolicy.from_config(config, workspace=workspace)
    resources: list[str] = []
    for field, configured_value in _configured_resource_entries(config):
        if not _has_glob_metacharacters(configured_value):
            candidate = resolve_workspace_path(configured_value, workspace=workspace)
            assert_path_within_workspace(
                candidate,
                workspace=workspace,
                field=field,
                configured_value=configured_value,
            )
        resources.append(configured_value)

    try:
        collection = policy.collect(
            resources,
            missing_digest=MISSING_RESOURCE_FILE_DIGEST,
        )
    except CanonicalPathError as exc:
        raise ConfigError(str(exc), path="agent_context.resources") from exc
    diagnostics = SnapshotDiagnostics(
        included_files=len(collection.digests),
        excluded_files=collection.excluded_file_count,
        pruned_directories=collection.excluded_directory_count,
        policy_version=collection.policy_version,
    )
    return collection.digests, diagnostics


def _exclusion_policy_for_context_spec(
    config: dict[str, Any],
    *,
    workspace: Path,
) -> dict[str, Any]:
    """Normalized exclusion policy fragment for context-spec identity (§7)."""

    from top_down_planning.config.snapshot_policy import SnapshotPolicy

    policy = SnapshotPolicy.from_config(config, workspace=workspace)
    return {
        "excludes": {
            "defaults": policy.default_excludes_enabled,
            "patterns": list(policy.user_patterns),
        },
        "policy_version": policy.policy_version,
    }


def _all_skill_digest_entries(
    config: dict[str, Any],
    *,
    workspace: Path,
) -> dict[str, str]:
    from top_down_planning.config.snapshot_policy import (
        CanonicalPathCollisionError,
    )

    digests: dict[str, str] = {}
    paths_by_key: dict[str, Path] = {}
    for role in ALLOWED_AGENT_ROLES:
        for entry in _skills_for_role(config, role, workspace=workspace):  # type: ignore[arg-type]
            key = _skill_digest_key(entry, workspace=workspace)
            prior = paths_by_key.get(key)
            if prior is not None and prior.resolve() != entry.path.resolve():
                raise CanonicalPathCollisionError(key, prior, entry.path)
            if key not in digests:
                paths_by_key[key] = entry.path
                digests[key] = digest_text(entry.content)
    for activity in ALLOWED_AGENT_ACTIVITIES:
        act_role = role_for_activity(activity)  # type: ignore[arg-type]
        for entry in _skills_for_activity(
            config,
            act_role,
            activity,  # type: ignore[arg-type]
            workspace=workspace,
        ):
            key = _skill_digest_key(entry, workspace=workspace)
            prior = paths_by_key.get(key)
            if prior is not None and prior.resolve() != entry.path.resolve():
                raise CanonicalPathCollisionError(key, prior, entry.path)
            if key not in digests:
                paths_by_key[key] = entry.path
                digests[key] = digest_text(entry.content)
    return {key: digests[key] for key in sorted(digests)}


def _all_guidance_digest_entries(
    config: dict[str, Any],
    *,
    workspace: Path,
    allow_missing_files: bool = False,
) -> list[dict[str, str]]:
    """Snapshot binding for guidance: normalized text plus file path/digest when applicable."""

    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for role in ALLOWED_AGENT_ROLES:
        for entry in _guidance_entries_for_role(
            config,
            role,  # type: ignore[arg-type]
            workspace=workspace,
            allow_missing_files=allow_missing_files,
        ):
            if entry.path is not None:
                key = f"file:{entry.path.resolve()}"
            else:
                key = f"text:{entry.text}"
            if key in seen:
                continue
            seen.add(key)
            entries.append(_guidance_snapshot_entry(entry, workspace=workspace))
    for activity in ALLOWED_AGENT_ACTIVITIES:
        act_role = role_for_activity(activity)  # type: ignore[arg-type]
        for entry in _guidance_entries_for_activity(
            config,
            act_role,
            activity,  # type: ignore[arg-type]
            workspace=workspace,
            allow_missing_files=allow_missing_files,
        ):
            if entry.path is not None:
                key = f"file:{entry.path.resolve()}"
            else:
                key = f"text:{entry.text}"
            if key in seen:
                continue
            seen.add(key)
            entries.append(_guidance_snapshot_entry(entry, workspace=workspace))
    return sorted(
        entries,
        key=lambda item: (item.get("path") or "", item.get("text") or ""),
    )


def build_context_spec_payload(
    config: dict[str, Any],
    *,
    workspace: Path,
) -> dict[str, Any]:
    """Build deterministic context **spec** payload (declarations, not resource bytes)."""

    roles_payload: dict[str, Any] = {}
    for role in sorted(ALLOWED_AGENT_ROLES):
        roles_payload[role] = _role_context_spec_from_config(
            config,
            role,  # type: ignore[arg-type]
            workspace=workspace,
        )

    activities_payload: dict[str, Any] = {}
    for activity in sorted(ALLOWED_AGENT_ACTIVITIES):
        activities_payload[activity] = _activity_context_spec_from_config(
            config,
            activity,  # type: ignore[arg-type]
            workspace=workspace,
        )

    return {
        "workspace": str(workspace.resolve()),
        "default": _overlay_context_spec_from_section(_default_overlay_section(config)),
        "roles": roles_payload,
        "activities": activities_payload,
        "context_snapshot": _exclusion_policy_for_context_spec(
            config,
            workspace=workspace,
        ),
    }


def build_context_snapshot_payload(
    config: dict[str, Any],
    *,
    workspace: Path,
    allow_missing_guidance_files: bool = False,
) -> dict[str, Any]:
    """Build materialized context snapshot: resources, skills, and guidance digests.

    Resource and skill bindings are compact maps keyed by canonical workspace-relative
    POSIX paths (proposal §9). Resource materialization applies §6 exclusion semantics;
    skill and guidance surfaces are not filtered by snapshot excludes.
    """

    binding, _diagnostics = build_context_snapshot_payload_with_diagnostics(
        config,
        workspace=workspace,
        allow_missing_guidance_files=allow_missing_guidance_files,
    )
    return binding


def build_context_snapshot_payload_with_diagnostics(
    config: dict[str, Any],
    *,
    workspace: Path,
    allow_missing_guidance_files: bool = False,
) -> tuple[dict[str, Any], Any]:
    """Build snapshot binding plus §14 diagnostics from the same materialization pass."""

    from top_down_planning.config.snapshot_diagnostics import (
        SnapshotDiagnostics,
        binding_payload_size_bytes,
    )

    resource_digests, resource_diag = _materialize_resource_digests(
        config,
        workspace=workspace,
    )
    binding = {
        "resource_digests": resource_digests,
        "skill_digests": _all_skill_digest_entries(config, workspace=workspace),
        "guidance_digests": _all_guidance_digest_entries(
            config,
            workspace=workspace,
            allow_missing_files=allow_missing_guidance_files,
        ),
    }
    diagnostics = SnapshotDiagnostics(
        included_files=resource_diag.included_files,
        excluded_files=resource_diag.excluded_files,
        pruned_directories=resource_diag.pruned_directories,
        policy_version=resource_diag.policy_version,
        binding_size_bytes=binding_payload_size_bytes(binding),
    )
    return binding, diagnostics


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
    allow_missing_guidance_files: bool = False,
) -> str:
    payload = build_context_snapshot_payload(
        config,
        workspace=workspace,
        allow_missing_guidance_files=allow_missing_guidance_files,
    )
    return compute_context_snapshot_digest_from_payload(payload)


def compute_effective_context_digest(
    *,
    role: str,
    activity: str,
    model: str | None,
    guidance: tuple[str, ...],
    resources: tuple[Path, ...],
    skills: tuple[SkillEntry, ...],
    workspace: Path,
) -> str:
    from top_down_planning.config.snapshot_policy import canonicalize_workspace_path
    from top_down_planning.persistence.digests import digest_binding_payload

    resource_entries: list[dict[str, str]] = []
    for path in resources:
        relative = canonicalize_workspace_path(path, workspace=workspace)
        if path.is_file():
            resource_entries.append(
                {"path": relative, "digest": digest_file(path)}
            )
        else:
            resource_entries.append(
                {"path": relative, "digest": MISSING_RESOURCE_FILE_DIGEST}
            )
    skill_entries = sorted(
        {
            _skill_digest_key(entry, workspace=workspace): digest_text(entry.content)
            for entry in skills
        }.items()
    )
    payload = {
        "role": role,
        "activity": activity,
        "model": model,
        "guidance": list(guidance),
        "resources": resource_entries,
        "skills": [{"key": key, "digest": digest} for key, digest in skill_entries],
    }
    return digest_binding_payload(payload)


def resolve_effective_activity_context(
    config: dict[str, Any],
    role: AgentRole,
    activity: AgentActivity,
    *,
    workspace: Path,
    output_goal: str | None = None,
) -> EffectiveActivityContext:
    """Resolve authoritative run contracts and activity-aware agent context."""

    assert_valid_activity_role_pair(role, activity)
    default_section, role_section, activity_section = _overlay_sections(
        config,
        role,
        activity,
    )

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
    role_resources = _resolve_supporting_resources(
        list(role_section.get("resources") or []),
        workspace=workspace,
        forbidden=forbidden,
        field=f"agent_context.roles.{role}.resources",
    )
    activity_resources = _resolve_supporting_resources(
        list(activity_section.get("resources") or []),
        workspace=workspace,
        forbidden=forbidden,
        field=f"agent_context.activities.{activity}.resources",
    )
    resources = _merge_resolved_resource_paths_multi(
        default_resources,
        role_resources,
        activity_resources,
    )
    skills = _skills_for_activity(config, role, activity, workspace=workspace)
    guidance_entries = _guidance_entries_for_activity(
        config,
        role,
        activity,
        workspace=workspace,
    )
    model = resolve_provider_model_for_activity(config, role, activity)
    guidance = tuple(entry.text for entry in guidance_entries)
    context_digest = compute_effective_context_digest(
        role=role,
        activity=activity,
        model=model,
        guidance=guidance,
        resources=resources,
        skills=skills,
        workspace=workspace,
    )

    return EffectiveActivityContext(
        role=role,
        activity=activity,
        model=model,
        input_refs=input_refs,
        output_goal=goal_text,
        guidance=guidance,
        resources=resources,
        skills=skills,
        context_digest=context_digest,
    )


def build_agent_context_manifest_payload(
    context: EffectiveActivityContext,
) -> dict[str, Any]:
    """Build the manifest fragment attached to fresh agent sessions."""

    return {
        "agent_context": {
            "role": context.role,
            "activity": context.activity,
            "context_digest": context.context_digest,
            "guidance": list(context.guidance),
            "resources": [str(path) for path in context.resources],
            "skills": [
                {"path": str(entry.path), "content": entry.content}
                for entry in context.skills
            ],
        }
    }
