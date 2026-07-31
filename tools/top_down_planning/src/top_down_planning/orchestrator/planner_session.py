"""Planner session manifest helpers."""

from __future__ import annotations

PLANNER_CANDIDATE_READY_SIGNAL = "candidate_plan_ready"


def build_planner_protocol_instructions() -> list[str]:
    """Provider-agnostic planner behavior instructions for session manifests."""

    return [
        (
            "You are the TDP planner. In the planning phase you expand the TDP "
            "plan tree stored in the run store. The phase name planning means "
            "plan-tree decomposition, not a host-IDE plan document or "
            "planning-only artifact."
        ),
        (
            "Mutate plan state only through the tdp agent plan shell commands "
            "in tool_instructions (snapshot, apply, check). Read-only workspace "
            "inspection is allowed."
        ),
        (
            "Do not switch to host planning modes or use planning-only tools. "
            "The orchestrator cannot consume those artifacts and the run will "
            "not advance."
        ),
        (
            "When the plan satisfies stop_hint and passes plan check, emit "
            "completion_signal as your final assistant line or as done.signal "
            "metadata."
        ),
        (
            "Discover request contracts with tdp agent readme, tdp agent "
            "schema, and tdp agent example."
        ),
    ]


def build_planner_tool_instructions(run_id: str) -> dict[str, str]:
    """CLI instructions embedded in planner session manifests."""

    return {
        "authorization": (
            "Mutating commands require the session capability token exported "
            "as TDP_CAPABILITY_TOKEN."
        ),
        "snapshot": f"tdp agent plan snapshot --run {run_id} --view active",
        "apply": f"tdp agent plan apply --run {run_id} --request <file>",
        "check": f"tdp agent plan check --run {run_id}",
        "request_review": f"tdp agent review request --run {run_id} --request <file>",
        "completion_signal": PLANNER_CANDIDATE_READY_SIGNAL,
    }


__all__ = [
    "PLANNER_CANDIDATE_READY_SIGNAL",
    "build_planner_protocol_instructions",
    "build_planner_tool_instructions",
]
