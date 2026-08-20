"""Shared CLI helpers for user and agent commands."""

from __future__ import annotations

from argparse import Namespace
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
import sys
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
from top_down_planning.persistence import FileRunStore, PersistenceError, RunNotFoundError
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
    except OSError as exc:
        emit_operational_error(exc, stream_json=bool(getattr(args, "stream_json", False)))
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


def recovery_fields(
    *,
    code: str,
    run_id: str | None = None,
    planning_run_id: str | None = None,
    phase: str | None = None,
) -> dict[str, Any] | None:
    """Machine-readable recovery hint derived from error code and durable identity."""

    identity = str(run_id or planning_run_id or "").strip()
    if not identity:
        return None
    if code in {
        "run_revision_conflict",
        "store_authorization_conflict",
        "run_owned_by_live_process",
    }:
        return {"command": "status", "run_id": identity}
    if code == "corrupt_run":
        return {"command": "doctor", "run_id": identity}
    if code == "prepare_incomplete":
        return {"command": "resume", "run_id": identity}
    if code in {"package_build_failed", "operational_error"} and str(phase or "") == "plan_validated":
        return {"command": "prepare", "planning_run_id": identity}
    if code == "package_build_failed":
        return {"command": "resume", "run_id": identity}
    if code.startswith("sub_tdp_") or code.startswith("package_"):
        return {"command": "inspect", "run_id": identity}
    if code in {"operational_error", "user_cancelled"}:
        return {"command": "status", "run_id": identity}
    if code == "run_not_found":
        return None
    return {"command": "resume", "run_id": identity}


def _with_recovery(extra: dict[str, Any] | None, *, code: str) -> dict[str, Any] | None:
    merged = dict(extra or {})
    if "recovery" not in merged:
        recovery = recovery_fields(
            code=code,
            run_id=str(merged.get("run_id") or "") or None,
            planning_run_id=str(merged.get("planning_run_id") or "") or None,
            phase=str(merged.get("phase") or "") or None,
        )
        if recovery:
            merged["recovery"] = recovery
    return merged or None


def emit_run_access_error(
    exc: BaseException,
    *,
    stream_json: bool,
    extra: dict[str, Any] | None = None,
) -> None:
    """Normalize missing runs vs persisted-state corruption for user commands."""

    from core_tools.persistence import PersistenceError, RunNotFoundError, StoreRevisionConflictError
    from top_down_planning.persistence.commit import StoreAuthorizationConflictError

    if isinstance(exc, RunNotFoundError):
        emit_error_with_fields(
            str(exc),
            exit_code=1,
            stream_json=stream_json,
            code="run_not_found",
            extra=_with_recovery(extra, code="run_not_found"),
        )
    if isinstance(exc, StoreRevisionConflictError):
        emit_error_with_fields(
            str(exc),
            exit_code=1,
            stream_json=stream_json,
            code="run_revision_conflict",
            extra=_with_recovery(extra, code="run_revision_conflict"),
        )
    if isinstance(exc, StoreAuthorizationConflictError):
        emit_error_with_fields(
            str(exc),
            exit_code=1,
            stream_json=stream_json,
            code="store_authorization_conflict",
            extra=_with_recovery(extra, code="store_authorization_conflict"),
        )
    if isinstance(exc, PersistenceError):
        emit_error_with_fields(
            str(exc),
            exit_code=1,
            stream_json=stream_json,
            code="corrupt_run",
            extra=_with_recovery(extra, code="corrupt_run"),
        )
    if isinstance(exc, OSError):
        if extra:
            from top_down_planning.orchestrator.failure import sanitize_operational_error

            emit_error_with_fields(
                sanitize_operational_error(exc),
                exit_code=1,
                stream_json=stream_json,
                code="operational_error",
                extra=_with_recovery(extra, code="operational_error"),
            )
        emit_operational_error(exc, stream_json=stream_json)
    raise exc


@contextmanager
def run_access_boundary(*, stream_json: bool) -> Iterator[None]:
    """Catch missing-run, corrupt-run, and filesystem errors for user commands."""

    try:
        yield
    except (RunNotFoundError, PersistenceError, OSError) as exc:
        emit_run_access_error(exc, stream_json=stream_json)


def emit_create_run_error(exc: BaseException, *, stream_json: bool) -> None:
    """Normalize pre-canonical create_run failures (no persisted run to repair)."""

    from core_tools.persistence import PersistenceError

    if isinstance(exc, PersistenceError):
        message = str(exc)
        code = (
            "creation_snapshot_changed"
            if "does not match resolved-config snapshot" in message
            or "does not match resolved config and workspace" in message
            else "run_creation_failed"
        )
        emit_error_message(
            message,
            exit_code=1,
            stream_json=stream_json,
            code=code,
        )
    if isinstance(exc, OSError):
        emit_operational_error(exc, stream_json=stream_json)
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


def emit_error_with_fields(
    message: str,
    *,
    code: str,
    stream_json: bool,
    exit_code: int = 1,
    extra: dict[str, Any] | None = None,
) -> None:
    """Emit a classified CLI error, optionally attaching recovery identity fields."""

    if stream_json:
        payload: dict[str, Any] = {
            "ok": False,
            "error": {"code": code, "message": message},
        }
        if extra:
            payload.update(extra)
        emit_payload(payload, exit_code=exit_code)
    lines = [message]
    if extra:
        run_id = str(extra.get("run_id") or "").strip()
        planning_run_id = str(extra.get("planning_run_id") or "").strip()
        if run_id:
            lines.append(f"Run: {run_id}")
        if planning_run_id and planning_run_id != run_id:
            lines.append(f"Planning run: {planning_run_id}")
        recovery = extra.get("recovery")
        if isinstance(recovery, dict):
            command = str(recovery.get("command") or "").strip()
            target = str(
                recovery.get("planning_run_id") or recovery.get("run_id") or ""
            ).strip()
            if command == "prepare" and target:
                lines.append(f"Next: tdp prepare --planning-run {target}")
            elif command and target:
                flag = "--planning-run" if command == "prepare" else "--run"
                lines.append(f"Next: tdp {command} {flag} {target}")
            elif command:
                lines.append(f"Next: tdp {command}")
    print("\n".join(lines), file=sys.stderr)
    raise SystemExit(exit_code)


def emit_continue_run_error(
    exc: BaseException,
    *,
    stream_json: bool,
    extra: dict[str, Any] | None = None,
) -> None:
    """Normalize engine-boundary failures for blocking CLI commands."""

    from top_down_planning.domain.run_ownership import RunOwnershipError

    if isinstance(exc, RunOwnershipError):
        emit_error_with_fields(
            str(exc),
            exit_code=1,
            stream_json=stream_json,
            code=exc.code,
            extra=_with_recovery(extra, code=exc.code),
        )
    if isinstance(exc, PersistenceError):
        emit_run_access_error(exc, stream_json=stream_json, extra=extra)
    if isinstance(exc, OSError):
        emit_run_access_error(exc, stream_json=stream_json, extra=extra)
    raise exc


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
    "emit_create_run_error",
    "run_access_boundary",
    "emit_operational_error",
    "emit_continue_run_error",
    "emit_error_with_fields",
    "recovery_fields",
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
