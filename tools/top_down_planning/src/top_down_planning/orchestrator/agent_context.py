"""Shared helpers for attaching effective role context to provider packages."""

from __future__ import annotations

from typing import Any

from top_down_planning.config import (
    AgentRole,
    EffectiveRoleContext,
    build_agent_context_manifest_payload,
    resolve_effective_role_context,
)
from top_down_planning.domain.models import Plan
from top_down_planning.workspace import run_workspace

__all__ = [
    "attach_role_context_to_manifest",
    "plan_execution_contract_fields",
    "resolve_role_session_context",
]


def resolve_role_session_context(
    config: dict[str, Any],
    run: dict[str, Any],
    role: AgentRole,
    *,
    output_goal: str | None = None,
) -> EffectiveRoleContext:
    """Resolve effective role context using the persisted run workspace."""

    workspace = run_workspace(run)
    return resolve_effective_role_context(
        config,
        role,
        workspace=workspace,
        output_goal=output_goal,
    )


def plan_execution_contract_fields(plan: Plan) -> dict[str, Any]:
    """Return normalized plan metadata used as the execution contract."""

    return {
        "plan_scope": plan.scope.to_dict(),
        "boundaries": list(plan.boundaries),
        "acceptance": list(plan.acceptance),
    }


def attach_role_context_to_manifest(
    manifest: dict[str, Any],
    *,
    config: dict[str, Any],
    run: dict[str, Any],
    role: AgentRole,
    output_goal: str | None = None,
) -> dict[str, Any]:
    """Return a copy of ``manifest`` with run contracts and ``agent_context`` attached."""

    context = resolve_role_session_context(
        config,
        run,
        role,
        output_goal=output_goal,
    )
    merged = dict(manifest)
    merged["input_refs"] = [str(path) for path in context.input_refs]
    merged["output_goal"] = context.output_goal
    merged.update(build_agent_context_manifest_payload(context))
    return merged
