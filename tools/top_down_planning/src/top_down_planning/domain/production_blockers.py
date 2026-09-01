"""Structured production blocker identity and stale-review reconciliation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

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
_REVIEW_WAIT_EVIDENCE_RE = re.compile(
    r"waiting\s+(?:for|on)\s+(?:a\s+)?focused\s+review|focused\s+review",
    re.IGNORECASE,
)
DIAGNOSTIC_AMBIGUOUS_LEGACY_BLOCKER = "ambiguous_legacy_blocker"


@dataclass(frozen=True)
class BlockerEvaluation:
    """Outcome of evaluating a persisted production blocker against review state."""

    disposition: BlockerDisposition
    report: dict[str, Any] | None = None
    matching_loop_id: str | None = None
    reason: str | None = None
    diagnostic_code: str | None = None


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
    if bound_digest:
        loop_digest = loop_bound_digest(loop)
        if loop_digest != bound_digest:
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


def _scope_item_ids(scope: Any) -> set[str]:
    if not isinstance(scope, Mapping):
        return set()
    raw = scope.get("item_ids")
    if not isinstance(raw, list):
        return set()
    return {str(item) for item in raw if str(item)}


def _looks_like_review_wait_evidence(report: Mapping[str, Any]) -> bool:
    text = f"{report.get('evidence') or ''} {report.get('summary') or ''}"
    return bool(_REVIEW_WAIT_EVIDENCE_RE.search(text))


def _is_legacy_untyped(raw: Mapping[str, Any]) -> bool:
    return (
        _optional_text(raw.get("kind")) is None
        and _optional_text(raw.get("review_loop_id")) is None
    )


def _event_loop_id(event: Mapping[str, Any]) -> str:
    return str(event.get("loop_id") or "").strip()


def _is_focused_output_request(event: Mapping[str, Any]) -> bool:
    if event.get("type") != "focused_review_requested":
        return False
    review_type = str(event.get("review_type") or "")
    return not review_type or review_type == "focused_output"


def _is_focused_loop_terminal_event(event: Mapping[str, Any]) -> bool:
    event_type = str(event.get("type") or "")
    if event_type == "focused_review_approved":
        return True
    if event_type != "review_responded":
        return False
    decision = str(event.get("decision") or "").strip()
    return decision in {"approved", "blocked", "verified"}


def _last_blocked_index(events: Sequence[Mapping[str, Any]]) -> int | None:
    last_blocked_index: int | None = None
    for index, event in enumerate(events):
        if event.get("type") == "production_blocked_reported":
            last_blocked_index = index
    return last_blocked_index


def _request_overlaps_blocker(
    event: Mapping[str, Any],
    reviews: list[ReviewLoop],
    report: Mapping[str, Any],
) -> bool:
    loop_by_id = {loop.id: loop for loop in reviews}
    affected = {str(item) for item in (report.get("affected_refs") or []) if str(item)}
    loop_id = _event_loop_id(event)
    item_ids = _scope_item_ids(event.get("scope"))
    loop = loop_by_id.get(loop_id)
    if not item_ids and loop is not None:
        item_ids = _scope_item_ids(loop.scope)
    if affected and item_ids and affected.isdisjoint(item_ids):
        return False
    if affected and not item_ids:
        return False
    return True


def _overlapping_request_loop_ids(
    events: Sequence[Mapping[str, Any]],
    reviews: list[ReviewLoop],
    report: Mapping[str, Any],
) -> list[str]:
    last_blocked_index = _last_blocked_index(events)
    if last_blocked_index is None:
        return []

    candidates: list[str] = []
    seen: set[str] = set()
    for event in events[:last_blocked_index]:
        if not _is_focused_output_request(event):
            continue
        loop_id = _event_loop_id(event)
        if not loop_id or loop_id in seen:
            continue
        if not _request_overlaps_blocker(event, reviews, report):
            continue
        seen.add(loop_id)
        candidates.append(loop_id)
    return candidates


def _loop_was_unresolved_at_blocked(
    events: Sequence[Mapping[str, Any]],
    loop_id: str,
    blocked_index: int,
) -> bool:
    requested = False
    for event in events[:blocked_index]:
        if _event_loop_id(event) != loop_id:
            continue
        if _is_focused_output_request(event):
            requested = True
        if _is_focused_loop_terminal_event(event):
            return False
    return requested


def _approval_follows_blocked(
    events: Sequence[Mapping[str, Any]],
    loop_id: str,
    blocked_index: int,
) -> bool:
    for event in events[blocked_index + 1 :]:
        if _event_loop_id(event) != loop_id:
            continue
        if event.get("type") == "focused_review_approved":
            return True
    return False


def _unresolved_overlapping_loop_ids(
    events: Sequence[Mapping[str, Any]],
    reviews: list[ReviewLoop],
    report: Mapping[str, Any],
) -> list[str]:
    blocked_index = _last_blocked_index(events)
    if blocked_index is None:
        return []
    return [
        loop_id
        for loop_id in _overlapping_request_loop_ids(events, reviews, report)
        if _loop_was_unresolved_at_blocked(events, loop_id, blocked_index)
    ]


def _bind_report_to_loop(
    report: Mapping[str, Any],
    loop: ReviewLoop,
    *,
    output_revision: int | None = None,
    output_digest: str | None = None,
) -> dict[str, Any]:
    bound = dict(report)
    bound["kind"] = BLOCKER_KIND_FOCUSED_REVIEW_WAIT
    bound["status"] = BLOCKER_STATUS_ACTIVE
    bound["review_loop_id"] = loop.id
    bound["target_revision"] = int(loop.target_revision)
    digest = loop_bound_digest(loop) or _optional_text(output_digest)
    if digest:
        bound["target_digest"] = digest
    if output_revision is not None:
        bound["reported_at_output_revision"] = int(output_revision)
    return bound


def _evaluate_review_bound(
    normalized: dict[str, Any],
    reviews: list[ReviewLoop],
) -> BlockerEvaluation:
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
    reason = "focused review wait is still active"
    if (
        matching is not None
        and _optional_text(normalized.get("target_digest"))
        and loop_bound_digest(matching) is None
        and matching.status in CLEAR_APPROVAL_STATUSES
    ):
        reason = (
            "review-bound production blocker cannot be satisfied; "
            "matching review is missing review digest"
        )
    return BlockerEvaluation(
        disposition="active_wait",
        report=normalized,
        matching_loop_id=loop_id or None,
        reason=reason,
    )


def evaluate_blocker_report(
    report: Mapping[str, Any] | None,
    reviews: list[ReviewLoop],
    events: Sequence[Mapping[str, Any]] | None = None,
) -> BlockerEvaluation:
    """Classify a persisted blocker against current review-loop state."""

    if not isinstance(report, Mapping):
        return BlockerEvaluation(disposition="none")
    normalized = normalize_blocker_report(report)
    if normalized is None:
        return BlockerEvaluation(disposition="none")
    if str(normalized.get("status") or "") in _INACTIVE_STATUSES:
        return BlockerEvaluation(disposition="none", report=normalized)
    if str(normalized.get("kind") or "") in _REVIEW_WAIT_KINDS:
        return _evaluate_review_bound(normalized, reviews)

    history = [event for event in (events or []) if isinstance(event, Mapping)]
    if _is_legacy_untyped(report) and history:
        overlapping = _overlapping_request_loop_ids(history, reviews, normalized)
        unresolved = _unresolved_overlapping_loop_ids(history, reviews, normalized)
        blocked_index = _last_blocked_index(history)
        unique_loop = None
        if len(unresolved) == 1:
            unique_loop = next(
                (loop for loop in reviews if loop.id == unresolved[0]),
                None,
            )
        if (
            unique_loop is not None
            and blocked_index is not None
            and _looks_like_review_wait_evidence(normalized)
        ):
            bound = _bind_report_to_loop(normalized, unique_loop)
            if _approval_follows_blocked(history, unique_loop.id, blocked_index):
                return _evaluate_review_bound(bound, reviews)
            if unique_loop.status in CLEAR_APPROVAL_STATUSES or is_terminal_review_loop(
                unique_loop
            ):
                return BlockerEvaluation(
                    disposition="active_terminal",
                    report=normalized,
                    matching_loop_id=unique_loop.id,
                    reason=(
                        "legacy production blocker coincides with focused review "
                        "history but causal binding is ambiguous"
                    ),
                    diagnostic_code=DIAGNOSTIC_AMBIGUOUS_LEGACY_BLOCKER,
                )
            return _evaluate_review_bound(bound, reviews)
        if overlapping:
            return BlockerEvaluation(
                disposition="active_terminal",
                report=normalized,
                matching_loop_id=overlapping[0] if len(overlapping) == 1 else None,
                reason=(
                    "legacy production blocker coincides with focused review "
                    "history but causal binding is ambiguous"
                ),
                diagnostic_code=DIAGNOSTIC_AMBIGUOUS_LEGACY_BLOCKER,
            )
    return BlockerEvaluation(
        disposition="active_terminal",
        report=normalized,
        reason="external production blocker is still active",
    )


def stale_blocked_run_is_repairable(
    *,
    run: Mapping[str, Any],
    production: Mapping[str, Any] | None,
    reviews: list[ReviewLoop],
    events: Sequence[Mapping[str, Any]] | None = None,
) -> BlockerEvaluation | None:
    """Return the resolved evaluation when a completed blocked run is a stale review wait."""

    if str(run.get("status") or "") != "completed":
        return None
    if str(run.get("outcome") or "") != "blocked":
        return None
    if str(run.get("phase") or "") != "production":
        return None
    if not isinstance(production, Mapping):
        return None
    report = production.get("blocker_report")
    if not isinstance(report, Mapping):
        return None
    if str(report.get("status") or "") in _INACTIVE_STATUSES:
        return None
    evaluation = evaluate_blocker_report(report, reviews, events=events)
    if evaluation.disposition != "resolved":
        return None
    return evaluation


def bind_open_focused_review_to_blocker(
    report: Mapping[str, Any],
    loops: list[ReviewLoop],
    *,
    output_revision: int,
    output_digest: str | None = None,
) -> dict[str, Any]:
    """Attach causal focused-review identity from explicit kind or loop id only."""

    normalized = normalize_blocker_report(report)
    if normalized is None:
        raise ValueError("blocker report is missing")
    raw_kind = _optional_text(report.get("kind"))
    raw_loop_id = _optional_text(report.get("review_loop_id"))
    if raw_kind == BLOCKER_KIND_EXTERNAL:
        return normalized
    if raw_loop_id:
        matching = next((loop for loop in loops if loop.id == raw_loop_id), None)
        if matching is None:
            bound = dict(normalized)
            bound["kind"] = BLOCKER_KIND_FOCUSED_REVIEW_WAIT
            bound["review_loop_id"] = raw_loop_id
            bound["reported_at_output_revision"] = int(output_revision)
            return bound
        return _bind_report_to_loop(
            normalized,
            matching,
            output_revision=output_revision,
            output_digest=output_digest,
        )
    if raw_kind != BLOCKER_KIND_FOCUSED_REVIEW_WAIT:
        untyped = dict(normalized)
        untyped.pop("review_loop_id", None)
        untyped.pop("kind", None)
        return untyped
    open_focused = [
        loop
        for loop in loops
        if loop.type == "focused_output"
        and loop.status != "blocked"
        and not is_terminal_review_loop(loop)
    ]
    affected = set(normalized.get("affected_refs") or [])
    overlapping = [
        loop
        for loop in open_focused
        if not affected or not _scope_item_ids(loop.scope).isdisjoint(affected)
    ]
    candidates = overlapping if len(overlapping) == 1 else open_focused
    if len(candidates) != 1:
        return normalized
    return _bind_report_to_loop(
        normalized,
        candidates[0],
        output_revision=output_revision,
        output_digest=output_digest,
    )
