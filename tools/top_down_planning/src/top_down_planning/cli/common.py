"""Shared CLI helpers for user and agent commands."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def resolve_runs_dir(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    env = os.environ.get("TDP_RUNS_DIR", "").strip()
    if env:
        return Path(env).resolve()
    return Path.cwd() / "runs"


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
