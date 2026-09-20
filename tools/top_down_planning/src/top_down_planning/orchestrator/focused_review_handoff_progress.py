"""Semantic progress tokens for focused-review internal continuation handoffs."""

from __future__ import annotations

from typing import Any

from top_down_planning.domain.reviews import (
    ReviewLoop,
    effective_owner_actions,
    focused_review_owner_actions_complete,
    needs_advisory_handoff,
)
from top_down_planning.orchestrator.provider_turns import (
    find_latest_active_focused_review_loop_id,
)
from top_down_planning.persistence.interface import RunStore
def resolve_focused_handoff_loop_id(
    store: RunStore,
    run_id: str,
    *,
    review_type: str,
) -> str | None:
    return find_latest_active_focused_review_loop_id(
        store,
        run_id,
        review_type=review_type,
    )


def _owner_actions_fingerprint(loop: ReviewLoop) -> tuple[tuple[str, str, int], ...]:
    actions = effective_owner_actions(
        loop.finding_actions,
        finding_set_id=loop.finding_set_id,
        owner_revision_cycle=int(loop.revision_cycles),
    )
    return tuple(
        sorted(
            (
                str(action.finding_id),
                str(action.action),
                int(action.owner_revision_cycle),
            )
            for action in actions.values()
        )
    )


def focused_review_semantic_progress_token(
    store: RunStore,
    run_id: str,
    loop_id: str | None,
) -> tuple[Any, ...]:
    """Durable review-centric progress; independent of run phase_action bookkeeping."""

    if not loop_id:
        return ("no-active-loop",)
    try:
        loop = ReviewLoop.from_dict(store.load_review(run_id, loop_id))
    except Exception:
        return ("missing-loop", loop_id)

    verification_decision = ""
    finding_status_fingerprint: tuple[tuple[str, str], ...] = ()
    if isinstance(loop.verification_result, dict):
        verification_decision = str(loop.verification_result.get("decision") or "")
        raw_results = loop.verification_result.get("finding_results") or []
        if isinstance(raw_results, list):
            finding_status_fingerprint = tuple(
                sorted(
                    (
                        str(entry.get("finding_id") or ""),
                        str(entry.get("disposition") or ""),
                    )
                    for entry in raw_results
                    if isinstance(entry, dict)
                )
            )
    review_incomplete_fingerprint: tuple[tuple[str, str], ...] = ()
    if isinstance(loop.review_incomplete, dict):
        review_incomplete_fingerprint = tuple(
            sorted((str(key), str(value)) for key, value in loop.review_incomplete.items())
        )

    artifact_revision: int | None = None
    if loop.type == "focused_output":
        production = store.load_production(run_id)
        artifact_revision = int(production.get("output_revision") or 0)
    elif loop.type == "focused_plan":
        artifact_revision = int(store.load_plan_model(run_id).revision)

    return (
        loop_id,
        str(loop.type or ""),
        str(loop.status or ""),
        str(loop.active_stage or ""),
        int(loop.revision_cycles),
        str(loop.finding_set_id or ""),
        _owner_actions_fingerprint(loop),
        bool(focused_review_owner_actions_complete(loop)),
        artifact_revision,
        verification_decision,
        bool(needs_advisory_handoff(loop)),
        review_incomplete_fingerprint,
        finding_status_fingerprint,
    )


__all__ = [
    "focused_review_semantic_progress_token",
    "resolve_focused_handoff_loop_id",
]
