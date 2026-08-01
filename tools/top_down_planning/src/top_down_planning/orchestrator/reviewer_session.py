"""Reviewer session allocation, capability binding, and turn delivery."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.domain.session_bindings import is_transient_provider_session_id
from top_down_planning.domain.session_bindings import (
    SessionBinding,
    resumable_binding_provider_session_id,
)
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
    review_type: str | None = None,
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
    normalized_type = str(review_type or "").strip() or None
    normalized = str(stage or "").strip() or None
    if normalized_type in {"whole_plan", "whole_output"} and normalized != "finding_verification":
        if normalized_type == "whole_plan":
            instructions.append(
                (
                    "Primary gate focus: plan correctness and internal consistency. "
                    "Flag contradictions between outcomes, acceptance criteria, "
                    "dependencies, and titles; impossible or cyclic dependencies; "
                    "overlapping executable scope; and claims that cannot be "
                    "verified before production."
                )
            )
        else:
            instructions.append(
                (
                    "Primary gate focus: output correctness and consistency. "
                    "Verify deliverables satisfy the approved plan contracts, "
                    "evidence supports claimed dispositions, and outputs do not "
                    "contradict each other, the plan acceptance criteria, or the "
                    "completion claim."
                )
            )
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
    elif normalized == "scope_review":
        instructions.extend(
            [
                (
                    "Stage: scope_review (fresh scope review). This is a "
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
                    "Respond with stage scope_review using finding_set_id, "
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
            "tdp agent example review-respond-scope"
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


def _reviewer_binding_requires_replacement(binding: SessionBinding | None) -> bool:
    if binding is None:
        return True
    if binding.state == "unbound":
        return True
    return binding.state == "starting" and is_transient_provider_session_id(
        binding.provider_session_id or ""
    )


def allocate_reviewer_binding_for_recheck(
    provider: Provider,
    store: RunStore,
    run_id: str,
    loop: ReviewLoop,
    *,
    phase: str,
    append_event: Callable[..., None],
    model: str | None = None,
    review_type: str | None = None,
    scope: dict[str, Any] | None = None,
) -> str:
    """Allocate a replacement reviewer session after the prior binding was lost."""

    from top_down_planning.orchestrator.session_events import (
        commit_reviewer_loop_provider_session,
        emit_reviewer_session_started,
    )

    session_id = allocate_reviewer_session(
        provider,
        run_id=run_id,
        loop_id=loop.id,
        model=model,
    )
    started_fields: dict[str, Any] = {"loop_id": loop.id}
    if review_type is not None:
        started_fields["review_type"] = review_type
    if scope is not None:
        started_fields["scope"] = scope
    emit_reviewer_session_started(
        append_event,
        provider,
        phase=phase,
        session_id=session_id,
        **started_fields,
    )
    updated = loop.with_reviewer_session_released().with_reviewer_provider_session_id(
        session_id
    )
    commit_reviewer_loop_provider_session(store, run_id, updated)
    return session_id


def resolve_reviewer_session_for_recheck(
    provider: Provider,
    store: RunStore,
    run_id: str,
    loop: ReviewLoop,
    *,
    target_revision: int,
    current_revision: int,
    phase: str,
    append_event: Callable[..., None],
    model: str | None = None,
    review_type: str | None = None,
    scope: dict[str, Any] | None = None,
) -> str:
    """Return a bound reviewer session for verification recheck.

    Recheck resumes the same bound reviewer session when available. When resume
    session policy cleared a lost transient binding after planner revision work
    is already recorded, allocate a replacement reviewer session.
    """

    session_id = reviewer_loop_provider_session_id(loop)
    if session_id is not None:
        return session_id

    if (
        loop.finding_actions
        and current_revision > target_revision
        and _reviewer_binding_requires_replacement(loop.reviewer_binding)
    ):
        return allocate_reviewer_binding_for_recheck(
            provider,
            store,
            run_id,
            loop,
            phase=phase,
            append_event=append_event,
            model=model,
            review_type=review_type,
            scope=scope,
        )

    raise ProviderRunError("reviewer session is missing for recheck")


__all__ = [
    "REVIEWER_DECISION_MISSING",
    "allocate_reviewer_binding_for_recheck",
    "allocate_reviewer_session",
    "begin_reviewer_review",
    "build_reviewer_allocation_request",
    "build_reviewer_protocol_instructions",
    "build_reviewer_tool_instructions",
    "deliver_reviewer_turn",
    "resolve_reviewer_session_for_recheck",
    "resume_reviewer_session_with_package",
    "reviewer_decision_missing_error",
    "reviewer_loop_binding",
    "reviewer_loop_provider_session_id",
]
