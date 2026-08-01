"""Request path resolution and containment for agent CLI commands."""

from __future__ import annotations

import os
from pathlib import Path

from top_down_planning.agent_tool.authorization import resolve_capability_token
from top_down_planning.agent_tool.errors import RequestError
from top_down_planning.cli.common import RUN_ID_ENV_VAR
from top_down_planning.persistence.file_store import AGENT_REQUESTS_DIR

SOURCE_KIND_AGENT_REQUESTS = "agent_requests"
SOURCE_KIND_STDIN = "stdin"


def is_capability_backed_session(capability_token: str | None = None) -> bool:
    """Return True when a capability token is present in args or process env."""

    return resolve_capability_token(capability_token) is not None


def assert_run_id_env_matches(run_id: str, *, capability_token: str | None = None) -> None:
    """Reject when capability context is active and TDP_RUN_ID disagrees with --run."""

    if not is_capability_backed_session(capability_token):
        return
    env_run_id = os.environ.get(RUN_ID_ENV_VAR)
    if env_run_id is None or not str(env_run_id).strip():
        return
    if str(env_run_id).strip() != run_id:
        raise RequestError(
            f"TDP_RUN_ID {env_run_id!r} does not match --run {run_id!r}"
        )


def _path_is_contained(path: Path, boundary: Path) -> bool:
    try:
        path.resolve().relative_to(boundary.resolve())
    except ValueError:
        return False
    return True


def _resolve_existing_path(request_path: str) -> Path:
    raw = Path(request_path)
    if not raw.is_absolute():
        candidate = (Path.cwd() / raw).resolve(strict=False)
    else:
        candidate = raw.resolve(strict=False)
    try:
        return candidate.resolve(strict=True)
    except OSError as exc:
        raise RequestError(f"request file not found: {request_path}") from exc


def resolve_request_path(
    request_path: str,
    *,
    agent_requests_dir: Path,
) -> Path:
    """Resolve a request file path and enforce agent-requests/ containment."""

    resolved = _resolve_existing_path(request_path)
    boundary = agent_requests_dir.resolve()
    if not _path_is_contained(resolved, boundary):
        raise RequestError(
            f"request path must remain inside {boundary}; got {resolved}"
        )
    return resolved


def classify_request_source(
    resolved_path: Path | None,
    *,
    agent_requests_dir: Path,
) -> tuple[str, str]:
    """Return (source_kind, source) for audit events."""

    if resolved_path is None:
        return SOURCE_KIND_STDIN, "stdin"

    boundary = agent_requests_dir.resolve()
    relative = resolved_path.resolve().relative_to(boundary)
    return SOURCE_KIND_AGENT_REQUESTS, f"{AGENT_REQUESTS_DIR}/{relative.as_posix()}"


__all__ = [
    "SOURCE_KIND_AGENT_REQUESTS",
    "SOURCE_KIND_STDIN",
    "assert_run_id_env_matches",
    "classify_request_source",
    "is_capability_backed_session",
    "resolve_request_path",
]
