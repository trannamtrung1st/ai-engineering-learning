"""Execution mode configuration helpers."""

from __future__ import annotations

from typing import Any

from core_tools.config.errors import ConfigError

EXECUTION_MODE_SINGLE = "single"
ALLOWED_EXECUTION_MODES = frozenset({EXECUTION_MODE_SINGLE})


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
            f"execution.mode must be one of: {', '.join(sorted(ALLOWED_EXECUTION_MODES))}; "
            "use tdp prepare and tdp execute for Sub-TDP work",
            path="execution.mode",
        )
    return mode


def validate_execution_config(config: dict[str, Any]) -> None:
    section = execution_section(config)
    unknown = sorted(set(section) - {"mode"})
    if unknown:
        raise ConfigError(
            f"unknown execution field: {unknown[0]!r}",
            path=f"execution.{unknown[0]}",
        )
    execution_mode_from_config(config)


__all__ = [
    "ALLOWED_EXECUTION_MODES",
    "EXECUTION_MODE_SINGLE",
    "execution_mode_from_config",
    "execution_section",
    "validate_execution_config",
]
