"""Unit tests for package-owned prompt rendering."""

from __future__ import annotations

import pytest

from top_down_planning.prompts import PromptRenderError, render_prompt
from top_down_planning.prompts.contexts import planner_protocol_context
from top_down_planning.prompts.renderer import _normalize_output


def test_render_prompt_substitutes_context_values() -> None:
    rendered = render_prompt("planner/protocol.md.j2", planner_protocol_context())
    assert "TDP planner" in rendered
    assert "item-root" in rendered


def test_render_prompt_fails_on_missing_variable() -> None:
    with pytest.raises(PromptRenderError, match="missing template variable"):
        render_prompt("planner/protocol.md.j2", {})


def test_render_prompt_fails_on_unknown_template() -> None:
    with pytest.raises(PromptRenderError, match="template not found"):
        render_prompt("missing/template.md.j2", planner_protocol_context())


def test_normalize_output_rejects_blank_rendered_text() -> None:
    assert _normalize_output("   \n") == ""


def test_render_prompt_rejects_empty_output(monkeypatch) -> None:
    from top_down_planning.prompts import renderer

    class _Template:
        def render(self, **kwargs: object) -> str:
            return "\n"

    class _Environment:
        def get_template(self, name: str) -> _Template:
            return _Template()

    renderer._prompt_environment.cache_clear()
    monkeypatch.setattr(renderer, "_prompt_environment", lambda: _Environment())

    with pytest.raises(PromptRenderError, match="rendered prompt is empty"):
        renderer.render_prompt("planner/protocol.md.j2", planner_protocol_context())


def test_render_prompt_is_deterministic() -> None:
    context = planner_protocol_context()
    first = render_prompt("planner/protocol.md.j2", context)
    second = render_prompt("planner/protocol.md.j2", context)
    assert first == second


def test_render_prompt_rejects_path_traversal() -> None:
    with pytest.raises(PromptRenderError, match="path traversal"):
        render_prompt("../outside.md.j2", planner_protocol_context())


def test_render_prompt_rejects_absolute_template_paths() -> None:
    with pytest.raises(PromptRenderError, match="invalid template name"):
        render_prompt("/etc/passwd.md.j2", planner_protocol_context())
