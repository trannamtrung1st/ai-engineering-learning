"""Unit tests for shared CLI helpers."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest

from core_tools.cli import (
    RequestError,
    emit_payload,
    load_structured_request,
    resolve_runs_dir,
)


def test_resolve_runs_dir_precedence(tmp_path: Path) -> None:
    cwd = tmp_path / "work"
    cwd.mkdir()
    explicit = tmp_path / "explicit"
    env = {"CUSTOM_RUNS_DIR": str(tmp_path / "env")}
    config = cwd / "config-runs"
    config.mkdir()

    assert resolve_runs_dir(explicit=explicit, cwd=cwd).path == explicit.resolve()
    assert (
        resolve_runs_dir(cwd=cwd, environ=env, env_var="CUSTOM_RUNS_DIR").path
        == (tmp_path / "env").resolve()
    )
    assert (
        resolve_runs_dir(config_value=config, cwd=cwd).path == config.resolve()
    )
    assert resolve_runs_dir(cwd=cwd).path == (cwd / "runs").resolve()


def test_emit_payload_exits_with_code(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        emit_payload({"ok": True}, exit_code=0)
    assert exc.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"ok": True}


def test_load_structured_request_from_json(tmp_path: Path) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text('{"action": "test"}', encoding="utf-8")
    payload = load_structured_request(request_path=str(request_path))
    assert payload == {"action": "test"}


def test_load_structured_request_empty_raises() -> None:
    with pytest.raises(RequestError, match="request body is empty"):
        load_structured_request(stdin=StringIO("   "))
