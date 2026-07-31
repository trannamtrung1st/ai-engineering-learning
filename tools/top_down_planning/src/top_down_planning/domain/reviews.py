"""Review loop models and helpers (proposal §11)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

_ACTIVE_REVIEW_BLOCKING_STATUSES = frozenset({"changes_requested", "blocked"})
PLAN_REVIEW_TYPES = frozenset({"focused_plan", "whole_plan"})
OUTPUT_REVIEW_TYPES = frozenset({"focused_output", "whole_output"})

ReviewLoopType = Literal["whole_plan", "whole_output", "focused_plan", "focused_output"]
ReviewDecision = Literal["approved", "changes_requested", "blocked"]
FindingStatus = Literal["unresolved", "resolved", "superseded"]
FindingImportance = Literal["blocking", "advisory"]
ReviewLoopStatus = Literal["pending", "approved", "changes_requested", "blocked"]


@dataclass
class ReviewFinding:
    id: str
    importance: FindingImportance
    target_refs: list[str]
    issue: str
    required_change: str
    status: FindingStatus = "unresolved"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "importance": self.importance,
            "target_refs": list(self.target_refs),
            "issue": self.issue,
            "required_change": self.required_change,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ReviewFinding:
        return cls(
            id=str(payload["id"]),
            importance=str(payload.get("importance") or "advisory"),  # type: ignore[arg-type]
            target_refs=[str(ref) for ref in (payload.get("target_refs") or [])],
            issue=str(payload.get("issue") or ""),
            required_change=str(payload.get("required_change") or ""),
            status=str(payload.get("status") or "unresolved"),  # type: ignore[arg-type]
        )


@dataclass
class ReviewLoop:
    id: str
    type: ReviewLoopType
    reviewer_session_id: str | None
    target_revision: int
    scope: dict[str, Any]
    status: ReviewLoopStatus = "pending"
    findings: list[ReviewFinding] = field(default_factory=list)
    revision_cycles: int = 0
    approved_digests: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "reviewer_session_id": self.reviewer_session_id,
            "target_revision": self.target_revision,
            "scope": dict(self.scope),
            "status": self.status,
            "findings": [finding.to_dict() for finding in self.findings],
            "revision_cycles": self.revision_cycles,
        }
        if self.approved_digests is not None:
            payload["approved_digests"] = dict(self.approved_digests)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ReviewLoop:
        raw_type = payload.get("type")
        if raw_type is None or not str(raw_type).strip():
            raise ValueError("review loop type is required")

        findings = [
            ReviewFinding.from_dict(item)
            for item in (payload.get("findings") or [])
            if isinstance(item, dict)
        ]
        approved = payload.get("approved_digests")
        approved_digests = (
            {str(key): str(value) for key, value in approved.items()}
            if isinstance(approved, dict)
            else None
        )
        return cls(
            id=str(payload["id"]),
            type=str(raw_type).strip(),  # type: ignore[arg-type]
            reviewer_session_id=payload.get("reviewer_session_id"),
            target_revision=int(payload.get("target_revision") or 0),
            scope=dict(payload.get("scope") or {}),
            status=str(payload.get("status") or "pending"),  # type: ignore[arg-type]
            findings=findings,
            revision_cycles=int(payload.get("revision_cycles") or 0),
            approved_digests=approved_digests,
        )


def is_item_blocked_by_unresolved_review_findings(
    reviews: list[dict[str, Any]],
    item_id: str,
    *,
    review_types: frozenset[str] | None = None,
) -> bool:
    """Return whether unresolved blocking findings target ``item_id``."""

    allowed_types = review_types or PLAN_REVIEW_TYPES
    for payload in reviews:
        if payload.get("type") not in allowed_types:
            continue
        loop = ReviewLoop.from_dict(payload)
        if loop.status not in _ACTIVE_REVIEW_BLOCKING_STATUSES:
            continue
        for finding in loop.findings:
            if finding.importance != "blocking":
                continue
            if finding.status != "unresolved":
                continue
            if item_id in finding.target_refs:
                return True
    return False


def build_is_review_blocked_fn(
    reviews: list[dict[str, Any]] | None,
    *,
    review_types: frozenset[str] | None = None,
) -> Callable[[str], bool]:
    if not reviews:
        return lambda _item_id: False

    allowed_types = review_types or PLAN_REVIEW_TYPES

    def is_review_blocked(item_id: str) -> bool:
        return is_item_blocked_by_unresolved_review_findings(
            reviews,
            item_id,
            review_types=allowed_types,
        )

    return is_review_blocked


def item_referenced_in_reviews(reviews: list[dict[str, Any]], item_id: str) -> bool:
    """Return whether an item appears in any review scope or finding target."""

    for payload in reviews:
        loop = ReviewLoop.from_dict(payload)
        scope_items = {str(ref) for ref in (loop.scope.get("item_ids") or [])}
        if item_id in scope_items:
            return True
        for finding in loop.findings:
            if item_id in finding.target_refs:
                return True
    return False


def blocking_unresolved_finding_ids(findings: list[ReviewFinding]) -> list[str]:
    unresolved: list[str] = []
    for finding in findings:
        if finding.importance != "blocking":
            continue
        if finding.status != "unresolved":
            continue
        unresolved.append(finding.id)
    return unresolved


def needs_primary_revision_resume(
    loop: ReviewLoop,
    *,
    current_revision: int,
) -> bool:
    """True when a revision cycle started but the primary owner never ran."""

    if loop.revision_cycles <= 0 or loop.status != "pending":
        return False
    if current_revision > loop.target_revision:
        return False
    return bool(blocking_unresolved_finding_ids(loop.findings))


_WHOLE_SCOPE_KINDS = frozenset({"whole_plan", "whole_output"})


def validate_focused_scope(scope: Any, review_type: str) -> dict[str, Any]:
    """Validate a bounded focused-review scope (proposal §5.1)."""

    if not isinstance(scope, dict):
        raise ValueError("scope must be an object")

    kind = str(scope.get("kind") or "").strip()
    if kind in _WHOLE_SCOPE_KINDS:
        raise ValueError(
            f"focused review scope cannot use whole scope kind {kind!r}; "
            "request a mandatory whole review instead"
        )
    if kind != review_type:
        raise ValueError(
            f"scope.kind must be {review_type!r} for a {review_type} review request"
        )

    raw_item_ids = scope.get("item_ids")
    if not isinstance(raw_item_ids, list) or not raw_item_ids:
        raise ValueError("scope.item_ids must be a non-empty list")

    item_ids: list[str] = []
    for raw_id in raw_item_ids:
        item_id = str(raw_id).strip()
        if not item_id:
            raise ValueError("scope.item_ids entries must be non-empty strings")
        item_ids.append(item_id)

    return {"kind": review_type, "item_ids": item_ids}


def validate_findings_within_scope(
    findings: list[ReviewFinding],
    scope: dict[str, Any],
) -> None:
    allowed = {str(item_id) for item_id in (scope.get("item_ids") or [])}
    if not allowed:
        raise ValueError("focused review scope is missing item_ids")

    for finding in findings:
        for ref in finding.target_refs:
            if str(ref) not in allowed:
                raise ValueError(
                    f"finding {finding.id} target_ref {ref!r} is outside declared scope"
                )


def focused_loop_count(reviews: list[dict[str, Any]], review_type: str) -> int:
    return sum(1 for payload in reviews if payload.get("type") == review_type)


def find_overlapping_active_focused_loop(
    reviews: list[dict[str, Any]],
    review_type: str,
    scope_item_ids: list[str],
) -> str | None:
    """Return an active focused loop id whose scope overlaps the requested items."""

    target_items = {str(item_id) for item_id in scope_item_ids}
    for payload in reviews:
        if payload.get("type") != review_type:
            continue
        loop = ReviewLoop.from_dict(payload)
        if loop.status in {"approved", "blocked"}:
            continue
        scope_items = {str(item_id) for item_id in (loop.scope.get("item_ids") or [])}
        if scope_items.intersection(target_items):
            return loop.id
    return None


def blocking_focused_findings_for_items(
    reviews: list[dict[str, Any]],
    review_type: str,
    item_ids: list[str],
) -> list[str]:
    """Return blocking finding ids that block progress for overlapping scoped items."""

    target_items = {str(item_id) for item_id in item_ids}
    blocked: list[str] = []

    for payload in reviews:
        if payload.get("type") != review_type:
            continue
        loop = ReviewLoop.from_dict(payload)
        scope_items = {str(item_id) for item_id in (loop.scope.get("item_ids") or [])}
        if not scope_items.intersection(target_items):
            continue
        if loop.status not in {"changes_requested", "blocked"}:
            continue
        blocked.extend(blocking_unresolved_finding_ids(loop.findings))

    return blocked


def blocking_unresolved_finding_ids_from_payload(review: dict[str, Any]) -> list[str]:
    findings = [
        ReviewFinding.from_dict(item)
        for item in (review.get("findings") or [])
        if isinstance(item, dict)
    ]
    return blocking_unresolved_finding_ids(findings)


def find_active_review_loop(
    reviews: list[dict[str, Any]],
    loop_type: str,
) -> ReviewLoop | None:
    """Return the latest non-terminal review loop of ``loop_type``, if any."""

    for payload in reversed(reviews):
        if payload.get("type") != loop_type:
            continue
        loop = ReviewLoop.from_dict(payload)
        if loop.status in {"approved", "blocked"}:
            continue
        return loop
    return None


def whole_output_revision_target_ids(reviews: list[dict[str, Any]]) -> set[str]:
    """Plan item ids targeted by unresolved blocking findings in an active whole-output loop."""

    loop = find_active_review_loop(reviews, "whole_output")
    if loop is None:
        return set()

    targets: set[str] = set()
    for finding in loop.findings:
        if finding.importance != "blocking":
            continue
        if finding.status != "unresolved":
            continue
        targets.update(finding.target_refs)
    return targets


def focused_output_revision_target_ids(
    reviews: list[dict[str, Any]],
    *,
    loop_id: str | None = None,
) -> set[str]:
    """Plan item ids in scope for an active focused_output changes_requested loop."""

    loop: ReviewLoop | None = None
    if loop_id is not None:
        for payload in reviews:
            if payload.get("id") != loop_id:
                continue
            candidate = ReviewLoop.from_dict(payload)
            if candidate.type != "focused_output":
                return set()
            loop = candidate
            break
    else:
        loop = find_active_review_loop(reviews, "focused_output")

    if loop is None:
        return set()
    if loop.status != "changes_requested":
        return set()

    scope_items = {str(item_id) for item_id in (loop.scope.get("item_ids") or [])}
    targets: set[str] = set()
    for finding in loop.findings:
        if finding.importance != "blocking":
            continue
        if finding.status != "unresolved":
            continue
        targets.update(str(ref) for ref in finding.target_refs)
    if not targets:
        return scope_items
    return targets & scope_items if scope_items else targets


def find_whole_output_approval(
    reviews: list[dict[str, Any]],
    output_revision: int,
) -> dict[str, Any] | None:
    for payload in reversed(reviews):
        if payload.get("type") != "whole_output":
            continue
        if payload.get("status") != "approved":
            continue
        target_revision = payload.get("target_revision")
        if target_revision is None:
            continue
        if int(target_revision) != output_revision:
            continue
        return payload
    return None


def find_whole_plan_approval(
    reviews: list[dict[str, Any]],
    plan_revision: int,
) -> dict[str, Any] | None:
    for payload in reversed(reviews):
        if payload.get("type") != "whole_plan":
            continue
        if payload.get("status") != "approved":
            continue
        target_revision = payload.get("target_revision")
        if target_revision is None:
            continue
        if int(target_revision) != plan_revision:
            continue
        return payload
    return None


def parse_findings(raw_findings: Any) -> list[ReviewFinding]:
    if not isinstance(raw_findings, list):
        raise ValueError("findings must be a list")
    findings: list[ReviewFinding] = []
    for item in raw_findings:
        if not isinstance(item, dict):
            raise ValueError("each finding must be an object")
        findings.append(ReviewFinding.from_dict(item))
    return findings


def validate_decision(decision: str) -> ReviewDecision:
    normalized = str(decision).strip()
    if normalized not in {"approved", "changes_requested", "blocked"}:
        raise ValueError(
            "decision must be one of: approved, changes_requested, blocked"
        )
    return normalized  # type: ignore[return-value]


def apply_review_response(
    loop: ReviewLoop,
    *,
    target_revision: int,
    decision: ReviewDecision,
    findings: list[ReviewFinding],
    approved_digests: dict[str, str] | None = None,
) -> ReviewLoop:
    if loop.target_revision != target_revision:
        raise ValueError(
            f"target_revision {target_revision} does not match loop target "
            f"{loop.target_revision}"
        )

    if decision == "approved":
        unresolved = blocking_unresolved_finding_ids(findings)
        if unresolved:
            raise ValueError(
                "approved decision requires all blocking findings to be resolved "
                f"or superseded; unresolved: {', '.join(unresolved)}"
            )

    return ReviewLoop(
        id=loop.id,
        type=loop.type,
        reviewer_session_id=loop.reviewer_session_id,
        target_revision=loop.target_revision,
        scope=loop.scope,
        status=decision,
        findings=findings,
        revision_cycles=loop.revision_cycles,
        approved_digests=(
            approved_digests if approved_digests is not None else loop.approved_digests
        ),
    )
