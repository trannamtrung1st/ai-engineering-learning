"""YAML load, deep merge, and CLI --set override helpers."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from core_tools.config.errors import ConfigError
from core_tools.persistence.digests import digest_file, digest_text
from core_tools.persistence.yaml_util import load_yaml


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
        # Prefer JSON for structured list overrides (guidance entries, etc.).
        if "{" in stripped:
            import json

            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                pass
        inner = stripped[1:-1].strip()
        if not inner:
            return []
        items = [part.strip() for part in inner.split(",")]
        yaml_list = "\n".join(f"- {item}" for item in items)
        return load_yaml(yaml_list)
    if stripped.startswith("{") and stripped.endswith("}"):
        if '"' in stripped:
            import json

            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                pass
        return load_yaml(stripped)
    if stripped[0] in {'"', "'"} or "\n" in stripped or ":" in stripped:
        return load_yaml(stripped)

    wrapped = load_yaml(f"value: {stripped}")
    if not isinstance(wrapped, dict) or "value" not in wrapped:
        raise ConfigError(f"failed to parse override value: {raw!r}")
    return wrapped["value"]


def set_nested_path(
    config: dict[str, Any],
    path: str,
    value: Any,
    *,
    allowed_paths: frozenset[str] | None = None,
) -> None:
    """Set a dotted path on config, optionally restricted to allowed_paths."""

    if allowed_paths is not None and path not in allowed_paths:
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
    *,
    allowed_paths: frozenset[str] | None = None,
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
        set_nested_path(result, path, value, allowed_paths=allowed_paths)
    return result


def load_yaml_config(path: Path) -> dict[str, Any]:
    """Load a YAML configuration file."""

    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError(f"failed to load config file {path}: {exc}") from exc

    try:
        raw = load_yaml(text)
    except ValueError as exc:
        raise ConfigError(f"failed to load config file {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"config file {path} must contain a mapping at the root")
    return raw


def compute_input_refs_digest(
    input_refs: list[Any],
    *,
    base_dir: Path,
) -> str:
    """Digest input references relative to a base directory."""

    import json

    entries: list[dict[str, str]] = []
    for ref in input_refs:
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
