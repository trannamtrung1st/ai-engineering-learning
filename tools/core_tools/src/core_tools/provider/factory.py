"""Provider factory from resolved configuration."""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from core_tools.provider.cursor import CursorProvider, ProcessRunner
from core_tools.provider.errors import ProviderError, ProviderUnsupportedPlatformError
from core_tools.provider.interface import Provider
from core_tools.provider.stub import StubProvider


def create_provider(
    config: dict[str, Any],
    *,
    workspace: Path | None = None,
    runner: ProcessRunner | None = None,
    extra_env: Mapping[str, str] | None = None,
    on_provider_event: Callable[[dict[str, Any]], None] | None = None,
) -> Provider:
    """Create a provider adapter from resolved configuration."""

    provider_cfg = config.get("provider") or {}
    name = str(provider_cfg["name"]).strip().lower()

    if name == "stub":
        return StubProvider(on_provider_event=on_provider_event)

    if name == "cursor":
        if sys.platform == "win32":
            raise ProviderUnsupportedPlatformError(
                "CursorProvider is POSIX-only; Windows process-tree ownership "
                "is not supported"
            )
        return CursorProvider(
            config,
            workspace=workspace,
            runner=runner,
            extra_env=extra_env,
            on_provider_event=on_provider_event,
        )

    raise ProviderError(f"unknown provider.name: {name}")
