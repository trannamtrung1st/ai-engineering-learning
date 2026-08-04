"""Unit tests for package-owned prompt rendering."""

from __future__ import annotations

import pytest

from top_down_planning.prompts import PromptRenderError, render_prompt


def test_render_prompt_substitutes_context_values() -> None:
    rendered = render_prompt("test/fixture.md.j2", {"name": "planner"})
    assert rendered == "Hello planner."


def test_render_prompt_fails_on_missing_variable() -> None:
    with pytest.raises(PromptRenderError, match="missing template variable"):
        render_prompt("test/fixture.md.j2", {})


def test_render_prompt_fails_on_unknown_template() -> None:
    with pytest.raises(PromptRenderError, match="template not found"):
        render_prompt("missing/template.md.j2", {"name": "planner"})


def test_render_prompt_rejects_empty_output() -> None:
    with pytest.raises(PromptRenderError, match="rendered prompt is empty"):
        render_prompt("test/empty.md.j2", {})


def test_render_prompt_is_deterministic() -> None:
    context = {"name": "reviewer"}
    first = render_prompt("test/fixture.md.j2", context)
    second = render_prompt("test/fixture.md.j2", context)
    assert first == second


def test_render_prompt_rejects_path_traversal() -> None:
    with pytest.raises(PromptRenderError, match="path traversal"):
        render_prompt("../outside.md.j2", {"name": "planner"})


def test_render_prompt_rejects_absolute_template_paths() -> None:
    with pytest.raises(PromptRenderError, match="invalid template name"):
        render_prompt("/etc/passwd.md.j2", {"name": "planner"})
