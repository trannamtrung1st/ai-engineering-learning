"""Shared run-specific provider factory for prepared execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from core_tools.provider import Provider, create_provider as build_provider

from top_down_planning.cli.common import ResolvedRunsDir, provider_extra_env
from top_down_planning.observability import ObservabilityContext, wrap_store_with_observability
from top_down_planning.persistence import FileRunStore

ProviderFactory = Callable[[dict[str, Any], Path], Provider]


@dataclass(frozen=True)
class ExecutionRuntime:
    """Provider factory and optional teardown for one prepared execution run."""

    create_provider: ProviderFactory
    observing_store: FileRunStore
    teardown: Callable[[], None]


def provider_factory_for_run(
    *,
    store: FileRunStore,
    resolved_runs: ResolvedRunsDir,
    observability: ObservabilityContext | None = None,
    workspace: Path | None = None,
) -> Callable[[str], ProviderFactory]:
    """Return a factory that builds a provider factory bound to a specific run id."""

    def for_run(run_id: str) -> ProviderFactory:
        def create_provider(config: dict[str, Any], child_workspace: Path) -> Provider:
            return build_provider(
                config,
                workspace=child_workspace if workspace is None else workspace,
                extra_env=provider_extra_env(
                    resolved_runs,
                    run_id=run_id,
                    store=store,
                ),
                on_provider_event=(
                    observability.provider_callback() if observability is not None else None
                ),
            )

        return create_provider

    return for_run


def build_execution_runtime(
    *,
    store: FileRunStore,
    run_id: str,
    resolved_runs: ResolvedRunsDir,
    observability: ObservabilityContext | None = None,
    workspace: Path | None = None,
) -> ExecutionRuntime:
    """Build the shared provider factory for a prepared parent or child run."""

    create_provider = provider_factory_for_run(
        store=store,
        resolved_runs=resolved_runs,
        observability=observability,
        workspace=workspace,
    )(run_id)

    def teardown() -> None:
        return None

    observing_store = (
        wrap_store_with_observability(store, observability)
        if observability is not None
        else store
    )

    return ExecutionRuntime(
        create_provider=create_provider,
        observing_store=observing_store,
        teardown=teardown,
    )


__all__ = [
    "ExecutionRuntime",
    "ProviderFactory",
    "build_execution_runtime",
    "provider_factory_for_run",
]
