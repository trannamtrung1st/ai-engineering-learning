"""Agent activity catalog and role bindings (activity-aware agent context)."""

from __future__ import annotations

from typing import Literal

AgentRole = Literal["planner", "producer", "reviewer"]

AgentActivity = Literal[
    "initial_plan",
    "plan_revision",
    "plan_amendment",
    "production",
    "output_revision",
    "initial_review",
    "finding_verification",
    "scope_review",
]

ALLOWED_AGENT_ROLES: frozenset[str] = frozenset({"planner", "producer", "reviewer"})

ALLOWED_AGENT_ACTIVITIES: frozenset[str] = frozenset(
    {
        "initial_plan",
        "plan_revision",
        "plan_amendment",
        "production",
        "output_revision",
        "initial_review",
        "finding_verification",
        "scope_review",
    }
)

ACTIVITY_ROLE_MAP: dict[str, str] = {
    "initial_plan": "planner",
    "plan_revision": "planner",
    "plan_amendment": "planner",
    "production": "producer",
    "output_revision": "producer",
    "initial_review": "reviewer",
    "finding_verification": "reviewer",
    "scope_review": "reviewer",
}

ALLOWED_AGENT_CONTEXT_TOP_LEVEL_KEYS: frozenset[str] = frozenset(
    {"default", "bundled_skills", "roles", "activities"}
)

_AGENT_CONTEXT_OVERLAY_FIELDS: frozenset[str] = frozenset(
    {"model", "guidance", "resources", "skills"}
)


def role_for_activity(activity: str) -> str:
    """Return the orchestrator-owned role for an activity name."""

    role = ACTIVITY_ROLE_MAP.get(str(activity).strip())
    if role is None:
        raise ValueError(f"unknown activity: {activity!r}")
    return role


def assert_valid_activity_role_pair(role: str, activity: str) -> None:
    """Raise ValueError when role and activity are not a valid orchestrator pair."""

    expected = role_for_activity(activity)
    if str(role).strip() != expected:
        raise ValueError(
            f"activity {activity!r} must run as role {expected!r}, not {role!r}"
        )


def agent_context_override_paths() -> frozenset[str]:
    """Semantic override paths for agent_context overlays."""

    paths: set[str] = {"agent_context.bundled_skills"}
    for field in _AGENT_CONTEXT_OVERLAY_FIELDS:
        paths.add(f"agent_context.default.{field}")
    for role in sorted(ALLOWED_AGENT_ROLES):
        for field in _AGENT_CONTEXT_OVERLAY_FIELDS:
            paths.add(f"agent_context.roles.{role}.{field}")
    for activity in sorted(ALLOWED_AGENT_ACTIVITIES):
        for field in _AGENT_CONTEXT_OVERLAY_FIELDS:
            paths.add(f"agent_context.activities.{activity}.{field}")
    return frozenset(paths)


__all__ = [
    "ACTIVITY_ROLE_MAP",
    "ALLOWED_AGENT_ACTIVITIES",
    "ALLOWED_AGENT_CONTEXT_TOP_LEVEL_KEYS",
    "ALLOWED_AGENT_ROLES",
    "AgentActivity",
    "AgentRole",
    "agent_context_override_paths",
    "assert_valid_activity_role_pair",
    "role_for_activity",
]
