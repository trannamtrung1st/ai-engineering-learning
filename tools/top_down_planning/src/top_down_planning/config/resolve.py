"""YAML load, defaults merge, and CLI --set override resolution (proposal §14)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from top_down_planning.config.defaults import ALLOWED_OVERRIDE_PATHS, DEFAULT_CONFIG
from top_down_planning.config.errors import ConfigError
from top_down_planning.persistence.digests import digest_file, digest_text
from top_down_planning.persistence.yaml_util import load_yaml


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge overlay into base; overlay values win."""

    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def parse_override_value(raw: str) -> Any:
    """Parse a CLI --set value as YAML."""

    stripped = raw.strip()
    if not stripped:
        raise ConfigError("override value is empty")

    # Structured YAML fragments and block scalars.
    if stripped == "true":
        return True
    if stripped == "false":
        return False
    if stripped in {"null", "~"}:
        return None
    if stripped == "{}":
        return {}
    if stripped == "[]":
        return []
    if stripped.startswith("[") and stripped.endswith("]"):
        inner = stripped[1:-1].strip()
        if not inner:
            return []
        items = [part.strip() for part in inner.split(",")]
        yaml_list = "\n".join(f"- {item}" for item in items)
        return load_yaml(yaml_list)
    if stripped.startswith("{") and stripped.endswith("}"):
        return load_yaml(stripped)
    if stripped[0] in {'"', "'"} or "\n" in stripped or ":" in stripped:
        return load_yaml(stripped)

    wrapped = load_yaml(f"value: {stripped}")
    if not isinstance(wrapped, dict) or "value" not in wrapped:
        raise ConfigError(f"failed to parse override value: {raw!r}")
    return wrapped["value"]


def set_nested_path(config: dict[str, Any], path: str, value: Any) -> None:
    """Set a dotted path on config; path must be in ALLOWED_OVERRIDE_PATHS."""

    if path not in ALLOWED_OVERRIDE_PATHS:
        raise ConfigError(f"unknown config path: {path}", path=path)

    parts = path.split(".")
    current: dict[str, Any] = config
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = value


def apply_cli_overrides(
    config: dict[str, Any],
    overrides: list[str],
) -> dict[str, Any]:
    """Apply ordered CLI --set PATH=VALUE overrides."""

    result = copy.deepcopy(config)
    for override in overrides:
        if "=" not in override:
            raise ConfigError(
                f"invalid --set override (expected PATH=VALUE): {override!r}"
            )
        path, raw_value = override.split("=", 1)
        path = path.strip()
        if not path:
            raise ConfigError(f"invalid --set override (empty path): {override!r}")
        value = parse_override_value(raw_value)
        set_nested_path(result, path, value)
    return result


def load_yaml_config(path: Path) -> dict[str, Any]:
    """Load a YAML configuration file."""

    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")

    try:
        raw = load_yaml(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"failed to load config file {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"config file {path} must contain a mapping at the root")
    return raw


def resolve_config(
    config_path: Path | None,
    overrides: list[str] | None = None,
) -> dict[str, Any]:
    """
    Resolve configuration with precedence:
    built-in defaults < YAML configuration < CLI --set overrides.
    """

    resolved = copy.deepcopy(DEFAULT_CONFIG)
    if config_path is not None:
        resolved = deep_merge(resolved, load_yaml_config(config_path))
    if overrides:
        resolved = apply_cli_overrides(resolved, overrides)
    return resolved


def compute_input_digest(config: dict[str, Any], *, base_dir: Path) -> str:
    """Digest input references relative to the config file directory."""

    refs = list((config.get("run") or {}).get("input_refs") or [])
    entries: list[dict[str, str]] = []
    for ref in refs:
        ref_text = str(ref)
        candidate = (base_dir / ref_text).resolve()
        if candidate.is_file():
            entries.append({"ref": ref_text, "digest": digest_file(candidate)})
        else:
            entries.append({"ref": ref_text, "digest": digest_text(ref_text)})

    canonical = json.dumps(
        entries,
        sort_keys=True,
        separators=(",", ":"),
    )
    return digest_text(canonical)


def compute_output_goal_digest(config: dict[str, Any]) -> str:
    goal = str((config.get("run") or {}).get("output_goal") or "")
    return digest_text(goal)
