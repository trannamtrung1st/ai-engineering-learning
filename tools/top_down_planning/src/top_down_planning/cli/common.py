"""Shared CLI helpers for user and agent commands."""

from __future__ import annotations

import json
import os
import sys
from argparse import Namespace
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from top_down_planning.config import ConfigError, resolve_config
from top_down_planning.persistence import FileRunStore

RunsDirSource = Literal["cli", "environment", "config", "default"]

RUNS_DIR_HELP = (
    "Run store root directory (precedence: --runs-dir > $TDP_RUNS_DIR > "
    "runtime.runs_dir in --config > ./runs)."
)

AGENT_RUNS_DIR_HELP = (
    "Run store root directory (precedence: --runs-dir > $TDP_RUNS_DIR > ./runs). "
    "Orchestrator subprocesses receive TDP_RUNS_DIR automatically."
)


@dataclass(frozen=True)
class ResolvedRunsDir:
    path: Path
    source: RunsDirSource


def runs_dir_config_value(config: dict[str, Any]) -> str | None:
    """Return configured ``runtime.runs_dir`` when set and non-empty."""

    runtime = config.get("runtime")
    if not isinstance(runtime, dict):
        return None
    value = runtime.get("runs_dir")
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped if stripped else None


def resolve_runs_dir(
    *,
    explicit: str | Path | None = None,
    config_value: str | Path | None = None,
    cwd: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> ResolvedRunsDir:
    """
    Resolve the run-store root with precedence:
    explicit CLI --runs-dir > TDP_RUNS_DIR > runtime.runs_dir > <cwd>/runs.
    """

    base = (cwd or Path.cwd()).resolve()
    env = environ if environ is not None else os.environ

    if explicit is not None and str(explicit).strip():
        return ResolvedRunsDir(Path(explicit).resolve(), "cli")

    env_value = str(env.get("TDP_RUNS_DIR", "")).strip()
    if env_value:
        return ResolvedRunsDir(Path(env_value).resolve(), "environment")

    if config_value is not None and str(config_value).strip():
        configured = Path(str(config_value).strip())
        if configured.is_absolute():
            return ResolvedRunsDir(configured.resolve(), "config")
        return ResolvedRunsDir((base / configured).resolve(), "config")

    return ResolvedRunsDir((base / "runs").resolve(), "default")


def load_config_for_runs_dir(args: Namespace) -> dict[str, Any] | None:
    config_path = getattr(args, "config", None)
    if not config_path:
        return None
    overrides = getattr(args, "set", None) or []
    return resolve_config(
        Path(config_path).resolve(),
        overrides if overrides else None,
    )


def resolve_runs_dir_from_args(
    args: Namespace,
    *,
    resolved_config: dict[str, Any] | None = None,
) -> ResolvedRunsDir:
    config = resolved_config
    if config is None:
        config = load_config_for_runs_dir(args)
    return resolve_runs_dir(
        explicit=getattr(args, "runs_dir", None),
        config_value=runs_dir_config_value(config) if config else None,
    )


class RunsStoreNotFoundError(Exception):
    def __init__(self, resolved: ResolvedRunsDir) -> None:
        self.resolved = resolved
        super().__init__(
            f"runs store not found: {resolved.path} "
            f"(resolved from: {resolved.source})"
        )


def open_run_store(
    args: Namespace,
    *,
    resolved_config: dict[str, Any] | None = None,
    create: bool = False,
) -> tuple[FileRunStore, ResolvedRunsDir]:
    resolved = resolve_runs_dir_from_args(args, resolved_config=resolved_config)
    store = FileRunStore(resolved.path)
    if create:
        store.root.mkdir(parents=True, exist_ok=True)
        return store, resolved
    if not store.root.is_dir():
        raise RunsStoreNotFoundError(resolved)
    return store, resolved


def provider_extra_env(resolved: ResolvedRunsDir) -> dict[str, str]:
    """Environment variables exported to provider subprocesses."""

    return {"TDP_RUNS_DIR": str(resolved.path)}


def store_diagnostics_payload(
    resolved: ResolvedRunsDir,
    *,
    run_id: str | None = None,
) -> dict[str, str]:
    payload = {
        "runs_root": str(resolved.path),
        "runs_root_source": resolved.source,
    }
    if run_id is not None:
        payload["run_path"] = str(resolved.path / run_id)
    return payload


def emit_payload(payload: dict[str, Any], *, exit_code: int = 0) -> None:
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    raise SystemExit(exit_code)


def emit_message(message: str, *, exit_code: int = 0, stream_json: bool = False) -> None:
    if stream_json:
        emit_payload({"ok": exit_code == 0, "message": message}, exit_code=exit_code)
    sys.stdout.write(message)
    if not message.endswith("\n"):
        sys.stdout.write("\n")
    raise SystemExit(exit_code)


def emit_error_message(
    message: str,
    *,
    exit_code: int = 1,
    stream_json: bool = False,
    code: str = "error",
) -> None:
    if stream_json:
        emit_payload(
            {
                "ok": False,
                "error": {
                    "code": code,
                    "message": message,
                },
            },
            exit_code=exit_code,
        )
    print(message, file=sys.stderr)
    raise SystemExit(exit_code)
