"""Package-owned Jinja prompt rendering."""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache

from jinja2 import (
    Environment,
    PackageLoader,
    StrictUndefined,
    TemplateNotFound,
    UndefinedError,
)
from jinja2.exceptions import TemplateError

from top_down_planning.prompts.errors import PromptRenderError

_TEMPLATE_PACKAGE = "top_down_planning.prompts"
_TEMPLATE_ROOT = "templates"


@lru_cache(maxsize=1)
def _prompt_environment() -> Environment:
    return Environment(
        loader=PackageLoader(_TEMPLATE_PACKAGE, _TEMPLATE_ROOT),
        undefined=StrictUndefined,
        autoescape=False,
        # Preserve template newlines so Markdown bullet includes stay on separate lines.
        trim_blocks=False,
        lstrip_blocks=False,
        keep_trailing_newline=False,
    )


def render_prompt(template_name: str, context: Mapping[str, object]) -> str:
    """Render a package-owned template with a narrow, explicit context."""

    normalized_name = str(template_name).strip().replace("\\", "/")
    if not normalized_name or normalized_name.startswith("/"):
        raise PromptRenderError(normalized_name or template_name, "invalid template name")
    if ".." in normalized_name.split("/"):
        raise PromptRenderError(normalized_name, "template path traversal is not allowed")

    environment = _prompt_environment()
    try:
        template = environment.get_template(normalized_name)
    except TemplateNotFound as exc:
        raise PromptRenderError(normalized_name, "template not found") from exc

    try:
        rendered = template.render(**dict(context))
    except UndefinedError as exc:
        raise PromptRenderError(normalized_name, "missing template variable") from exc
    except TemplateError as exc:
        raise PromptRenderError(normalized_name, "template rendering failed") from exc

    normalized = _normalize_output(rendered)
    if not normalized:
        raise PromptRenderError(normalized_name, "rendered prompt is empty")
    return normalized


def _normalize_output(text: str) -> str:
    return str(text).strip()


__all__ = ["render_prompt"]
