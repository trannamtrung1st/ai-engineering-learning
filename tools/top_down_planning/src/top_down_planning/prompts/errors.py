"""Prompt rendering errors."""

from __future__ import annotations


class PromptRenderError(Exception):
    """Raised when a package-owned prompt template cannot be rendered safely."""

    def __init__(self, template_name: str, message: str) -> None:
        self.template_name = template_name
        super().__init__(f"Failed to render prompt template {template_name!r}: {message}")


__all__ = ["PromptRenderError"]
