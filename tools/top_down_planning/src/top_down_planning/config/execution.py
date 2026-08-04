"""Execution mode configuration helpers."""

from __future__ import annotations

from typing import Any

from core_tools.config.errors import ConfigError

EXECUTION_MODE_SINGLE = "single"
EXECUTION_MODE_SUB_TDPS = "sub_tdps"
ALLOWED_EXECUTION_MODES = frozenset({EXECUTION_MODE_SINGLE, EXECUTION_MODE_SUB_TDPS})


def execution_section(config: dict[str, Any]) -> dict[str, Any]:
    section = config.get("execution")
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise ConfigError("execution must be a mapping", path="execution")
    return section


def execution_mode_from_config(config: dict[str, Any]) -> str:
    section = execution_section(config)
    raw = section.get("mode")
    if raw is None or str(raw).strip() == "":
        return EXECUTION_MODE_SINGLE
    mode = str(raw).strip()
    if mode not in ALLOWED_EXECUTION_MODES:
        raise ConfigError(
            f"execution.mode must be one of: {', '.join(sorted(ALLOWED_EXECUTION_MODES))}",
            path="execution.mode",
        )
    return mode


def execution_state_file_from_config(config: dict[str, Any]) -> str | None:
    section = execution_section(config)
    raw = section.get("state_file")
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def is_sub_tdps_mode(config: dict[str, Any]) -> bool:
    return execution_mode_from_config(config) == EXECUTION_MODE_SUB_TDPS


def validate_execution_config(config: dict[str, Any]) -> None:
    section = execution_section(config)
    unknown = sorted(set(section) - {"mode", "state_file"})
    if unknown:
        raise ConfigError(
            f"unknown execution field: {unknown[0]!r}",
            path=f"execution.{unknown[0]}",
        )
    execution_mode_from_config(config)
    state_file = execution_state_file_from_config(config)
    if state_file is not None and not state_file.strip():
        raise ConfigError(
            "execution.state_file must be a non-empty path when set",
            path="execution.state_file",
        )


def assert_child_execution_allowed(config: dict[str, Any]) -> None:
    """Reject sub_tdps mode on child runs (only parent orchestrator may use it)."""

    if is_sub_tdps_mode(config):
        raise ConfigError(
            "execution.mode sub_tdps is only allowed on parent orchestration runs",
            path="execution.mode",
        )


__all__ = [
    "ALLOWED_EXECUTION_MODES",
    "EXECUTION_MODE_SINGLE",
    "EXECUTION_MODE_SUB_TDPS",
    "assert_child_execution_allowed",
    "execution_mode_from_config",
    "execution_section",
    "execution_state_file_from_config",
    "is_sub_tdps_mode",
    "validate_execution_config",
]
