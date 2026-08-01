"""Reviewer session allocation, capability binding, and turn delivery."""

from __future__ import annotations

from typing import Any

from top_down_planning.domain.plan_tree import PLAN_ROOT_REVIEWER_INSTRUCTION
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
                    "verified before production. Flag generic or meaningless risks, "
                    "requirements placed in risks instead of acceptance, risks "
                    "duplicated across levels, architecture suggestions in acceptance, "
                    "source references in scope.includes instead of source_refs, and "
                    "material risks implied by inputs but omitted from the plan."
                )
            )
            instructions.append(PLAN_ROOT_REVIEWER_INSTRUCTION)
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
    elif normalized_type == "focused_plan" and normalized != "finding_verification":
        instructions.append(
            (
                "Focused plan review: flag generic or misplaced risks, requirements "
                "placed in risks instead of acceptance, risks duplicated across "
                "levels, architecture suggestions in acceptance, source references "
                "in scope.includes instead of source_refs, and material risks "
                "implied by inputs but omitted from the scoped items."
            )
        )
        instructions.append(PLAN_ROOT_REVIEWER_INSTRUCTION)
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
    instructions.append(
        (
            "Write mutating request payloads only under $TDP_AGENT_REQUESTS_DIR. "
            "Do not create .tdp-* or .review-* dotfiles in the project workspace "
            "or harness folders. Do not modify orchestrator-owned run files."
        )
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
        "agent_requests_dir": "$TDP_AGENT_REQUESTS_DIR",
        "respond": (
            f"tdp agent review respond --run {run_id} "
            "--request $TDP_AGENT_REQUESTS_DIR/review-respond-<stage>-r<rev>-a01.json "
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
    bind_provider_capability(provider, token)
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
        commit_reviewer_loop_provider_session,
    )

    loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    session_id = start_reviewer_review_session(
        provider,
        review_package,
        model=model,
    )
    commit_reviewer_loop_provider_session(
        store,
        run_id,
        loop.with_reviewer_provider_session_id(session_id),
    )
    token = bind_reviewer_session_capability(
        store,
        run_id,
        provider,
        session_id=session_id,
        loop_id=loop_id,
        phase=phase,
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
    "REVIEWER_DECISION_MISSING",
    "ReviewerRecheckRequiresNewSession",
    "begin_reviewer_review",
    "bind_reviewer_session_capability",
    "build_reviewer_protocol_instructions",
    "build_reviewer_tool_instructions",
    "deliver_reviewer_turn",
    "recheck_requires_reviewer_session_replacement",
    "resolve_reviewer_session_for_recheck",
    "resume_reviewer_session_with_package",
    "reviewer_decision_missing_error",
    "reviewer_loop_binding",
    "reviewer_loop_provider_session_id",
    "start_reviewer_review_session",
]
