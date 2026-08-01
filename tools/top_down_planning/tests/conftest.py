"""Shared pytest fixtures and helpers."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from io import StringIO
from unittest.mock import patch

import pytest

from top_down_planning.cli.main import main


@pytest.fixture(autouse=True)
def suppress_desktop_notifications(request: pytest.FixtureRequest):
    """Prevent real desktop notifications during tests (macOS/notify-py)."""

    if request.node.get_closest_marker("allow_desktop_notifications"):
        yield
        return

    targets = (
        "top_down_planning.notifications.desktop.send_desktop_notification",
        "top_down_planning.notifications.bridge.send_desktop_notification",
        "top_down_planning.notifications.outcome.send_desktop_notification",
    )
    patches = [patch(target, return_value=False) for target in targets]
    with patches[0], patches[1], patches[2]:
        yield


@dataclass(frozen=True)
class CliResult:
    exit_code: int
    stdout: str
    stderr: str

    def json(self) -> dict:
        text = self.stdout.strip()
        if not text:
            raise json.JSONDecodeError("empty stdout", text, 0)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        decoder = json.JSONDecoder()
        last: dict | None = None
        idx = 0
        while idx < len(text):
            while idx < len(text) and text[idx] not in "{[":
                idx += 1
            if idx >= len(text):
                break
            try:
                value, end = decoder.raw_decode(text, idx)
            except json.JSONDecodeError:
                idx += 1
                continue
            if isinstance(value, dict):
                last = value
            idx = end

        if last is not None:
            return last
        raise json.JSONDecodeError("no JSON object in stdout", text, 0)


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
