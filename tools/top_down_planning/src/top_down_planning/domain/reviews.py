"""Review loop models and helpers (proposal §11)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "reviewer_session_id": self.reviewer_session_id,
            "target_revision": self.target_revision,
            "scope": dict(self.scope),
            "status": self.status,
            "findings": [finding.to_dict() for finding in self.findings],
            "revision_cycles": self.revision_cycles,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ReviewLoop:
        findings = [
            ReviewFinding.from_dict(item)
            for item in (payload.get("findings") or [])
            if isinstance(item, dict)
        ]
        return cls(
            id=str(payload["id"]),
            type=str(payload.get("type") or "whole_plan"),  # type: ignore[arg-type]
            reviewer_session_id=payload.get("reviewer_session_id"),
            target_revision=int(payload.get("target_revision") or 0),
            scope=dict(payload.get("scope") or {}),
            status=str(payload.get("status") or "pending"),  # type: ignore[arg-type]
            findings=findings,
            revision_cycles=int(payload.get("revision_cycles") or 0),
        )


def blocking_unresolved_finding_ids(findings: list[ReviewFinding]) -> list[str]:
    unresolved: list[str] = []
    for finding in findings:
        if finding.importance != "blocking":
            continue
        if finding.status != "unresolved":
            continue
        unresolved.append(finding.id)
    return unresolved


def blocking_unresolved_finding_ids_from_payload(review: dict[str, Any]) -> list[str]:
    findings = [
        ReviewFinding.from_dict(item)
        for item in (review.get("findings") or [])
        if isinstance(item, dict)
    ]
    return blocking_unresolved_finding_ids(findings)


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
    )
