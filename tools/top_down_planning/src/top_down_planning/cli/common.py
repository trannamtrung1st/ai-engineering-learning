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
from top_down_planning.persistence.path_ids import validate_run_id

RUNS_DIR_ENV_VAR = "TDP_RUNS_DIR"
RUN_ID_ENV_VAR = "TDP_RUN_ID"
AGENT_REQUESTS_DIR_ENV_VAR = "TDP_AGENT_REQUESTS_DIR"

RunsDirSource = RunsDirSource

RUNS_DIR_HELP = (
    "Run store root directory (precedence: --runs-dir > $TDP_RUNS_DIR > "
    "runtime.runs_dir in --config > ./runs)."
)

RUNS_DIR_REQUIRED_HELP = (
    "Run store root directory (required; precedence: --runs-dir > $TDP_RUNS_DIR > "
    "runtime.runs_dir in --config). This command does not fall back to ./runs."
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


def emit_command_result(
    payload: dict[str, Any],
    *,
    human_message: str,
    stream_json: bool,
    exit_code: int = 0,
) -> None:
    """Emit exactly one stdout payload: JSON when requested, otherwise human text."""

    if stream_json:
        emit_payload(payload, exit_code=exit_code)
    emit_message(human_message, exit_code=exit_code)


def open_run_store_for_cli(
    args: Namespace,
    *,
    resolved_config: dict[str, Any] | None = None,
    create: bool = False,
) -> tuple[FileRunStore, ResolvedRunsDir]:
    """Open a run store and convert config/store locator failures into CLI errors."""

    from top_down_planning.config import ConfigError

    try:
        return open_run_store(args, resolved_config=resolved_config, create=create)
    except ConfigError as exc:
        emit_error_message(
            str(exc),
            exit_code=2,
            stream_json=bool(getattr(args, "stream_json", False)),
            code="config_error",
        )
    except RunsStoreNotFoundError as exc:
        emit_error_message(
            str(exc),
            exit_code=1,
            stream_json=bool(getattr(args, "stream_json", False)),
            code="runs_store_not_found",
        )


def require_cli_run_id(run_id: str | None, *, stream_json: bool) -> str:
    """Validate a user-supplied run id before any store access."""

    from core_tools.persistence import PersistenceError

    text = str(run_id or "")
    try:
        return validate_run_id(text)
    except PersistenceError as exc:
        emit_error_message(
            str(exc),
            exit_code=2,
            stream_json=stream_json,
            code="invalid_run_id",
        )
        raise


def emit_run_access_error(exc: BaseException, *, stream_json: bool) -> None:
    """Normalize missing runs vs persisted-state corruption for user commands."""

    from core_tools.persistence import PersistenceError, RunNotFoundError

    if isinstance(exc, RunNotFoundError):
        emit_error_message(
            str(exc),
            exit_code=1,
            stream_json=stream_json,
            code="run_not_found",
        )
    if isinstance(exc, PersistenceError):
        emit_error_message(
            str(exc),
            exit_code=1,
            stream_json=stream_json,
            code="corrupt_run",
        )
    raise exc


def emit_operational_error(exc: BaseException, *, stream_json: bool) -> None:
    """Normalize filesystem I/O failures for mutating user commands."""

    from top_down_planning.orchestrator.failure import sanitize_operational_error

    emit_error_message(
        sanitize_operational_error(exc),
        exit_code=1,
        stream_json=stream_json,
        code="operational_error",
    )


__all__ = [
    "AGENT_REQUESTS_DIR_ENV_VAR",
    "AGENT_RUNS_DIR_HELP",
    "CAPABILITY_TOKEN_FILE_ENV_VAR",
    "RUN_ID_ENV_VAR",
    "RUNS_DIR_ENV_VAR",
    "RUNS_DIR_HELP",
    "RUNS_DIR_REQUIRED_HELP",
    "ResolvedRunsDir",
    "RunsDirSource",
    "RunsStoreNotFoundError",
    "emit_command_result",
    "emit_error_message",
    "emit_message",
    "emit_payload",
    "emit_run_access_error",
    "emit_operational_error",
    "require_cli_run_id",
    "format_run_startup_diagnostics",
    "load_config_for_runs_dir",
    "open_run_store",
    "open_run_store_for_cli",
    "provider_extra_env",
    "resolve_runs_dir",
    "resolve_runs_dir_from_args",
    "run_startup_diagnostics_payload",
    "runs_dir_config_value",
    "store_diagnostics_payload",
]
