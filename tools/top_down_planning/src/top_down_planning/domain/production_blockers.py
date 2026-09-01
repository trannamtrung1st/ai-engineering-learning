"""Structured production blocker identity and stale-review reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

from top_down_planning.domain.reviews import (
    CLEAR_APPROVAL_STATUSES,
    ReviewLoop,
    is_terminal_review_loop,
)

BLOCKER_KIND_EXTERNAL = "external"
BLOCKER_KIND_FOCUSED_REVIEW_WAIT = "focused_review_wait"
BLOCKER_STATUS_ACTIVE = "active"
BLOCKER_STATUS_RESOLVED = "resolved"
BLOCKER_STATUS_SUPERSEDED = "superseded"

BlockerDisposition = Literal["none", "active_terminal", "active_wait", "resolved"]

_REVIEW_WAIT_KINDS = frozenset({BLOCKER_KIND_FOCUSED_REVIEW_WAIT})
_INACTIVE_STATUSES = frozenset({BLOCKER_STATUS_RESOLVED, BLOCKER_STATUS_SUPERSEDED})


@dataclass(frozen=True)
class BlockerEvaluation:
    """Outcome of evaluating a persisted production blocker against review state."""

    disposition: BlockerDisposition
    report: dict[str, Any] | None = None
    matching_loop_id: str | None = None
    reason: str | None = None


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def loop_bound_digest(loop: ReviewLoop) -> str | None:
    """Return the artifact digest bound to a focused-review success, if recorded."""

    verification = loop.verification_result or {}
    digest = _optional_text(verification.get("target_digest"))
    if digest:
        return digest
    approved = loop.approved_digests or {}
    for key in ("output", "plan"):
        digest = _optional_text(approved.get(key))
        if digest:
            return digest
    return None


def normalize_blocker_report(raw: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Return a structured blocker, inferring kind/status for historical records."""

    if not isinstance(raw, Mapping):
        return None
    evidence = _optional_text(raw.get("evidence"))
    if not evidence:
        return None

    kind = _optional_text(raw.get("kind"))
    review_loop_id = _optional_text(raw.get("review_loop_id"))
    if kind is None:
        kind = (
            BLOCKER_KIND_FOCUSED_REVIEW_WAIT
            if review_loop_id
            else BLOCKER_KIND_EXTERNAL
        )
    status = _optional_text(raw.get("status")) or BLOCKER_STATUS_ACTIVE
    affected_refs = raw.get("affected_refs")
    if not isinstance(affected_refs, list):
        affected_refs = []

    report: dict[str, Any] = {
        "kind": kind,
        "status": status,
        "evidence": evidence,
        "affected_refs": [str(item) for item in affected_refs],
        "summary": str(raw.get("summary") or ""),
    }
    if review_loop_id:
        report["review_loop_id"] = review_loop_id
    package_item_id = _optional_text(raw.get("package_item_id"))
    if package_item_id:
        report["package_item_id"] = package_item_id
    target_revision = _optional_int(raw.get("target_revision"))
    if target_revision is not None:
        report["target_revision"] = target_revision
    target_digest = _optional_text(raw.get("target_digest"))
    if target_digest:
        report["target_digest"] = target_digest
    plan_revision = _optional_int(raw.get("plan_revision"))
    if plan_revision is not None:
        report["plan_revision"] = plan_revision
    output_revision = _optional_int(raw.get("output_revision"))
    if output_revision is not None:
        report["output_revision"] = output_revision
    reported_at = _optional_int(raw.get("reported_at_output_revision"))
    if reported_at is None:
        reported_at = output_revision
    if reported_at is not None:
        report["reported_at_output_revision"] = reported_at
    resolved_by = _optional_text(raw.get("resolved_by"))
    if resolved_by:
        report["resolved_by"] = resolved_by
    return report


def is_review_bound_blocker(report: Mapping[str, Any] | None) -> bool:
    normalized = normalize_blocker_report(report)
    if normalized is None:
        return False
    return (
        normalized.get("kind") in _REVIEW_WAIT_KINDS
        and bool(normalized.get("review_loop_id"))
    )


def is_active_blocker(report: Mapping[str, Any] | None) -> bool:
    normalized = normalize_blocker_report(report)
    if normalized is None:
        return False
    return str(normalized.get("status") or "") not in _INACTIVE_STATUSES


def review_satisfies_blocker(report: Mapping[str, Any], loop: ReviewLoop) -> bool:
    """True when ``loop`` canonically satisfies a review-bound blocker identity."""

    normalized = normalize_blocker_report(report)
    if normalized is None or not is_review_bound_blocker(normalized):
        return False
    if str(normalized.get("status") or "") in _INACTIVE_STATUSES:
        return False
    if loop.id != str(normalized.get("review_loop_id") or ""):
        return False
    if loop.status not in CLEAR_APPROVAL_STATUSES:
        return False
    bound_revision = _optional_int(normalized.get("target_revision"))
    if bound_revision is not None and int(loop.target_revision) != bound_revision:
        return False
    bound_digest = _optional_text(normalized.get("target_digest"))
    loop_digest = loop_bound_digest(loop)
    if bound_digest and loop_digest and bound_digest != loop_digest:
        return False
    return True


def resolve_blocker_report(
    report: Mapping[str, Any],
    *,
    resolved_by: str,
) -> dict[str, Any]:
    """Mark a blocker resolved by the satisfying review loop."""

    normalized = normalize_blocker_report(report)
    if normalized is None:
        raise ValueError("blocker report is missing")
    updated = dict(normalized)
    updated["status"] = BLOCKER_STATUS_RESOLVED
    updated["resolved_by"] = str(resolved_by)
    return updated


def evaluate_blocker_report(
    report: Mapping[str, Any] | None,
    reviews: list[ReviewLoop],
) -> BlockerEvaluation:
    """Classify a persisted blocker against current review-loop state."""

    normalized = normalize_blocker_report(report)
    if normalized is None:
        return BlockerEvaluation(disposition="none")
    if str(normalized.get("status") or "") in _INACTIVE_STATUSES:
        return BlockerEvaluation(disposition="none", report=normalized)
    if str(normalized.get("kind") or "") in _REVIEW_WAIT_KINDS:
        if not is_review_bound_blocker(normalized):
            return BlockerEvaluation(
                disposition="active_wait",
                report=normalized,
                reason="focused review wait is missing review_loop_id",
            )
        loop_id = str(normalized.get("review_loop_id") or "")
        matching = next((loop for loop in reviews if loop.id == loop_id), None)
        if matching is not None and review_satisfies_blocker(normalized, matching):
            return BlockerEvaluation(
                disposition="resolved",
                report=resolve_blocker_report(normalized, resolved_by=matching.id),
                matching_loop_id=matching.id,
                reason=(
                    "stale review-bound production blocker; "
                    "blocking condition is already satisfied"
                ),
            )
        return BlockerEvaluation(
            disposition="active_wait",
            report=normalized,
            matching_loop_id=loop_id or None,
            reason="focused review wait is still active",
        )
    return BlockerEvaluation(
        disposition="active_terminal",
        report=normalized,
        reason="external production blocker is still active",
    )


def bind_open_focused_review_to_blocker(
    report: Mapping[str, Any],
    loops: list[ReviewLoop],
    *,
    output_revision: int,
    output_digest: str | None = None,
) -> dict[str, Any]:
    """Attach causal focused-review identity when exactly one open loop exists."""

    normalized = normalize_blocker_report(report)
    if normalized is None:
        raise ValueError("blocker report is missing")
    if str(normalized.get("kind") or "") == BLOCKER_KIND_EXTERNAL:
        raw_kind = _optional_text(report.get("kind"))
        if raw_kind == BLOCKER_KIND_EXTERNAL:
            return normalized
    if _optional_text(normalized.get("review_loop_id")):
        return normalized
    open_focused = [
        loop
        for loop in loops
        if loop.type == "focused_output"
        and loop.status != "blocked"
        and not is_terminal_review_loop(loop)
    ]
    if len(open_focused) != 1:
        return normalized
    loop = open_focused[0]
    bound = dict(normalized)
    bound["kind"] = BLOCKER_KIND_FOCUSED_REVIEW_WAIT
    bound["status"] = BLOCKER_STATUS_ACTIVE
    bound["review_loop_id"] = loop.id
    bound["target_revision"] = int(loop.target_revision)
    digest = loop_bound_digest(loop) or _optional_text(output_digest)
    if digest:
        bound["target_digest"] = digest
    bound["reported_at_output_revision"] = int(output_revision)
    return bound
