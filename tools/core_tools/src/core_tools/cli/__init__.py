"""Shared CLI helpers for agent orchestration tools."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Type

from core_tools.config.paths import resolve_path
from core_tools.persistence import load_yaml

RunsDirSource = Literal["cli", "environment", "config", "default"]


class RequestError(Exception):
    """Structured request loading failed."""


@dataclass(frozen=True)
class ResolvedRunsDir:
    path: Path
    source: RunsDirSource


def resolve_runs_dir(
    *,
    explicit: str | Path | None = None,
    config_value: str | Path | None = None,
    cwd: Path | None = None,
    environ: Mapping[str, str] | None = None,
    env_var: str = "RUNS_DIR",
    default_relative: str = "runs",
) -> ResolvedRunsDir:
    """
    Resolve the run-store root with precedence:
    explicit CLI --runs-dir > env_var > config_value > <cwd>/default_relative.
    """

    base = (cwd or Path.cwd()).resolve()
    env = environ if environ is not None else os.environ

    if explicit is not None and str(explicit).strip():
        return ResolvedRunsDir(Path(explicit).resolve(), "cli")

    env_value = str(env.get(env_var, "")).strip()
    if env_value:
        return ResolvedRunsDir(Path(env_value).resolve(), "environment")

    if config_value is not None and str(config_value).strip():
        configured = resolve_path(str(config_value).strip(), cwd=base)
        return ResolvedRunsDir(configured, "config")

    return ResolvedRunsDir((base / default_relative).resolve(), "default")


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


def load_structured_request(
    *,
    request_path: str | None = None,
    stdin: Any | None = None,
    error_type: Type[Exception] = RequestError,
) -> dict[str, Any]:
    """Load a JSON or YAML request object from a file or stdin."""

    if request_path:
        path = Path(request_path)
        if not path.exists():
            raise error_type(f"request file not found: {path}")
        text = path.read_text(encoding="utf-8")
    else:
        stream = stdin if stdin is not None else sys.stdin
        text = stream.read()

    text = text.strip()
    if not text:
        raise error_type(
            "request body is empty; provide JSON or YAML via stdin or --request"
        )

    payload = _parse_structured_text(text, error_type=error_type)
    if not isinstance(payload, dict):
        raise error_type("request body must be a JSON or YAML object")
    return payload


def _parse_structured_text(text: str, *, error_type: Type[Exception]) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    try:
        return load_yaml(text)
    except ValueError as exc:
        raise error_type(f"failed to parse request body: {exc}") from exc


__all__ = [
    "RequestError",
    "ResolvedRunsDir",
    "RunsDirSource",
    "emit_error_message",
    "emit_message",
    "emit_payload",
    "load_structured_request",
    "resolve_runs_dir",
]
