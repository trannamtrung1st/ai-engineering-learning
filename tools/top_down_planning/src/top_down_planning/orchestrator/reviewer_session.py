"""Reviewer session allocation, capability binding, and turn delivery."""

from __future__ import annotations

from typing import Any

from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.domain.session_bindings import is_transient_provider_session_id
from top_down_planning.prompts import render_prompt
from top_down_planning.prompts.contexts import reviewer_protocol_context
from top_down_planning.domain.session_bindings import (
    SessionBinding,
    resumable_binding_provider_session_id,
)
from top_down_planning.orchestrator.capability import (
    bind_provider_capability,
    issue_session_capability,
)
from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.persistence.capabilities import CAPABILITY_TOKEN_FILE_ENV_VAR
from top_down_planning.persistence.interface import RunStore
from core_tools.provider import Provider

REVIEWER_GATE_CONTINUE_BLOCKED_REASON = (
    "The previous reviewer provider turn ended without a persisted "
    "`tdp agent review respond` decision. Follow protocol_instructions and "
    "submit your decision now."
)

REVIEWER_DECISION_COMPLETE_SIGNAL = "review_decision_complete"
OWNER_FINDING_ACTION_COMPLETE_SIGNAL = "owner_finding_action_complete"


class ReviewerRecheckRequiresNewSession(Exception):
    """The bound reviewer session is missing; begin a new session with the recheck package."""


def reviewer_loop_provider_session_id(loop: ReviewLoop | dict[str, Any]) -> str | None:
    if isinstance(loop, ReviewLoop):
        return resumable_binding_provider_session_id(loop.reviewer_binding)
    binding_raw = loop.get("reviewer_binding")
    if isinstance(binding_raw, dict):
        return resumable_binding_provider_session_id(binding_raw)
    return None


def reviewer_loop_binding(loop: ReviewLoop | dict[str, Any]) -> SessionBinding | None:
    if isinstance(loop, ReviewLoop):
        return loop.reviewer_binding
    binding_raw = loop.get("reviewer_binding")
    if isinstance(binding_raw, dict) and binding_raw.get("session_instance_id"):
        return SessionBinding.from_dict(binding_raw)
    return None


def build_reviewer_protocol_instructions(
    *,
    stage: str | None = None,
    review_type: str | None = None,
) -> str:
    """Provider-agnostic reviewer behavior instructions for review packages."""

    return render_prompt(
        "reviewer/protocol.md.j2",
        reviewer_protocol_context(stage=stage, review_type=review_type),
    )


def build_reviewer_tool_instructions(
    run_id: str,
    *,
    review_type: str | None = None,
    **extra: str,
) -> dict[str, str]:
    """CLI instructions embedded in reviewer review packages."""

    mandatory_family = review_type in {"whole_plan", "whole_output"}
    if mandatory_family:
        if review_type == "whole_output":
            examples = (
                "tdp agent example review-respond-family-discovery-output ; "
                "tdp agent example review-respond-family-verification-output ; "
                "tdp agent example review-respond-scope"
            )
        else:
            examples = (
                "tdp agent example review-respond-family-discovery ; "
                "tdp agent example review-respond-family-verification ; "
                "tdp agent example review-respond-scope"
            )
    elif review_type == "focused_output":
        examples = (
            "tdp agent example review-respond ; "
            "tdp agent example review-respond-focused-with-instance-ref ; "
            "tdp agent example review-respond-family-discovery-focused-output ; "
            "tdp agent example review-respond-verification"
        )
    elif review_type == "focused_plan":
        examples = (
            "tdp agent example review-respond ; "
            "tdp agent example review-respond-focused-with-instance-ref ; "
            "tdp agent example review-respond-family-discovery-focused-plan ; "
            "tdp agent example review-respond-verification"
        )
    else:
        examples = (
            "tdp agent example review-respond ; "
            "tdp agent example review-respond-verification"
        )
    readme_sections = (
        "Audit attestation; Built-in finding-family rule_id values"
        if mandatory_family
        else "Built-in finding-family rule_id values"
    )
    instructions = {
        "authorization": (
            "Mutating commands require the session capability token from "
            f"{CAPABILITY_TOKEN_FILE_ENV_VAR} on the provider subprocess that runs "
            "your review turn."
        ),
        "agent_requests_dir": "$TDP_AGENT_REQUESTS_DIR",
        "respond": (
            f"tdp agent review respond --run {run_id} "
            "--request $TDP_AGENT_REQUESTS_DIR/review-respond-<stage>-r<rev>-a01.json "
            "(invoke `tdp` directly; do not wrap with `uv run`)"
        ),
        "completion_requirement": (
            "See protocol_instructions for reviewer turn completion requirements."
        ),
        "schema": "tdp agent schema review-respond",
        "examples": examples,
        "discover": (
            f"tdp agent readme ({readme_sections}); "
            "tdp agent schema review-respond; "
            f"{examples}. Packaged reviewer skills are in agent_context.skills."
        ),
    }
    instructions.update(extra)
    return instructions


def build_reviewer_gate_continue_request(
    *,
    stage: str | None,
    turn: int,
    max_turns: int,
    review_type: str | None = None,
) -> dict[str, Any]:
    """Nudge payload when a reviewer turn ended without review respond."""

    stage_label = str(stage or "review").strip() or "review"
    remaining = max(0, max_turns - turn)
    return {
        "action": "continue",
        "phase": "review",
        "review_type": review_type,
        "stage": stage,
        "blocked_reason": (
            f"{REVIEWER_GATE_CONTINUE_BLOCKED_REASON} "
            f"(gate turn {turn}/{max_turns}; {remaining} retry "
            f"{'turn' if remaining == 1 else 'turns'} remaining)."
        ),
        "required_action": (
            "Write review-respond JSON under $TDP_AGENT_REQUESTS_DIR and run "
            "`tdp agent review respond --run <run-id> --request "
            "$TDP_AGENT_REQUESTS_DIR/review-respond-<stage>-r<rev>-a01.json`. "
            "Invoke `tdp` directly; do not wrap with `uv run`."
        ),
        "reviewer_gate": {
            "stage": stage_label,
            "agent_turn": turn,
            "max_agent_turns": max_turns,
            "turns_remaining": remaining,
        },
    }


def _issue_reviewer_capability(
    store: RunStore,
    run_id: str,
    provider: Provider,
    *,
    session_id: str,
    loop_id: str,
    phase: str,
) -> str:
    token = issue_session_capability(
        store,
        run_id,
        role="reviewer",
        phase=phase,
        session_id=session_id,
        session_kind="reviewer",
        loop_id=loop_id,
    )
    bind_provider_capability(provider, token, store=store, run_id=run_id)
    return token


def start_reviewer_review_session(
    provider: Provider,
    review_package: dict[str, Any],
    *,
    model: str | None = None,
) -> str:
    """Register a reviewer session whose first streamed turn uses *review_package*."""

    return provider.start_reviewer_session(review_package, model=model)


def bind_reviewer_session_capability(
    store: RunStore,
    run_id: str,
    provider: Provider,
    *,
    session_id: str,
    loop_id: str,
    phase: str,
) -> str:
    """Issue and bind a reviewer capability token for an already-persisted loop binding."""

    return _issue_reviewer_capability(
        store,
        run_id,
        provider,
        session_id=session_id,
        loop_id=loop_id,
        phase=phase,
    )


def deliver_reviewer_turn(
    provider: Provider,
    store: RunStore,
    run_id: str,
    *,
    session_id: str,
    loop_id: str,
    phase: str,
    request: dict[str, Any],
    model: str | None = None,
) -> str:
    """Bind reviewer capability and queue a follow-up turn on an existing session."""

    token = _issue_reviewer_capability(
        store,
        run_id,
        provider,
        session_id=session_id,
        loop_id=loop_id,
        phase=phase,
    )
    provider.send(session_id, request, model=model)
    return token


def begin_reviewer_review(
    provider: Provider,
    store: RunStore,
    run_id: str,
    *,
    loop_id: str,
    review_package: dict[str, Any],
    phase: str,
    model: str | None = None,
) -> tuple[str, str]:
    """Start a reviewer session, persist its loop binding, and bind capability."""

    from top_down_planning.orchestrator.session_events import (
        active_provider_session_ids,
        commit_reviewer_loop_provider_session,
        discard_if_unpublished,
    )

    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    preexisting = active_provider_session_ids(provider)
    session_id = start_reviewer_review_session(
        provider,
        review_package,
        model=model,
    )
    try:
        committed = commit_reviewer_loop_provider_session(
            store,
            run_id,
            loop.with_reviewer_provider_session_id(session_id),
            session_provider=provider,
        )
    except Exception:
        discard_if_unpublished(
            provider,
            store,
            run_id,
            session_id,
            preexisting_ids=preexisting,
            role="reviewer",
            loop_id=loop_id,
        )
        raise
    binding = committed.reviewer_binding
    bound_id = (
        str(binding.provider_session_id)
        if binding is not None and binding.provider_session_id
        else session_id
    )
    token = bind_reviewer_session_capability(
        store,
        run_id,
        provider,
        session_id=bound_id,
        loop_id=loop_id,
        phase=phase,
    )
    return bound_id, token


def resume_reviewer_session_with_package(
    provider: Provider,
    store: RunStore,
    run_id: str,
    *,
    session_id: str,
    loop_id: str,
    phase: str,
    review_package: dict[str, Any],
    model: str | None = None,
) -> str:
    """Deliver a full review package on an existing reviewer session (cold resume)."""

    return deliver_reviewer_turn(
        provider,
        store,
        run_id,
        session_id=session_id,
        loop_id=loop_id,
        phase=phase,
        request=review_package,
        model=model,
    )


def _reviewer_binding_requires_replacement(binding: SessionBinding | None) -> bool:
    if binding is None:
        return True
    if binding.state == "unbound":
        return True
    return binding.state == "starting" and is_transient_provider_session_id(
        binding.provider_session_id or ""
    )


def recheck_requires_reviewer_session_replacement(
    loop: ReviewLoop,
    *,
    target_revision: int,
    current_revision: int,
) -> bool:
    return (
        bool(loop.finding_actions)
        and current_revision > target_revision
        and _reviewer_binding_requires_replacement(loop.reviewer_binding)
    )


def resolve_reviewer_session_for_recheck(
    loop: ReviewLoop,
    *,
    target_revision: int,
    current_revision: int,
) -> str:
    """Return a bound reviewer session id for verification recheck.

    Raises ``ReviewerRecheckRequiresNewSession`` when planner revision work is
    recorded but the prior binding was lost before a durable id was bound.
    """

    session_id = reviewer_loop_provider_session_id(loop)
    if session_id is not None:
        return session_id

    if recheck_requires_reviewer_session_replacement(
        loop,
        target_revision=target_revision,
        current_revision=current_revision,
    ):
        raise ReviewerRecheckRequiresNewSession()

    raise ProviderRunError("reviewer session is missing for recheck")


__all__ = [
    "OWNER_FINDING_ACTION_COMPLETE_SIGNAL",
    "REVIEWER_DECISION_COMPLETE_SIGNAL",
    "ReviewerRecheckRequiresNewSession",
    "begin_reviewer_review",
    "bind_reviewer_session_capability",
    "build_reviewer_gate_continue_request",
    "build_reviewer_protocol_instructions",
    "build_reviewer_tool_instructions",
    "deliver_reviewer_turn",
    "recheck_requires_reviewer_session_replacement",
    "resolve_reviewer_session_for_recheck",
    "resume_reviewer_session_with_package",
    "reviewer_loop_binding",
    "reviewer_loop_provider_session_id",
    "start_reviewer_review_session",
]
