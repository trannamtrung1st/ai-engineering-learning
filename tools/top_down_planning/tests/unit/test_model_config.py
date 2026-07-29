import os

from top_down_planning.model_config import resolve_embed_threshold, resolve_model
from top_down_planning.models import DEFAULT_CURSOR_MODEL, DEFAULT_INLINE_EMBED_THRESHOLD


def test_resolve_model_default() -> None:
    assert resolve_model(None) == DEFAULT_CURSOR_MODEL
    assert DEFAULT_CURSOR_MODEL == "auto"


def test_resolve_model_cli_override() -> None:
    assert resolve_model("custom-model") == "custom-model"


def test_resolve_model_env_override(monkeypatch) -> None:
    monkeypatch.setenv("PLANNING_TOOL_MODEL", "env-model")
    assert resolve_model(None) == "env-model"


def test_resolve_model_cli_beats_env(monkeypatch) -> None:
    monkeypatch.setenv("PLANNING_TOOL_MODEL", "env-model")
    assert resolve_model("cli-model") == "cli-model"


def test_resolve_embed_threshold_default() -> None:
    assert resolve_embed_threshold(None) == DEFAULT_INLINE_EMBED_THRESHOLD


def test_resolve_embed_threshold_cli_override() -> None:
    assert resolve_embed_threshold(100) == 100


def test_resolve_embed_threshold_env_override(monkeypatch) -> None:
    monkeypatch.setenv("PLANNING_TOOL_EMBED_THRESHOLD", "2500")
    assert resolve_embed_threshold(None) == 2500


def test_resolve_embed_threshold_cli_beats_env(monkeypatch) -> None:
    monkeypatch.setenv("PLANNING_TOOL_EMBED_THRESHOLD", "2500")
    assert resolve_embed_threshold(100) == 100
