"""Shared CLI helpers for user and agent commands."""

from __future__ import annotations

from argparse import Namespace
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from core_tools.cli import (
    ResolvedRunsDir,
    RunsDirSource,
    emit_error_message,
    emit_message,
    emit_payload,
    resolve_runs_dir as _resolve_runs_dir,
)

from top_down_planning.config import resolve_config
from top_down_planning.persistence import FileRunStore
from top_down_planning.persistence.capabilities import CAPABILITY_TOKEN_FILE_ENV_VAR

RUNS_DIR_ENV_VAR = "TDP_RUNS_DIR"
RUN_ID_ENV_VAR = "TDP_RUN_ID"
AGENT_REQUESTS_DIR_ENV_VAR = "TDP_AGENT_REQUESTS_DIR"

RunsDirSource = RunsDirSource

RUNS_DIR_HELP = (
    "Run store root directory (precedence: --runs-dir > $TDP_RUNS_DIR > "
    "runtime.runs_dir in --config > ./runs)."
)

AGENT_RUNS_DIR_HELP = (
    "Run store root directory (precedence: --runs-dir > $TDP_RUNS_DIR > ./runs). "
    "Orchestrator subprocesses receive TDP_RUNS_DIR automatically."
)


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

    return _resolve_runs_dir(
        explicit=explicit,
        config_value=config_value,
        cwd=cwd,
        environ=environ,
        env_var=RUNS_DIR_ENV_VAR,
        default_relative="runs",
    )


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


def provider_extra_env(
    resolved: ResolvedRunsDir,
    *,
    run_id: str | None = None,
    store: FileRunStore | None = None,
) -> dict[str, str]:
    """Environment variables exported to provider subprocesses."""

    env = {RUNS_DIR_ENV_VAR: str(resolved.path)}
    if run_id is not None:
        if store is None:
            raise ValueError("store is required when run_id is set")
        env[RUN_ID_ENV_VAR] = run_id
        env[AGENT_REQUESTS_DIR_ENV_VAR] = str(store.agent_requests_dir(run_id))
    return env


def store_diagnostics_payload(
    resolved: ResolvedRunsDir,
    *,
    run_id: str | None = None,
    store: FileRunStore | None = None,
) -> dict[str, str]:
    payload = {
        "runs_root": str(resolved.path),
        "runs_root_source": resolved.source,
    }
    if run_id is not None:
        if store is None:
            raise ValueError("store is required when run_id is set")
        run_path = store.run_dir(run_id)
        payload["run_path"] = str(run_path)
        payload["agent_requests_dir"] = str(store.agent_requests_dir(run_id))
    return payload


def run_startup_diagnostics_payload(
    *,
    cwd: Path,
    config_path: Path,
    workspace: Path,
    resolved_runs: ResolvedRunsDir,
    run_id: str | None = None,
    store: FileRunStore | None = None,
) -> dict[str, str]:
    """Path diagnostics printed once at ``tdp run`` startup."""

    payload = {
        "working_directory": str(cwd),
        "config_file": str(config_path),
        "workspace": str(workspace),
        **store_diagnostics_payload(resolved_runs, run_id=run_id, store=store),
    }
    return payload


def format_run_startup_diagnostics(payload: Mapping[str, str]) -> str:
    return (
        f"Working directory: {payload['working_directory']}\n"
        f"Config file: {payload['config_file']}\n"
        f"Workspace: {payload['workspace']}\n"
        f"Runs root: {payload['runs_root']}\n"
        f"Runs root source: {payload['runs_root_source']}"
    )


__all__ = [
    "AGENT_REQUESTS_DIR_ENV_VAR",
    "AGENT_RUNS_DIR_HELP",
    "CAPABILITY_TOKEN_FILE_ENV_VAR",
    "RUN_ID_ENV_VAR",
    "RUNS_DIR_ENV_VAR",
    "RUNS_DIR_HELP",
    "ResolvedRunsDir",
    "RunsDirSource",
    "RunsStoreNotFoundError",
    "emit_error_message",
    "emit_message",
    "emit_payload",
    "format_run_startup_diagnostics",
    "load_config_for_runs_dir",
    "open_run_store",
    "provider_extra_env",
    "resolve_runs_dir",
    "resolve_runs_dir_from_args",
    "run_startup_diagnostics_payload",
    "runs_dir_config_value",
    "store_diagnostics_payload",
]
