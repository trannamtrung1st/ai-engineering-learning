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

from top_down_planning.config.defaults import (
    ALLOWED_AGENT_CONTEXT_ROLES,
    ALLOWED_OVERRIDE_PATHS,
    DEFAULT_CONFIG,
)

__all__ = [
    "compute_input_digest",
    "compute_output_goal_digest",
    "finalize_resolved_config",
    "resolve_config",
    "resolve_output_goal_text",
]


def _validate_agent_context_roles(config: dict[str, Any]) -> None:
    agent_context = config.get("agent_context")
    if agent_context is None:
        return
    if not isinstance(agent_context, dict):
        raise ConfigError(
            "agent_context must be a mapping",
            path="agent_context",
        )
    for role_name in agent_context:
        if role_name not in ALLOWED_AGENT_CONTEXT_ROLES:
            raise ConfigError(
                f"unknown agent_context role: {role_name!r}",
                path=f"agent_context.{role_name}",
            )


def finalize_resolved_config(
    config: dict[str, Any],
    *,
    cwd: Path,
) -> dict[str, Any]:
    """Normalize workspace fields and validate agent context roles."""

    finalized = copy.deepcopy(config)
    _validate_agent_context_roles(finalized)

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
        reject_unknown_config_paths(yaml_config, allowed_paths=ALLOWED_OVERRIDE_PATHS)
        resolved = deep_merge(resolved, yaml_config)
    if overrides:
        resolved = apply_cli_overrides(
            resolved,
            overrides,
            allowed_paths=ALLOWED_OVERRIDE_PATHS,
        )
    _validate_agent_context_roles(resolved)
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
