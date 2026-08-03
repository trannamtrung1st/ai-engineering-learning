"""Producer session manifest helpers."""

from __future__ import annotations

from typing import Any

from top_down_planning.domain.session_bindings import SessionBinding
from top_down_planning.persistence.session_bindings import (
    get_primary_binding,
    primary_provider_session_id,
)

PRODUCER_BATCH_COMPLETE_SIGNAL = "batch_complete"


def primary_producer_provider_session_id(run: dict[str, Any]) -> str | None:
    return primary_provider_session_id(run, "producer")


def primary_producer_binding(run: dict[str, Any]) -> SessionBinding | None:
    return get_primary_binding(run, "producer")


def build_producer_protocol_instructions() -> list[str]:
    """Provider-agnostic producer behavior instructions for session manifests."""

    return [
        (
            "You are the TDP producer. Record batches, evidence, and "
            "dispositions through tdp agent production commands in "
            "tool_instructions."
        ),
        (
            "Do not use host planning modes or planning-only tools. Production "
            "state advances only through persisted tdp agent commands."
        ),
        (
            "Include every changed snapshot-bound artifact in each batch's "
            "outputs before calling production apply. Git diff may help "
            "discovery, but only declared output refs authorize snapshot drift."
        ),
        (
            "When production apply reports production_evidence_incomplete, "
            "add every listed workspace path to outputs and retry with the current "
            "production_revision."
        ),
        (
            "When production apply reports "
            "production_context_mutation_unauthorized, revert or reconcile "
            "unauthorized snapshot-bound context changes (skills, file or inline "
            "guidance, and similar binding keys). Those paths cannot be "
            "authorized through outputs."
        ),
        (
            "Emit batch_complete_signal after each recorded batch when more "
            "work remains. Submit completion with goal_met and "
            "goal_assessment when the output goal is met."
        ),
        (
            "Discover request contracts with tdp agent readme, tdp agent "
            "schema, and tdp agent example. Role skill: "
            "tools/top_down_planning/skills/tdp-agent/producer."
        ),
        (
            "Write mutating request payloads only under $TDP_AGENT_REQUESTS_DIR. "
            "Do not create .tdp-* or .review-* dotfiles in the project workspace "
            "or harness folders. Do not modify orchestrator-owned run files."
        ),
        (
            "Each production batch must stay within the plan item's "
            "effective_scope and effective_boundaries. Item scope and "
            "boundaries are the item-owned slice; effective_* is the union "
            "with plan-level guardrails. Use item acceptance and risks as the "
            "verifiable batch contract."
        ),
    ]


def build_producer_tool_instructions(run_id: str) -> dict[str, str]:
    """CLI instructions embedded in producer session manifests."""

    return {
        "authorization": (
            "Mutating commands require the session capability token exported "
            "as TDP_CAPABILITY_TOKEN."
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
        "batch_complete_signal": PRODUCER_BATCH_COMPLETE_SIGNAL,
        "discover": (
            "tdp agent readme; tdp agent schema production-apply; "
            "tdp agent example batch-result; tdp agent example completion-claim"
        ),
    }


__all__ = [
    "PRODUCER_BATCH_COMPLETE_SIGNAL",
    "build_producer_protocol_instructions",
    "build_producer_tool_instructions",
    "primary_producer_binding",
    "primary_producer_provider_session_id",
]
