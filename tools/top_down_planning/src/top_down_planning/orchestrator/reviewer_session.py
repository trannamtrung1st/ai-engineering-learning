"""Reviewer session allocation, capability binding, and turn delivery."""

from __future__ import annotations

from typing import Any

from top_down_planning.orchestrator.capability import (
    bind_provider_capability,
    issue_session_capability,
)
from top_down_planning.orchestrator.errors import ProviderRunError
from top_down_planning.persistence.interface import RunStore
from core_tools.provider import Provider

REVIEWER_DECISION_MISSING = (
    "reviewer turn completed without a decision; "
    "ensure `tdp agent review respond` succeeded "
    "(mutating commands require TDP_CAPABILITY_TOKEN from the active reviewer "
    "session — invoke `tdp` directly, not `uv run tdp`)"
)

_FORBIDDEN_STAGE_LABELS = (
    "full review",
    "confirmation review",
    "holistic review",
    "spot check",
)


def build_reviewer_allocation_request(*, run_id: str, loop_id: str) -> dict[str, Any]:
    """Minimal allocation payload that only establishes a provider session id."""

    return {
        "action": "reviewer_session_allocate",
        "run_id": run_id,
        "loop_id": loop_id,
    }


def build_reviewer_protocol_instructions(
    *,
    stage: str | None = None,
) -> list[str]:
    """Provider-agnostic reviewer behavior instructions for review packages."""

    instructions = [
        (
            "You are the TDP reviewer. Inspect the delivered review package and "
            "submit a structured decision through tdp agent review respond in "
            "tool_instructions."
        ),
        (
            "Do not use host planning modes or planning-only tools. The "
            "orchestrator persists review outcomes only from review respond "
            "payloads."
        ),
        (
            "Assistant prose or host plan artifacts alone do not advance the "
            "run. Invoke `tdp` directly for mutating commands; do not wrap "
            "with `uv run`."
        ),
    ]
    normalized = str(stage or "").strip() or None
    if normalized == "finding_verification":
        instructions.extend(
            [
                (
                    "Stage: finding_verification (Verify revisions). Verify the "
                    "disposition of prior findings and direct revision side "
                    "effects. Do not perform a broad discovery pass; the next "
                    "fresh scope review handles newly discovered unrelated issues."
                ),
                (
                    "Respond with stage finding_verification. Prefer decision "
                    "verified|needs_revision|blocked and finding_results "
                    "dispositions "
                    "resolved|partially_resolved|unresolved|superseded|invalid."
                ),
            ]
        )
    elif normalized == "scope_blocker_review":
        instructions.extend(
            [
                (
                    "Stage: scope_blocker_review (fresh scope review). This is a "
                    "fresh discovery pass: do not anchor on prior finding lists "
                    "or revision discussion. Review the complete current scope "
                    "and report every material issue you find."
                ),
                (
                    "Classify each finding by severity and category using the "
                    "provided review_policy definitions. Report every material "
                    "issue you discover; do not omit lower-severity issues "
                    "because they may not force revision. Do not report purely "
                    "subjective preferences unless they are clearly marked as "
                    "suggestions. Do not raise out-of-scope issues. Do not call "
                    "this a full, confirmation, holistic, or spot-check review."
                ),
                (
                    "Respond with stage scope_blocker_review using finding_set_id, "
                    "reported_findings, review_completed, target_digest, and "
                    "summary. Echo finding_set_id unchanged. Do not decide whether "
                    "policy forces revision; the service derives that. Finding "
                    "closure alone must not approve the artifact."
                ),
            ]
        )
    else:
        instructions.extend(
            [
                (
                    "Review the complete current scope and report every material "
                    "issue you find. Classify each finding by severity and "
                    "category using the provided review_policy definitions. "
                    "Report every material issue you discover; do not omit "
                    "lower-severity issues because they may not force revision. "
                    "Do not report purely subjective preferences unless they are "
                    "clearly marked as suggestions. Do not raise out-of-scope "
                    "issues."
                ),
                (
                    "Respond with finding_set_id, reported_findings, "
                    "review_completed, and summary. Echo finding_set_id unchanged. "
                    "Do not decide whether policy forces revision; the service "
                    "derives lifecycle outcomes from findings. Set "
                    "review_completed false only when inputs prevent a reliable "
                    "review. For mandatory whole_* reviews, clear discovery still "
                    "requires a later fresh scope review before run approval."
                ),
            ]
        )
    return instructions


def build_reviewer_tool_instructions(
    run_id: str,
    **extra: str,
) -> dict[str, str]:
    """CLI instructions embedded in reviewer review packages."""

    instructions = {
        "authorization": (
            "Mutating commands require the session capability token exported "
            "as TDP_CAPABILITY_TOKEN on the provider subprocess that runs your "
            "review turn."
        ),
        "respond": (
            f"tdp agent review respond --run {run_id} --request <file> "
            "(invoke `tdp` directly; do not wrap with `uv run`)"
        ),
        "schema": "tdp agent schema review-respond",
        "examples": (
            "tdp agent example review-respond-verification ; "
            "tdp agent example review-respond-blocker"
        ),
    }
    instructions.update(extra)
    return instructions


def reviewer_decision_missing_error() -> ProviderRunError:
    return ProviderRunError(REVIEWER_DECISION_MISSING)


def allocate_reviewer_session(
    provider: Provider,
    *,
    run_id: str,
    loop_id: str,
    model: str | None = None,
) -> str:
    """Register a reviewer session id without delivering the review package."""

    return provider.start_reviewer_session(
        build_reviewer_allocation_request(run_id=run_id, loop_id=loop_id),
        model=model,
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
    """Issue a reviewer capability token, bind it, then queue a provider turn."""

    token = issue_session_capability(
        store,
        run_id,
        role="reviewer",
        phase=phase,
        session_id=session_id,
        session_kind="reviewer",
        loop_id=loop_id,
    )
    bind_provider_capability(provider, token)
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
    """Allocate a reviewer session, then deliver the bounded review package."""

    session_id = allocate_reviewer_session(
        provider,
        run_id=run_id,
        loop_id=loop_id,
        model=model,
    )
    token = deliver_reviewer_turn(
        provider,
        store,
        run_id,
        session_id=session_id,
        loop_id=loop_id,
        phase=phase,
        request=review_package,
    )
    return session_id, token


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


__all__ = [
    "REVIEWER_DECISION_MISSING",
    "allocate_reviewer_session",
    "begin_reviewer_review",
    "build_reviewer_allocation_request",
    "build_reviewer_protocol_instructions",
    "build_reviewer_tool_instructions",
    "deliver_reviewer_turn",
    "resume_reviewer_session_with_package",
    "reviewer_decision_missing_error",
]
