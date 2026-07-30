"""Generic configuration helpers."""

from core_tools.config.errors import ConfigError
from core_tools.config.merge import (
    apply_cli_overrides,
    compute_input_refs_digest,
    deep_merge,
    load_yaml_config,
    parse_override_value,
    set_nested_path,
)
from core_tools.config.paths import (
    PathResolutionContext,
    assert_path_within_workspace,
    is_path_within_workspace,
    resolve_path,
    resolve_workspace,
    resolve_workspace_path,
)
from core_tools.config.resources import (
    SkillEntry,
    load_skills,
    resolve_expanded_path_list,
    resolve_provider_model,
)
from core_tools.config.validation import collect_leaf_paths, reject_unknown_config_paths

__all__ = [
    "ConfigError",
    "PathResolutionContext",
    "SkillEntry",
    "apply_cli_overrides",
    "assert_path_within_workspace",
    "collect_leaf_paths",
    "compute_input_refs_digest",
    "deep_merge",
    "is_path_within_workspace",
    "load_skills",
    "load_yaml_config",
    "parse_override_value",
    "reject_unknown_config_paths",
    "resolve_expanded_path_list",
    "resolve_path",
    "resolve_provider_model",
    "resolve_workspace",
    "resolve_workspace_path",
    "set_nested_path",
]
