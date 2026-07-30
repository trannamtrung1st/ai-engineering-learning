"""Role guardrails for agent tool mutations (proposal §17.3)."""

from __future__ import annotations

from typing import Literal

from top_down_planning.agent_tool.errors import RoleDeniedError

AgentRole = Literal["planner", "producer", "reviewer", "orchestrator"]

PLAN_MUTATION_ROLES: frozenset[AgentRole] = frozenset({"planner"})


def assert_plan_mutations_allowed(role: str) -> None:
    """Reject non-planner mutation attempts."""

    if role not in PLAN_MUTATION_ROLES:
        raise RoleDeniedError(role)
