"""Provider adapter layer (proposal §16, §17.4)."""

from top_down_planning.provider.cursor import (
    CursorProvider,
    build_agent_argv,
    default_process_runner,
    resolve_agent_binary,
)
from top_down_planning.provider.errors import (
    ProviderBinaryNotFoundError,
    ProviderError,
    ProviderSessionError,
    ProviderTurnError,
)
from top_down_planning.provider.events import normalize_cursor_event
from top_down_planning.provider.factory import create_provider
from top_down_planning.provider.interface import Provider
from top_down_planning.provider.stub import StubProvider

__all__ = [
    "CursorProvider",
    "Provider",
    "ProviderBinaryNotFoundError",
    "ProviderError",
    "ProviderSessionError",
    "ProviderTurnError",
    "StubProvider",
    "build_agent_argv",
    "create_provider",
    "default_process_runner",
    "normalize_cursor_event",
    "resolve_agent_binary",
]
