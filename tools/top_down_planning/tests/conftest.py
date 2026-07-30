"""Shared pytest fixtures and helpers."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from io import StringIO

from top_down_planning.cli.main import main


@dataclass(frozen=True)
class CliResult:
    exit_code: int
    stdout: str
    stderr: str

    def json(self) -> dict:
        return json.loads(self.stdout)


def run_cli(argv: list[str]) -> CliResult:
    """Invoke the CLI in-process and capture stdout/stderr."""

    out = StringIO()
    err = StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        try:
            main(argv)
            exit_code = 0
        except SystemExit as exc:
            code = exc.code
            exit_code = 0 if code is None else int(code)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return CliResult(exit_code=exit_code, stdout=out.getvalue(), stderr=err.getvalue())
