"""Shared helpers for attaching effective activity context to provider packages."""

from __future__ import annotations

from typing import Any

from top_down_planning.config import (
    AgentActivity,
    AgentRole,
    EffectiveActivityContext,
    build_agent_context_manifest_payload,
    resolve_effective_activity_context,
)
from top_down_planning.domain.models import Plan
from top_down_planning.workspace import run_workspace

__all__ = [
    "attach_activity_context_to_manifest",
    "manifest_agent_context_fields",
    "plan_execution_contract_fields",
    "resolve_activity_session_context",
]


def manifest_agent_context_fields(
    manifest: dict[str, Any],
) -> tuple[str | None, str | None]:
    """Return activity and context_digest from a provider manifest, when present."""

    agent_context = manifest.get("agent_context")
    if not isinstance(agent_context, dict):
        return None, None
    activity_raw = agent_context.get("activity")
    digest_raw = agent_context.get("context_digest")
    activity = (
        str(activity_raw).strip()
        if activity_raw is not None and str(activity_raw).strip()
        else None
    )
    context_digest = (
        str(digest_raw).strip()
        if digest_raw is not None and str(digest_raw).strip()
        else None
    )
    return activity, context_digest


def resolve_activity_session_context(
    config: dict[str, Any],
    run: dict[str, Any],
    role: AgentRole,
    activity: AgentActivity,
    *,
    output_goal: str | None = None,
) -> EffectiveActivityContext:
    """Resolve effective activity context using the persisted run workspace."""

    workspace = run_workspace(run)
    return resolve_effective_activity_context(
        config,
        role,
        activity,
        workspace=workspace,
        output_goal=output_goal,
    )


def plan_execution_contract_fields(plan: Plan) -> dict[str, Any]:
    """Return normalized plan metadata used as the execution contract."""

    return {
        "plan_scope": plan.scope.to_dict(),
        "boundaries": list(plan.boundaries),
        "acceptance": list(plan.acceptance),
        "risks": list(plan.risks),
    }


def attach_activity_context_to_manifest(
    manifest: dict[str, Any],
    *,
    config: dict[str, Any],
    run: dict[str, Any],
    role: AgentRole,
    activity: AgentActivity,
    output_goal: str | None = None,
) -> dict[str, Any]:
    """Return a copy of ``manifest`` with run contracts and ``agent_context`` attached."""

    context = resolve_activity_session_context(
        config,
        run,
        role,
        activity,
        output_goal=output_goal,
    )
    merged = dict(manifest)
    merged["input_refs"] = [str(path) for path in context.input_refs]
    merged["output_goal"] = context.output_goal
    merged.update(build_agent_context_manifest_payload(context))
    return merged
