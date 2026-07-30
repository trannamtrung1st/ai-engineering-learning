"""Role guardrails for agent tool mutations (proposal §17.3)."""

from __future__ import annotations

from typing import Literal

from top_down_planning.agent_tool.errors import RoleDeniedError

AgentRole = Literal["planner", "producer", "reviewer", "orchestrator"]

PLAN_MUTATION_ROLES: frozenset[AgentRole] = frozenset({"planner"})
PRODUCTION_MUTATION_ROLES: frozenset[AgentRole] = frozenset({"producer"})


def assert_plan_mutations_allowed(role: str) -> None:
    """Reject non-planner mutation attempts."""

    if role not in PLAN_MUTATION_ROLES:
        raise RoleDeniedError(role)


def assert_production_mutations_allowed(role: str) -> None:
    """Reject non-producer production mutation attempts."""

    if role not in PRODUCTION_MUTATION_ROLES:
        raise RoleDeniedError(
            role,
            action="Only the producer role may record production state.",
        )
