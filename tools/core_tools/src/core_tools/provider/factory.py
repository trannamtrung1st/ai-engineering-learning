"""Provider factory from resolved configuration."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from core_tools.provider.cursor import CursorProvider, ProcessRunner
from core_tools.provider.errors import ProviderError
from core_tools.provider.interface import Provider
from core_tools.provider.stub import StubProvider


def create_provider(
    config: dict[str, Any],
    *,
    workspace: Path | None = None,
    runner: ProcessRunner | None = None,
    extra_env: Mapping[str, str] | None = None,
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
            extra_env=extra_env,
        )

    raise ProviderError(f"unknown provider.name: {name}")
