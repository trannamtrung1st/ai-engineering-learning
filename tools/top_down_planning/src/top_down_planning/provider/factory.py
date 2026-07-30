"""Provider factory from resolved configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from top_down_planning.provider.cursor import CursorProvider, ProcessRunner
from top_down_planning.provider.errors import ProviderError
from top_down_planning.provider.interface import Provider
from top_down_planning.provider.stub import StubProvider


def create_provider(
    config: dict[str, Any],
    *,
    workspace: Path | None = None,
    runner: ProcessRunner | None = None,
) -> Provider:
    """Create a provider adapter from resolved configuration."""

    provider_cfg = config.get("provider") or {}
    name = str(provider_cfg["name"]).strip().lower()

    if name == "stub":
        return StubProvider()

    if name == "cursor":
        return CursorProvider(
            config,
            workspace=workspace,
            runner=runner,
        )

    raise ProviderError(f"unknown provider.name: {name}")
