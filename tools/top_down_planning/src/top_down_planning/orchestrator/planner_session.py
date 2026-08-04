"""Planner session manifest helpers."""

from __future__ import annotations

from typing import Any

from top_down_planning.domain.session_bindings import SessionBinding
from top_down_planning.prompts import render_prompt
from top_down_planning.prompts.contexts import planner_protocol_context
from top_down_planning.persistence.capabilities import CAPABILITY_TOKEN_FILE_ENV_VAR
from top_down_planning.persistence.session_bindings import (
    get_primary_binding,
    primary_provider_session_id,
)

PLANNER_CANDIDATE_READY_SIGNAL = "candidate_plan_ready"


def primary_planner_provider_session_id(run: dict[str, Any]) -> str | None:
    return primary_provider_session_id(run, "planner")


def primary_planner_binding(run: dict[str, Any]) -> SessionBinding | None:
    return get_primary_binding(run, "planner")


def build_planner_protocol_instructions() -> str:
    """Provider-agnostic planner behavior instructions for session manifests."""

    return render_prompt("planner/protocol.md.j2", planner_protocol_context())


def build_planner_tool_instructions(run_id: str) -> dict[str, str]:
    """CLI instructions embedded in planner session manifests."""

    return {
        "authorization": (
            "Mutating commands require the session capability token from "
            f"{CAPABILITY_TOKEN_FILE_ENV_VAR}."
        ),
        "agent_requests_dir": "$TDP_AGENT_REQUESTS_DIR",
        "snapshot": f"tdp agent plan snapshot --run {run_id} --view active",
        "apply": (
            f"tdp agent plan apply --run {run_id} "
            "--request $TDP_AGENT_REQUESTS_DIR/plan-apply-r<rev>-a01.json"
        ),
        "check": f"tdp agent plan check --run {run_id}",
        "request_review": (
            f"tdp agent review request --run {run_id} "
            "--request $TDP_AGENT_REQUESTS_DIR/review-request-<scope>-a01.json"
        ),
        "completion_signal": PLANNER_CANDIDATE_READY_SIGNAL,
        "discover": (
            "tdp agent readme; tdp agent schema plan-transaction; "
            "tdp agent example expand-branch"
        ),
        "plan_depends_on": (
            "For new items in the same batch, set add_item.item.depends_on inline "
            "(stable ids or same-batch temp_id; string or array). For existing "
            "items, use add_dependency. See tdp agent example expand-branch."
        ),
    }


__all__ = [
    "PLANNER_CANDIDATE_READY_SIGNAL",
    "build_planner_protocol_instructions",
    "build_planner_tool_instructions",
    "primary_planner_binding",
    "primary_planner_provider_session_id",
]
