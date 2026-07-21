import os

from top_down_planning.model_config import resolve_model
from top_down_planning.models import DEFAULT_CURSOR_MODEL


def test_resolve_model_default() -> None:
    assert resolve_model(None) == DEFAULT_CURSOR_MODEL
    assert DEFAULT_CURSOR_MODEL == "gpt-5.6-sol-high"


def test_resolve_model_cli_override() -> None:
    assert resolve_model("custom-model") == "custom-model"


def test_resolve_model_env_override(monkeypatch) -> None:
    monkeypatch.setenv("PLANNING_TOOL_MODEL", "env-model")
    assert resolve_model(None) == "env-model"


def test_resolve_model_cli_beats_env(monkeypatch) -> None:
    monkeypatch.setenv("PLANNING_TOOL_MODEL", "env-model")
    assert resolve_model("cli-model") == "cli-model"
