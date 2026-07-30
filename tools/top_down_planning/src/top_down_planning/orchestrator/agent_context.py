"""Shared helpers for attaching effective role context to provider packages."""

from __future__ import annotations

from typing import Any

from top_down_planning.config import (
    AgentRole,
    EffectiveRoleContext,
    build_agent_context_manifest_payload,
    resolve_effective_role_context,
)
from top_down_planning.workspace import run_workspace

__all__ = [
    "attach_role_context_to_manifest",
    "resolve_role_session_context",
]


def resolve_role_session_context(
    config: dict[str, Any],
    run: dict[str, Any],
    role: AgentRole,
) -> EffectiveRoleContext:
    """Resolve effective role context using the persisted run workspace."""

    workspace = run_workspace(run)
    return resolve_effective_role_context(config, role, workspace=workspace)


def attach_role_context_to_manifest(
    manifest: dict[str, Any],
    *,
    config: dict[str, Any],
    run: dict[str, Any],
    role: AgentRole,
) -> dict[str, Any]:
    """Return a copy of ``manifest`` with ``agent_context`` attached."""

    context = resolve_role_session_context(config, run, role)
    merged = dict(manifest)
    merged.update(build_agent_context_manifest_payload(context))
    return merged
