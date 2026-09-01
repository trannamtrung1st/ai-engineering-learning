"""Producer session manifest helpers."""

from __future__ import annotations

from typing import Any

from top_down_planning.domain.session_bindings import SessionBinding
from top_down_planning.prompts import render_prompt
from top_down_planning.prompts.contexts import producer_protocol_context
from top_down_planning.persistence.capabilities import CAPABILITY_TOKEN_FILE_ENV_VAR
from top_down_planning.persistence.session_bindings import (
    get_primary_binding,
    primary_provider_session_id,
)

PRODUCER_BATCH_COMPLETE_SIGNAL = "batch_complete"
PRODUCER_COMPLETION_COMPLETE_SIGNAL = "completion_claimed"
PRODUCER_FOCUSED_REVIEW_REQUESTED_SIGNAL = "focused_review_requested"


def primary_producer_provider_session_id(run: dict[str, Any]) -> str | None:
    return primary_provider_session_id(run, "producer")


def primary_producer_binding(run: dict[str, Any]) -> SessionBinding | None:
    return get_primary_binding(run, "producer")


def build_producer_protocol_instructions() -> str:
    """Provider-agnostic producer behavior instructions for session manifests."""

    return render_prompt("producer/protocol.md.j2", producer_protocol_context())


def build_producer_tool_instructions(run_id: str) -> dict[str, str]:
    """CLI instructions embedded in producer session manifests."""

    return {
        "authorization": (
            "Mutating commands require the session capability token from "
            f"{CAPABILITY_TOKEN_FILE_ENV_VAR}."
        ),
        "agent_requests_dir": "$TDP_AGENT_REQUESTS_DIR",
        "snapshot": f"tdp agent production snapshot --run {run_id} --view ready",
        "apply": (
            f"tdp agent production apply --run {run_id} "
            "--request $TDP_AGENT_REQUESTS_DIR/production-apply-batch-01-a01.json"
        ),
        "check": f"tdp agent production check --run {run_id}",
        "request_amendment": (
            f"tdp agent production request-amendment --run {run_id} "
            "--request $TDP_AGENT_REQUESTS_DIR/production-amendment-a01.json"
        ),
        "submit_completion": (
            f"tdp agent production submit-completion --run {run_id} "
            "--request $TDP_AGENT_REQUESTS_DIR/production-completion-a01.json"
        ),
        "report_blocked": (
            f"tdp agent production report-blocked --run {run_id} "
            "--request $TDP_AGENT_REQUESTS_DIR/production-blocked-a01.json"
        ),
        "request_review": (
            f"tdp agent review request --run {run_id} "
            "--request $TDP_AGENT_REQUESTS_DIR/review-request-<scope>-a01.json"
        ),
        "discover": (
            "tdp agent readme; tdp agent schema production-apply; "
            "tdp agent example batch-result; tdp agent example completion-claim"
        ),
    }


__all__ = [
    "PRODUCER_BATCH_COMPLETE_SIGNAL",
    "PRODUCER_COMPLETION_COMPLETE_SIGNAL",
    "PRODUCER_FOCUSED_REVIEW_REQUESTED_SIGNAL",
    "build_producer_protocol_instructions",
    "build_producer_tool_instructions",
    "primary_producer_binding",
    "primary_producer_provider_session_id",
]
