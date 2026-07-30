"""Configuration loading and CLI override resolution (proposal §14)."""

from core_tools.config import (
    ConfigError,
    PathResolutionContext,
    SkillEntry,
    assert_path_within_workspace,
    is_path_within_workspace,
    load_skills,
    resolve_expanded_path_list,
    resolve_path,
    resolve_workspace,
    resolve_workspace_path,
)

from top_down_planning.config.context import (
    AgentRole,
    EffectiveRoleContext,
    build_agent_context_manifest_payload,
    build_context_digest_payload,
    compute_context_digest_from_config,
    resolve_effective_role_context,
    resolve_provider_model,
)
from top_down_planning.config.defaults import (
    ALLOWED_AGENT_CONTEXT_ROLES,
    ALLOWED_OVERRIDE_PATHS,
    DEFAULT_CONFIG,
)
from top_down_planning.config.resolve import (
    compute_input_digest,
    compute_output_goal_digest,
    finalize_resolved_config,
    resolve_config,
    resolve_output_goal_text,
)

__all__ = [
    "ALLOWED_AGENT_CONTEXT_ROLES",
    "ALLOWED_OVERRIDE_PATHS",
    "DEFAULT_CONFIG",
    "AgentRole",
    "ConfigError",
    "EffectiveRoleContext",
    "PathResolutionContext",
    "SkillEntry",
    "assert_path_within_workspace",
    "build_agent_context_manifest_payload",
    "build_context_digest_payload",
    "compute_context_digest_from_config",
    "compute_input_digest",
    "compute_output_goal_digest",
    "finalize_resolved_config",
    "is_path_within_workspace",
    "load_skills",
    "resolve_config",
    "resolve_effective_role_context",
    "resolve_expanded_path_list",
    "resolve_output_goal_text",
    "resolve_path",
    "resolve_provider_model",
    "resolve_workspace",
    "resolve_workspace_path",
]
