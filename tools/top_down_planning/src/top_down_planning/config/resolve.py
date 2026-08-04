"""TDP configuration resolution (proposal §14)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from core_tools.config import (
    apply_cli_overrides,
    compute_input_refs_digest,
    deep_merge,
    load_yaml_config,
    reject_unknown_config_paths,
    resolve_workspace,
    resolve_workspace_path,
)
from core_tools.config.errors import ConfigError

from top_down_planning.config.activities import (
    ALLOWED_AGENT_ACTIVITIES,
    ALLOWED_AGENT_CONTEXT_TOP_LEVEL_KEYS,
    ALLOWED_AGENT_ROLES,
)
from top_down_planning.config.defaults import (
    ALLOWED_OVERRIDE_PATHS,
    DEFAULT_CONFIG,
)
from top_down_planning.config.execution import validate_execution_config

__all__ = [
    "compute_input_digest",
    "compute_output_goal_digest",
    "finalize_resolved_config",
    "resolve_config",
    "resolve_output_goal_text",
]

_AGENT_CONTEXT_OVERLAY_FIELDS = frozenset({"model", "guidance", "resources", "skills"})


def _validate_context_overlay_section(
    section: dict[str, Any],
    *,
    path_prefix: str,
) -> None:
    unknown = sorted(set(section) - _AGENT_CONTEXT_OVERLAY_FIELDS)
    if unknown:
        raise ConfigError(
            f"unsupported {path_prefix} field: {unknown[0]!r}",
            path=f"{path_prefix}.{unknown[0]}",
        )


def _validate_agent_context_roles(config: dict[str, Any]) -> None:
    agent_context = config.get("agent_context")
    if agent_context is None:
        return
    if not isinstance(agent_context, dict):
        raise ConfigError(
            "agent_context must be a mapping",
            path="agent_context",
        )
    for key_name in agent_context:
        if key_name not in ALLOWED_AGENT_CONTEXT_TOP_LEVEL_KEYS:
            raise ConfigError(
                f"unknown agent_context key: {key_name!r}",
                path=f"agent_context.{key_name}",
            )
    bundled_skills = agent_context.get("bundled_skills")
    if bundled_skills is not None and not isinstance(bundled_skills, bool):
        raise ConfigError(
            "agent_context.bundled_skills must be a boolean",
            path="agent_context.bundled_skills",
        )

    default_section = agent_context.get("default")
    if default_section is not None:
        if not isinstance(default_section, dict):
            raise ConfigError(
                "agent_context.default must be a mapping",
                path="agent_context.default",
            )
        _validate_context_overlay_section(
            default_section,
            path_prefix="agent_context.default",
        )

    roles_section = agent_context.get("roles")
    if roles_section is not None:
        if not isinstance(roles_section, dict):
            raise ConfigError(
                "agent_context.roles must be a mapping",
                path="agent_context.roles",
            )
        for role_name, role_section in roles_section.items():
            if role_name not in ALLOWED_AGENT_ROLES:
                raise ConfigError(
                    f"unknown agent_context role: {role_name!r}",
                    path=f"agent_context.roles.{role_name}",
                )
            if not isinstance(role_section, dict):
                raise ConfigError(
                    f"agent_context.roles.{role_name} must be a mapping",
                    path=f"agent_context.roles.{role_name}",
                )
            _validate_context_overlay_section(
                role_section,
                path_prefix=f"agent_context.roles.{role_name}",
            )

    activities_section = agent_context.get("activities")
    if activities_section is not None:
        if not isinstance(activities_section, dict):
            raise ConfigError(
                "agent_context.activities must be a mapping",
                path="agent_context.activities",
            )
        for activity_name, activity_section in activities_section.items():
            if activity_name not in ALLOWED_AGENT_ACTIVITIES:
                raise ConfigError(
                    f"unknown agent_context activity: {activity_name!r}",
                    path=f"agent_context.activities.{activity_name}",
                )
            if not isinstance(activity_section, dict):
                raise ConfigError(
                    f"agent_context.activities.{activity_name} must be a mapping",
                    path=f"agent_context.activities.{activity_name}",
                )
            if "role" in activity_section:
                raise ConfigError(
                    "agent_context activities must not configure role",
                    path=f"agent_context.activities.{activity_name}.role",
                )
            _validate_context_overlay_section(
                activity_section,
                path_prefix=f"agent_context.activities.{activity_name}",
            )


def _validate_context_snapshot(config: dict[str, Any]) -> None:
    section = config.get("context_snapshot")
    if section is None:
        return
    if not isinstance(section, dict):
        raise ConfigError(
            "context_snapshot must be a mapping",
            path="context_snapshot",
        )
    unknown = sorted(set(section) - {"excludes"})
    if unknown:
        raise ConfigError(
            f"unknown context_snapshot field: {unknown[0]!r}",
            path=f"context_snapshot.{unknown[0]}",
        )
    excludes = section.get("excludes")
    if excludes is None:
        return
    if not isinstance(excludes, dict):
        raise ConfigError(
            "context_snapshot.excludes must be a mapping",
            path="context_snapshot.excludes",
        )
    unknown_excludes = sorted(set(excludes) - {"defaults", "patterns"})
    if unknown_excludes:
        raise ConfigError(
            f"unknown context_snapshot.excludes field: {unknown_excludes[0]!r}",
            path=f"context_snapshot.excludes.{unknown_excludes[0]}",
        )
    if "defaults" in excludes and not isinstance(excludes["defaults"], bool):
        raise ConfigError(
            "context_snapshot.excludes.defaults must be a boolean",
            path="context_snapshot.excludes.defaults",
        )
    if "patterns" in excludes:
        patterns = excludes["patterns"]
        if not isinstance(patterns, list):
            raise ConfigError(
                "context_snapshot.excludes.patterns must be a list",
                path="context_snapshot.excludes.patterns",
            )
        for index, pattern in enumerate(patterns):
            if not isinstance(pattern, str) or not pattern.strip():
                raise ConfigError(
                    "context_snapshot.excludes.patterns entries must be non-empty strings",
                    path=f"context_snapshot.excludes.patterns[{index}]",
                )
        # Compile once so invalid gitwildmatch patterns fail at config resolve.
        from top_down_planning.config.exclude_matching import (
            compile_exclude_matcher,
            effective_exclude_patterns,
        )

        defaults = excludes.get("defaults", True)
        if not isinstance(defaults, bool):
            defaults = True
        compile_exclude_matcher(
            effective_exclude_patterns(
                defaults_enabled=defaults,
                user_patterns=[str(item) for item in patterns],
            )
        )


def _validate_revise_at_value(value: Any, *, path: str) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(
            f"{path} must be null or one of: suggestion, minor, major, blocker",
            path=path,
        )
    from top_down_planning.domain.review_policy import SEVERITY_ORDER

    if value.strip() not in SEVERITY_ORDER:
        raise ConfigError(
            f"{path} must be null or one of: " + ", ".join(SEVERITY_ORDER),
            path=path,
        )


def _validate_revise_at_config(config: dict[str, Any]) -> None:
    review = config.get("review")
    if review is None:
        return
    if not isinstance(review, dict):
        raise ConfigError("review must be a mapping", path="review")
    _validate_revise_at_value(review.get("revise_at"), path="review.revise_at")
    for review_type in (
        "focused_plan",
        "focused_output",
        "whole_plan",
        "whole_output",
    ):
        section = review.get(review_type)
        if section is None:
            continue
        if not isinstance(section, dict):
            raise ConfigError(
                f"review.{review_type} must be a mapping",
                path=f"review.{review_type}",
            )
        _validate_revise_at_value(
            section.get("revise_at"),
            path=f"review.{review_type}.revise_at",
        )


def finalize_resolved_config(
    config: dict[str, Any],
    *,
    cwd: Path,
) -> dict[str, Any]:
    """Normalize workspace fields and validate agent context roles."""

    finalized = copy.deepcopy(config)
    _validate_agent_context_roles(finalized)
    _validate_context_snapshot(finalized)
    _validate_revise_at_config(finalized)
    validate_execution_config(finalized)

    workspace = resolve_workspace(finalized, cwd=cwd)

    project = finalized.setdefault("project", {})
    if not isinstance(project, dict):
        raise ConfigError("project must be a mapping", path="project")
    project["workspace"] = str(workspace)

    return finalized


def resolve_config(
    config_path: Path | None,
    overrides: list[str] | None = None,
    *,
    cwd: Path | None = None,
) -> dict[str, Any]:
    """
    Resolve configuration with precedence:
    built-in defaults < YAML configuration < CLI --set overrides.
    """

    resolved = copy.deepcopy(DEFAULT_CONFIG)
    if config_path is not None:
        yaml_config = load_yaml_config(config_path)
        _validate_agent_context_roles(yaml_config)
        _validate_context_snapshot(yaml_config)
        _validate_revise_at_config(yaml_config)
        reject_unknown_config_paths(yaml_config, allowed_paths=ALLOWED_OVERRIDE_PATHS)
        resolved = deep_merge(resolved, yaml_config)
    if overrides:
        resolved = apply_cli_overrides(
            resolved,
            overrides,
            allowed_paths=ALLOWED_OVERRIDE_PATHS,
        )
    _validate_agent_context_roles(resolved)
    _validate_context_snapshot(resolved)
    _validate_revise_at_config(resolved)
    reject_unknown_config_paths(resolved, allowed_paths=ALLOWED_OVERRIDE_PATHS)
    return finalize_resolved_config(resolved, cwd=cwd or Path.cwd())


def compute_input_digest(config: dict[str, Any], *, base_dir: Path) -> str:
    """Digest input references relative to the resolved workspace directory."""

    refs = list((config.get("run") or {}).get("input_refs") or [])
    return compute_input_refs_digest(refs, base_dir=base_dir)


def resolve_output_goal_text(config: dict[str, Any], *, base_dir: Path) -> str:
    """Load inline or file-backed output goal text (mutually exclusive)."""

    run_section = config.get("run")
    if not isinstance(run_section, dict):
        raise ConfigError(
            "resolved config requires run.output_goal or run.output_goal_file",
            path="run.output_goal",
        )

    inline = str(run_section.get("output_goal") or "").strip()
    file_ref = str(run_section.get("output_goal_file") or "").strip()

    if inline and file_ref:
        raise ConfigError(
            "use either run.output_goal or run.output_goal_file, not both",
            path="run.output_goal",
        )
    if not inline and not file_ref:
        raise ConfigError(
            "resolved config requires run.output_goal or run.output_goal_file",
            path="run.output_goal",
        )

    if file_ref:
        goal_path = resolve_workspace_path(file_ref, workspace=base_dir)
        if not goal_path.is_file():
            raise ConfigError(
                f"output goal file not found: {goal_path}",
                path="run.output_goal_file",
            )
        try:
            text = goal_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(
                f"failed to read output goal file: {goal_path}",
                path="run.output_goal_file",
            ) from exc
        if not text.strip():
            raise ConfigError(
                f"output goal file is empty: {goal_path}",
                path="run.output_goal_file",
            )
        return text

    return inline


def compute_output_goal_digest(config: dict[str, Any], *, base_dir: Path) -> str:
    from core_tools.persistence.digests import digest_text

    return digest_text(resolve_output_goal_text(config, base_dir=base_dir))
