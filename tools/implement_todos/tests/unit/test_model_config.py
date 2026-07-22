import os

from todos_tool.model_config import resolve_model
from todos_tool.models import DEFAULT_CURSOR_MODEL


def test_resolve_model_default() -> None:
    assert resolve_model(None) == DEFAULT_CURSOR_MODEL
    assert DEFAULT_CURSOR_MODEL == "composer-2.5"


def test_resolve_model_cli_override() -> None:
    assert resolve_model("custom-model") == "custom-model"


def test_resolve_model_env_override(monkeypatch) -> None:
    monkeypatch.setenv("TODOS_TOOL_MODEL", "env-model")
    assert resolve_model(None) == "env-model"


def test_resolve_model_cli_beats_env(monkeypatch) -> None:
    monkeypatch.setenv("TODOS_TOOL_MODEL", "env-model")
    assert resolve_model("cli-model") == "cli-model"


def test_resolve_model_manifest_override() -> None:
    assert (
        resolve_model(None, manifest_model="manifest-model", workspace_loaded=True)
        == "manifest-model"
    )


def test_resolve_model_explicit_null_in_manifest() -> None:
    assert resolve_model(None, manifest_model=None, workspace_loaded=True) is None


def test_resolve_model_default_before_workspace_load() -> None:
    assert resolve_model(None, manifest_model=None, workspace_loaded=False) == (
        DEFAULT_CURSOR_MODEL
    )
