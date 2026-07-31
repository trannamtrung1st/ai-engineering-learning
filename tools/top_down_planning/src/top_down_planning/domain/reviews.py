"""Review loop models and helpers (proposal §11; mandatory review gates)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from top_down_planning.domain.review_policy import (
    FindingCategory,
    ReviewSeverity,
    severity_at_or_above,
    validate_finding_category,
    validate_review_severity,
)

# Persisted review-record schema version (separate from run-record schema_version).
CURRENT_REVIEW_SCHEMA_VERSION = 1

_ACTIVE_REVIEW_BLOCKING_STATUSES = frozenset(
    {"changes_requested", "needs_revision", "blockers_found"}
)
PLAN_REVIEW_TYPES = frozenset({"focused_plan", "whole_plan"})
OUTPUT_REVIEW_TYPES = frozenset({"focused_output", "whole_output"})

ReviewLoopType = Literal["whole_plan", "whole_output", "focused_plan", "focused_output"]
ReviewDecision = Literal["approved", "changes_requested", "blocked"]
ReviewLoopStatus = Literal[
    "pending",
    "advisory_pending",
    "approved",
    "changes_requested",
    "blocked",
    "verified",
    "needs_revision",
    "approve",
    "blockers_found",
    "review_incomplete",
]
MandatoryStageDecision = Literal[
    "approved",
    "changes_requested",
    "blocked",
    "verified",
    "needs_revision",
    "approve",
    "blockers_found",
    "review_incomplete",
]
REVISION_REQUESTED_STATUSES = frozenset(
    {"changes_requested", "needs_revision", "blockers_found"}
)
CLEAR_APPROVAL_STATUSES = frozenset({"approved", "verified", "approve"})

# Persisted finding status on ReviewFinding; open statuses block approval.
FindingStatus = Literal[
    "unresolved",
    "partially_resolved",
    "resolved",
    "superseded",
    "invalid",
]
# Stage-1 verification disposition (proposal Finding disposition).
FindingDisposition = Literal[
    "resolved",
    "partially_resolved",
    "unresolved",
    "superseded",
    "invalid",
]
FindingImportance = Literal["blocking", "advisory"]

# Recommended Naming / Result Contracts
# Canonical stage for fresh mandatory discovery is ``scope_review``; legacy
# ``scope_blocker_review`` remains readable.
ReviewStage = Literal[
    "finding_verification",
    "scope_review",
    "scope_blocker_review",  # legacy alias
]
VerificationDecision = Literal["verified", "needs_revision", "blocked"]
# Canonical scope-review decisions are approved|changes_requested|blocked;
# approve|blockers_found remain readable legacy aliases.
ScopeReviewDecision = Literal[
    "approved",
    "changes_requested",
    "blocked",
    "approve",
    "blockers_found",
]
BlockerReviewDecision = ScopeReviewDecision  # legacy alias name

SCOPE_REVIEW_STAGE = "scope_review"
LEGACY_SCOPE_REVIEW_STAGE = "scope_blocker_review"
SCOPE_REVIEW_STAGES = frozenset({SCOPE_REVIEW_STAGE, LEGACY_SCOPE_REVIEW_STAGE})

# Suggested State Model for mandatory whole_* loops
MandatoryReviewLifecycleStatus = Literal[
    "review_pending",
    "findings_open",
    "revision_in_progress",
    "verification_pending",
    "findings_closed",
    "scope_review_pending",
    "blocker_review_pending",  # legacy alias
    "approved",
    "blocked",
    "limit_reached",
    "review_incomplete",
]

FINDING_DISPOSITIONS: frozenset[str] = frozenset(
    {
        "resolved",
        "partially_resolved",
        "unresolved",
        "superseded",
        "invalid",
    }
)
OPEN_FINDING_DISPOSITIONS: frozenset[str] = frozenset(
    {"unresolved", "partially_resolved"}
)
CLOSED_FINDING_DISPOSITIONS: frozenset[str] = frozenset(
    {"resolved", "superseded", "invalid"}
)

FindingOwnerAction = Literal["fix", "defer", "accept_as_is", "challenge"]
FindingActionActorRole = Literal["planner", "producer"]
ChallengeProposedDisposition = Literal["invalid", "superseded"]

FINDING_OWNER_ACTIONS: frozenset[str] = frozenset(
    {"fix", "defer", "accept_as_is", "challenge"}
)
CHALLENGE_PROPOSED_DISPOSITIONS: frozenset[str] = frozenset({"invalid", "superseded"})
ACTIONS_REQUIRING_RATIONALE: frozenset[str] = frozenset(
    {"defer", "accept_as_is", "challenge"}
)
QUALIFYING_OPTIONAL_OWNER_ACTIONS: frozenset[str] = frozenset(
    {"defer", "accept_as_is"}
)
REQUIRED_FINDING_OWNER_ACTIONS: frozenset[str] = frozenset({"fix", "challenge"})
OPTIONAL_FINDING_OWNER_ACTIONS: frozenset[str] = frozenset(
    {"fix", "defer", "accept_as_is", "challenge"}
)

MANDATORY_REVIEW_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "review_pending": frozenset(
        {
            "findings_open",
            "scope_review_pending",
            "blocker_review_pending",
            "review_incomplete",
        }
    ),
    "findings_open": frozenset(
        {"revision_in_progress", "blocked", "review_incomplete"}
    ),
    "revision_in_progress": frozenset({"verification_pending", "limit_reached"}),
    "verification_pending": frozenset(
        {
            "findings_closed",
            "revision_in_progress",
            "blocked",
            "limit_reached",
            "review_incomplete",
        }
    ),
    "findings_closed": frozenset(
        {"scope_review_pending", "blocker_review_pending", "limit_reached"}
    ),
    "scope_review_pending": frozenset(
        {"approved", "findings_open", "blocked", "limit_reached", "review_incomplete"}
    ),
    "blocker_review_pending": frozenset(
        {"approved", "findings_open", "blocked", "limit_reached", "review_incomplete"}
    ),
    "approved": frozenset(),
    "blocked": frozenset(),
    "limit_reached": frozenset(),
    "review_incomplete": frozenset(
        {
            "review_pending",
            "findings_open",
            "scope_review_pending",
            "blocker_review_pending",
            "verification_pending",
        }
    ),
}


def canonicalize_review_stage(stage: str | None) -> str | None:
    """Map legacy scope_blocker_review onto canonical scope_review."""

    if stage is None:
        return None
    normalized = str(stage).strip()
    if not normalized:
        return None
    if normalized == LEGACY_SCOPE_REVIEW_STAGE:
        return SCOPE_REVIEW_STAGE
    return normalized


def is_scope_review_stage_name(stage: str | None) -> bool:
    return str(stage or "").strip() in SCOPE_REVIEW_STAGES


def canonicalize_lifecycle_status(status: str | None) -> str | None:
    if status is None:
        return None
    normalized = str(status).strip()
    if not normalized:
        return None
    if normalized == "blocker_review_pending":
        return "scope_review_pending"
    return normalized


def canonicalize_scope_review_decision(decision: str) -> str:
    normalized = str(decision).strip()
    if normalized == "approve":
        return "approved"
    if normalized == "blockers_found":
        return "changes_requested"
    return normalized


def normalize_exhausted_budget(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if normalized == "blocker_review":
        return "scope_review"
    return normalized or None


@dataclass
class ReviewFinding:
    id: str
    severity: ReviewSeverity
    category: FindingCategory
    target_refs: list[str]
    issue: str
    recommended_change: str
    status: FindingStatus = "unresolved"
    evidence: list[str] = field(default_factory=list)
    reopens_finding_id: str | None = None

    @property
    def importance(self) -> FindingImportance:
        """Legacy derived importance until threshold-aware helpers replace callers."""

        return "blocking" if self.severity == "blocker" else "advisory"

    @property
    def required_change(self) -> str:
        """Legacy alias for recommended_change until callers migrate."""

        return self.recommended_change

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "severity": self.severity,
            "category": self.category,
            "target_refs": list(self.target_refs),
            "issue": self.issue,
            "evidence": list(self.evidence),
            "recommended_change": self.recommended_change,
            "status": self.status,
        }
        if self.reopens_finding_id is not None:
            payload["reopens_finding_id"] = self.reopens_finding_id
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ReviewFinding:
        severity = _severity_from_payload(payload)
        category_raw = payload.get("category")
        if category_raw is None or not str(category_raw).strip():
            category: FindingCategory = "other"
        else:
            category = validate_finding_category(str(category_raw))

        if "recommended_change" in payload:
            recommended_change = str(payload.get("recommended_change") or "")
        else:
            recommended_change = str(payload.get("required_change") or "")

        reopens_raw = payload.get("reopens_finding_id")
        reopens_finding_id = (
            str(reopens_raw).strip()
            if reopens_raw is not None and str(reopens_raw).strip()
            else None
        )
        evidence_raw = payload.get("evidence") or []
        if not isinstance(evidence_raw, list):
            raise ValueError("finding evidence must be a list")
        evidence = [str(item) for item in evidence_raw]

        return cls(
            id=str(payload["id"]),
            severity=severity,
            category=category,
            target_refs=[str(ref) for ref in (payload.get("target_refs") or [])],
            issue=str(payload.get("issue") or ""),
            recommended_change=recommended_change,
            status=str(payload.get("status") or "unresolved"),  # type: ignore[arg-type]
            evidence=evidence,
            reopens_finding_id=reopens_finding_id,
        )


def _severity_from_payload(payload: Mapping[str, Any]) -> ReviewSeverity:
    if payload.get("severity") is not None and str(payload.get("severity")).strip():
        return validate_review_severity(str(payload["severity"]))
    importance = payload.get("importance")
    if importance is None or not str(importance).strip():
        raise ValueError("finding requires severity (or legacy importance)")
    normalized = str(importance).strip()
    if normalized == "blocking":
        return "blocker"
    if normalized == "advisory":
        return "minor"
    raise ValueError(
        "legacy finding importance must be one of: blocking, advisory"
    )


@dataclass
class FindingAction:
    """Primary-agent owner action recorded on a review loop."""

    finding_id: str
    action: FindingOwnerAction
    actor_role: FindingActionActorRole
    artifact_revision: int
    finding_set_id: str
    rationale: str | None = None
    proposed_disposition: ChallengeProposedDisposition | None = None
    superseded_by_finding_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "finding_id": self.finding_id,
            "action": self.action,
            "actor_role": self.actor_role,
            "artifact_revision": self.artifact_revision,
            "finding_set_id": self.finding_set_id,
        }
        if self.rationale is not None:
            payload["rationale"] = self.rationale
        if self.proposed_disposition is not None:
            payload["proposed_disposition"] = self.proposed_disposition
        if self.superseded_by_finding_id is not None:
            payload["superseded_by_finding_id"] = self.superseded_by_finding_id
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> FindingAction:
        return parse_finding_action(payload)


def validate_finding_owner_action(action: str) -> FindingOwnerAction:
    normalized = str(action).strip()
    if normalized not in FINDING_OWNER_ACTIONS:
        raise ValueError(
            "finding action must be one of: "
            + ", ".join(sorted(FINDING_OWNER_ACTIONS))
        )
    return normalized  # type: ignore[return-value]


def parse_finding_action(payload: Mapping[str, Any]) -> FindingAction:
    """Parse and validate a finding_actions record."""

    if not isinstance(payload, Mapping):
        raise ValueError("finding_actions entry must be an object")
    finding_id = str(payload.get("finding_id") or "").strip()
    if not finding_id:
        raise ValueError("finding_actions entry requires finding_id")
    action = validate_finding_owner_action(str(payload.get("action") or ""))
    actor_role = str(payload.get("actor_role") or "").strip()
    if actor_role not in {"planner", "producer"}:
        raise ValueError("finding_actions actor_role must be planner or producer")
    finding_set_id = str(payload.get("finding_set_id") or "").strip()
    if not finding_set_id:
        raise ValueError("finding_actions entry requires finding_set_id")
    try:
        artifact_revision = int(payload.get("artifact_revision"))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "finding_actions entry requires integer artifact_revision"
        ) from exc

    rationale_raw = payload.get("rationale")
    rationale = (
        str(rationale_raw).strip()
        if rationale_raw is not None and str(rationale_raw).strip()
        else None
    )
    if action in ACTIONS_REQUIRING_RATIONALE and not rationale:
        raise ValueError(f"finding action {action!r} requires rationale")

    proposed_raw = payload.get("proposed_disposition")
    proposed_disposition: ChallengeProposedDisposition | None = None
    if proposed_raw is not None and str(proposed_raw).strip():
        proposed = str(proposed_raw).strip()
        if proposed not in CHALLENGE_PROPOSED_DISPOSITIONS:
            raise ValueError(
                "proposed_disposition must be one of: invalid, superseded"
            )
        proposed_disposition = proposed  # type: ignore[assignment]

    superseded_raw = payload.get("superseded_by_finding_id")
    superseded_by_finding_id = (
        str(superseded_raw).strip()
        if superseded_raw is not None and str(superseded_raw).strip()
        else None
    )

    if action == "challenge":
        if proposed_disposition is None:
            raise ValueError("challenge requires proposed_disposition")
        if proposed_disposition == "superseded" and not superseded_by_finding_id:
            raise ValueError(
                "challenge with proposed_disposition superseded requires "
                "superseded_by_finding_id"
            )
    elif proposed_disposition is not None or superseded_by_finding_id is not None:
        raise ValueError(
            "proposed_disposition and superseded_by_finding_id are only valid "
            "for challenge actions"
        )

    return FindingAction(
        finding_id=finding_id,
        action=action,
        actor_role=actor_role,  # type: ignore[arg-type]
        artifact_revision=artifact_revision,
        finding_set_id=finding_set_id,
        rationale=rationale,
        proposed_disposition=proposed_disposition,
        superseded_by_finding_id=superseded_by_finding_id,
    )


def validate_reopens_finding_id(
    finding: ReviewFinding,
    existing_findings: Sequence[ReviewFinding],
) -> None:
    """Validate reopen lineage against findings already in the loop."""

    if finding.reopens_finding_id is None:
        return
    if finding.reopens_finding_id == finding.id:
        raise ValueError("reopens_finding_id must not reference the finding itself")
    by_id = {item.id: item for item in existing_findings}
    referenced = by_id.get(finding.reopens_finding_id)
    if referenced is None:
        raise ValueError(
            f"reopens_finding_id {finding.reopens_finding_id!r} must reference "
            "a finding in the same loop"
        )
    if referenced.status not in CLOSED_FINDING_DISPOSITIONS:
        raise ValueError(
            f"reopens_finding_id {finding.reopens_finding_id!r} must reference a "
            "closed finding (resolved, superseded, or invalid)"
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
    # Mandatory review loop fields (optional; focused loops leave unset).
    lifecycle_status: MandatoryReviewLifecycleStatus | None = None
    active_stage: ReviewStage | None = None
    finding_set_id: str | None = None
    blocker_review_rounds: int = 0
    verification_result: dict[str, Any] | None = None
    blocker_review_result: dict[str, Any] | None = None
    exhausted_budget: ExhaustedReviewBudget | None = None
    # Severity-threshold review fields (proposal review-record model).
    review_schema_version: int = CURRENT_REVIEW_SCHEMA_VERSION
    revise_at: ReviewSeverity | None = None
    finding_actions: list[FindingAction] = field(default_factory=list)
    review_incomplete: dict[str, Any] | None = None
    advisory_handoffs_completed: list[str] = field(default_factory=list)

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
            "review_schema_version": self.review_schema_version,
            "finding_actions": [action.to_dict() for action in self.finding_actions],
            "review_incomplete": (
                dict(self.review_incomplete)
                if self.review_incomplete is not None
                else None
            ),
            "advisory_handoffs_completed": list(self.advisory_handoffs_completed),
        }
        if self.revise_at is not None:
            payload["revise_at"] = self.revise_at
        if self.approved_digests is not None:
            payload["approved_digests"] = dict(self.approved_digests)
        if self.lifecycle_status is not None:
            payload["lifecycle_status"] = (
                canonicalize_lifecycle_status(self.lifecycle_status)
                or self.lifecycle_status
            )
        if self.active_stage is not None:
            payload["active_stage"] = (
                canonicalize_review_stage(self.active_stage) or self.active_stage
            )
        if self.finding_set_id is not None:
            payload["finding_set_id"] = self.finding_set_id
        rounds = int(self.blocker_review_rounds)
        if rounds:
            payload["scope_review_rounds"] = rounds
        if self.verification_result is not None:
            payload["verification_result"] = dict(self.verification_result)
        if self.blocker_review_result is not None:
            payload["scope_review_result"] = dict(self.blocker_review_result)
        if self.exhausted_budget is not None:
            payload["exhausted_budget"] = normalize_exhausted_budget(self.exhausted_budget)
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
        lifecycle_raw = payload.get("lifecycle_status")
        lifecycle_status = canonicalize_lifecycle_status(
            str(lifecycle_raw).strip()
            if lifecycle_raw is not None and str(lifecycle_raw).strip()
            else None
        )
        stage_raw = payload.get("active_stage")
        active_stage = canonicalize_review_stage(
            str(stage_raw).strip()
            if stage_raw is not None and str(stage_raw).strip()
            else None
        )
        finding_set_raw = payload.get("finding_set_id")
        finding_set_id = (
            str(finding_set_raw).strip()
            if finding_set_raw is not None and str(finding_set_raw).strip()
            else None
        )
        verification_raw = payload.get("verification_result")
        verification_result = (
            dict(verification_raw) if isinstance(verification_raw, dict) else None
        )
        blocker_raw = payload.get("scope_review_result")
        if not isinstance(blocker_raw, dict):
            blocker_raw = payload.get("blocker_review_result")
        blocker_review_result = (
            dict(blocker_raw) if isinstance(blocker_raw, dict) else None
        )
        exhausted_raw = payload.get("exhausted_budget")
        exhausted_budget = normalize_exhausted_budget(
            str(exhausted_raw).strip()
            if exhausted_raw is not None and str(exhausted_raw).strip()
            else None
        )
        rounds_raw = payload.get("scope_review_rounds")
        if rounds_raw is None:
            rounds_raw = payload.get("blocker_review_rounds")
        blocker_review_rounds = int(rounds_raw or 0)
        schema_raw = payload.get("review_schema_version")
        if schema_raw is None:
            review_schema_version = CURRENT_REVIEW_SCHEMA_VERSION
        else:
            try:
                review_schema_version = int(schema_raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "review_schema_version must be an integer"
                ) from exc

        revise_raw = payload.get("revise_at")
        revise_at: ReviewSeverity | None = None
        if revise_raw is not None and str(revise_raw).strip():
            revise_at = validate_review_severity(str(revise_raw))

        finding_actions = [
            parse_finding_action(item)
            for item in (payload.get("finding_actions") or [])
            if isinstance(item, dict)
        ]
        incomplete_raw = payload.get("review_incomplete")
        review_incomplete = (
            dict(incomplete_raw) if isinstance(incomplete_raw, dict) else None
        )
        advisory_handoffs_completed = [
            str(item).strip()
            for item in (payload.get("advisory_handoffs_completed") or [])
            if str(item).strip()
        ]

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
            lifecycle_status=lifecycle_status,  # type: ignore[arg-type]
            active_stage=active_stage,  # type: ignore[arg-type]
            finding_set_id=finding_set_id,
            blocker_review_rounds=blocker_review_rounds,
            verification_result=verification_result,
            blocker_review_result=blocker_review_result,
            exhausted_budget=exhausted_budget,  # type: ignore[arg-type]
            review_schema_version=review_schema_version,
            revise_at=revise_at,
            finding_actions=finding_actions,
            review_incomplete=review_incomplete,
            advisory_handoffs_completed=advisory_handoffs_completed,
        )


def with_loop_revise_at(
    loop: ReviewLoop,
    revise_at: ReviewSeverity,
) -> ReviewLoop:
    """Persist effective revise_at at loop creation; reject later mutation."""

    if loop.revise_at is not None and loop.revise_at != revise_at:
        raise ValueError(
            f"revise_at is immutable after loop creation "
            f"(persisted {loop.revise_at!r}, refused {revise_at!r})"
        )
    if loop.revise_at == revise_at:
        return loop
    return replace(loop, revise_at=revise_at)


def is_mandatory_review_loop(loop: ReviewLoop) -> bool:
    return loop.type in {"whole_plan", "whole_output"}


def is_terminal_review_loop(loop: ReviewLoop) -> bool:
    if loop.status == "blocked":
        return True
    if is_mandatory_review_loop(loop):
        return loop.lifecycle_status == "approved"
    return loop.status == "approved"


def is_review_respond_closed(loop: ReviewLoop) -> bool:
    """True when ``review respond`` must reject further reviewer decisions."""

    if is_terminal_review_loop(loop):
        return True
    if is_mandatory_review_loop(loop) and loop.status == "approve":
        # Legacy mandatory-gate closed status.
        return True
    if (
        is_mandatory_review_loop(loop)
        and loop.status == "approved"
        and loop.lifecycle_status == "approved"
        and is_scope_review_stage_name(loop.active_stage)
    ):
        return True
    blocker = loop.blocker_review_result
    if is_mandatory_review_loop(loop) and isinstance(blocker, dict):
        decision = canonicalize_scope_review_decision(
            str(blocker.get("decision") or "")
        )
        if decision == "approved" and is_scope_review_stage_name(
            str(blocker.get("stage") or loop.active_stage or "")
        ):
            return True
    return False


def is_revision_requested_status(status: str) -> bool:
    return str(status).strip() in REVISION_REQUESTED_STATUSES


def is_item_blocked_by_unresolved_review_findings(
    reviews: list[dict[str, Any]],
    item_id: str,
    *,
    review_types: frozenset[str] | None = None,
) -> bool:
    """Return whether unresolved required findings target ``item_id``."""

    allowed_types = review_types or PLAN_REVIEW_TYPES
    for payload in reviews:
        if payload.get("type") not in allowed_types:
            continue
        loop = ReviewLoop.from_dict(payload)
        if loop.status not in _ACTIVE_REVIEW_BLOCKING_STATUSES:
            continue
        threshold = loop_revise_at(loop)
        for finding in required_open_findings(loop.findings, threshold):
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


def is_open_finding_status(status: str) -> bool:
    """True when a finding still requires verification/revision attention."""

    return str(status).strip() in OPEN_FINDING_DISPOSITIONS


def loop_revise_at(loop: ReviewLoop) -> ReviewSeverity:
    """Return the loop's persisted revise_at, or blocker for legacy loops."""

    if loop.revise_at is not None:
        return loop.revise_at
    return "blocker"


def open_findings(findings: Sequence[ReviewFinding]) -> list[ReviewFinding]:
    return [
        finding
        for finding in findings
        if is_open_finding_status(finding.status)
    ]


def required_open_findings(
    findings: Sequence[ReviewFinding],
    threshold: ReviewSeverity,
) -> list[ReviewFinding]:
    """Open findings at or above the effective revision threshold."""

    return [
        finding
        for finding in open_findings(findings)
        if severity_at_or_above(finding.severity, threshold)
    ]


def optional_open_findings(
    findings: Sequence[ReviewFinding],
    threshold: ReviewSeverity,
) -> list[ReviewFinding]:
    """Open findings below the effective revision threshold."""

    return [
        finding
        for finding in open_findings(findings)
        if not severity_at_or_above(finding.severity, threshold)
    ]


def required_open_finding_ids(
    findings: Sequence[ReviewFinding],
    threshold: ReviewSeverity,
) -> list[str]:
    return [finding.id for finding in required_open_findings(findings, threshold)]


def optional_open_finding_ids(
    findings: Sequence[ReviewFinding],
    threshold: ReviewSeverity,
) -> list[str]:
    return [finding.id for finding in optional_open_findings(findings, threshold)]


def open_optional_findings_without_owner_action(
    findings: Sequence[ReviewFinding],
    finding_actions: Sequence[FindingAction],
    threshold: ReviewSeverity,
    *,
    finding_set_id: str | None = None,
) -> list[ReviewFinding]:
    """Optional open findings lacking a qualifying defer/accept_as_is action."""

    acknowledged = {
        action.finding_id
        for action in finding_actions
        if action.action in QUALIFYING_OPTIONAL_OWNER_ACTIONS
        and (
            finding_set_id is None
            or action.finding_set_id == finding_set_id
        )
    }
    return [
        finding
        for finding in optional_open_findings(findings, threshold)
        if finding.id not in acknowledged
    ]


def unacknowledged_optional_finding_ids(
    findings: Sequence[ReviewFinding],
    finding_actions: Sequence[FindingAction],
    threshold: ReviewSeverity,
    *,
    finding_set_id: str | None = None,
) -> list[str]:
    return [
        finding.id
        for finding in open_optional_findings_without_owner_action(
            findings,
            finding_actions,
            threshold,
            finding_set_id=finding_set_id,
        )
    ]


def findings_permit_approval(
    findings: Sequence[ReviewFinding],
    finding_actions: Sequence[FindingAction],
    threshold: ReviewSeverity,
    *,
    finding_set_id: str | None = None,
) -> bool:
    """True when required findings are clear and optionals have owner actions."""

    if required_open_findings(findings, threshold):
        return False
    if open_optional_findings_without_owner_action(
        findings,
        finding_actions,
        threshold,
        finding_set_id=finding_set_id,
    ):
        return False
    return True


def assert_owner_action_allowed_for_finding(
    finding: ReviewFinding,
    action: str,
    threshold: ReviewSeverity,
) -> FindingOwnerAction:
    """Validate owner action against required/optional policy for a finding."""

    normalized = validate_finding_owner_action(action)
    is_required = severity_at_or_above(finding.severity, threshold)
    if is_required:
        if normalized not in REQUIRED_FINDING_OWNER_ACTIONS:
            raise ValueError(
                f"required finding {finding.id!r} cannot use action "
                f"{normalized!r}; allowed: fix, challenge"
            )
    elif normalized not in OPTIONAL_FINDING_OWNER_ACTIONS:
        raise ValueError(
            f"optional finding {finding.id!r} cannot use action {normalized!r}"
        )
    return normalized


def policy_observability_fields(
    findings: Sequence[ReviewFinding],
    finding_actions: Sequence[FindingAction],
    threshold: ReviewSeverity,
    *,
    finding_set_id: str | None = None,
) -> dict[str, Any]:
    """Derived threshold/requirement state for review responses and events."""

    required_ids = required_open_finding_ids(findings, threshold)
    optional_ids = optional_open_finding_ids(findings, threshold)
    unacked_ids = unacknowledged_optional_finding_ids(
        findings,
        finding_actions,
        threshold,
        finding_set_id=finding_set_id,
    )
    return {
        "revise_at": threshold,
        "finding_count": len(findings),
        "required_open_finding_count": len(required_ids),
        "optional_open_finding_count": len(optional_ids),
        "required_open_finding_ids": required_ids,
        "optional_open_finding_ids": optional_ids,
        "unacknowledged_optional_finding_ids": unacked_ids,
    }


def blocking_unresolved_finding_ids(
    findings: list[ReviewFinding],
    *,
    revise_at: ReviewSeverity | None = None,
) -> list[str]:
    """Return open finding ids at or above ``revise_at`` (default: blocker)."""

    threshold: ReviewSeverity = revise_at if revise_at is not None else "blocker"
    return required_open_finding_ids(findings, threshold)


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
    return bool(
        blocking_unresolved_finding_ids(
            loop.findings,
            revise_at=loop_revise_at(loop),
        )
    )


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
        blocked.extend(
            blocking_unresolved_finding_ids(
                loop.findings,
                revise_at=loop_revise_at(loop),
            )
        )

    return blocked


def blocking_unresolved_finding_ids_from_payload(review: dict[str, Any]) -> list[str]:
    findings = [
        ReviewFinding.from_dict(item)
        for item in (review.get("findings") or [])
        if isinstance(item, dict)
    ]
    revise_raw = review.get("revise_at")
    revise_at: ReviewSeverity | None = None
    if revise_raw is not None and str(revise_raw).strip():
        revise_at = validate_review_severity(str(revise_raw))
    return blocking_unresolved_finding_ids(findings, revise_at=revise_at)


def find_active_review_loop(
    reviews: list[dict[str, Any]],
    loop_type: str,
) -> ReviewLoop | None:
    """Return the latest non-terminal review loop of ``loop_type``, if any."""

    for payload in reversed(reviews):
        if payload.get("type") != loop_type:
            continue
        loop = ReviewLoop.from_dict(payload)
        if is_terminal_review_loop(loop):
            continue
        return loop
    return None


def whole_output_revision_target_ids(reviews: list[dict[str, Any]]) -> set[str]:
    """Plan item ids targeted by unresolved required findings in an active whole-output loop."""

    loop = find_active_review_loop(reviews, "whole_output")
    if loop is None:
        return set()

    targets: set[str] = set()
    for finding in required_open_findings(loop.findings, loop_revise_at(loop)):
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
    required = required_open_findings(loop.findings, loop_revise_at(loop))
    if not required:
        return set()
    targets: set[str] = set()
    for finding in required:
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
        if str(payload.get("status") or "").strip() not in {"approve", "approved"}:
            continue
        target_revision = payload.get("target_revision")
        if target_revision is None:
            continue
        if int(output_revision) != int(target_revision):
            continue
        if not is_mandatory_gate_approval_record(payload):
            continue
        return payload
    return None


def is_mandatory_gate_approval_record(payload: Mapping[str, Any]) -> bool:
    """True when a persisted mandatory loop completed the mandatory approval gate."""

    status = str(payload.get("status") or "").strip()
    if status not in {"approve", "approved"}:
        return False
    if payload.get("lifecycle_status") != "approved":
        return False
    if not is_scope_review_stage_name(str(payload.get("active_stage") or "")):
        return False
    blocker_raw = payload.get("scope_review_result")
    if not isinstance(blocker_raw, dict):
        blocker_raw = payload.get("blocker_review_result")
    if not isinstance(blocker_raw, dict):
        return False
    if not is_scope_review_stage_name(str(blocker_raw.get("stage") or "")):
        return False
    decision = canonicalize_scope_review_decision(
        str(blocker_raw.get("decision") or "")
    )
    if decision != "approved":
        return False
    reported = blocker_raw.get("reported_findings")
    if reported is None:
        reported = blocker_raw.get("blocking_findings")
    if reported:
        return False
    if not str(blocker_raw.get("target_digest") or "").strip():
        return False
    return True


def find_whole_plan_approval(
    reviews: list[dict[str, Any]],
    plan_revision: int,
) -> dict[str, Any] | None:
    for payload in reversed(reviews):
        if payload.get("type") != "whole_plan":
            continue
        if str(payload.get("status") or "").strip() not in {"approve", "approved"}:
            continue
        target_revision = payload.get("target_revision")
        if target_revision is None:
            continue
        if int(target_revision) != plan_revision:
            continue
        if not is_mandatory_gate_approval_record(payload):
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


def is_discovery_respond_payload(request: Mapping[str, Any]) -> bool:
    """True when the respond payload uses the unified discovery contract."""

    return "reported_findings" in request or "review_completed" in request


def next_finding_set_id(loop: ReviewLoop) -> str:
    """Allocate the next orchestrator-owned finding_set_id for ``loop``."""

    base = loop.id
    existing = loop.finding_set_id or ""
    suffix = 1
    if existing.startswith(f"{base}-fs-"):
        try:
            suffix = int(existing.rsplit("-", 1)[-1]) + 1
        except ValueError:
            suffix = 1
    return f"{base}-fs-{suffix:02d}"


def allocate_discovery_finding_set_id(loop: ReviewLoop) -> tuple[ReviewLoop, str]:
    """Ensure a discovery finding_set_id is allocated on the loop.

    Reuses the existing id when the loop is marked review_incomplete so retries
    echo the same identifier. Otherwise allocates a new id for a fresh discovery
    pass.
    """

    if loop.review_incomplete is not None and loop.finding_set_id:
        return loop, loop.finding_set_id
    if loop.finding_set_id and loop.active_stage == "finding_verification":
        return loop, loop.finding_set_id
    finding_set_id = next_finding_set_id(loop)
    return replace(loop, finding_set_id=finding_set_id), finding_set_id


def validate_finding_set_id_echo(
    loop: ReviewLoop,
    request: Mapping[str, Any],
) -> str:
    """Require the reviewer to echo the orchestrator-allocated finding_set_id."""

    expected = str(loop.finding_set_id or "").strip()
    if not expected:
        raise ValueError(
            "review loop is missing orchestrator-allocated finding_set_id"
        )
    echoed = str(request.get("finding_set_id") or "").strip()
    if not echoed:
        raise ValueError("discovery respond requires finding_set_id")
    if echoed != expected:
        raise ValueError(
            f"finding_set_id mismatch: expected {expected!r}, got {echoed!r}"
        )
    return echoed


def parse_reported_finding(payload: Mapping[str, Any]) -> ReviewFinding:
    """Parse one discovery finding; severity and category are required."""

    if payload.get("severity") is None or not str(payload.get("severity")).strip():
        raise ValueError("discovery finding requires severity")
    if payload.get("category") is None or not str(payload.get("category")).strip():
        raise ValueError("discovery finding requires category")
    finding = ReviewFinding.from_dict(dict(payload))
    if finding.status != "unresolved":
        raise ValueError(
            f"discovery finding {finding.id!r} must have status unresolved"
        )
    return finding


def parse_reported_findings(request: Mapping[str, Any]) -> list[ReviewFinding]:
    """Parse ``reported_findings`` from a discovery respond payload."""

    if "reported_findings" not in request:
        raise ValueError("discovery respond requires reported_findings")
    raw = request.get("reported_findings")
    if not isinstance(raw, list):
        raise ValueError("reported_findings must be a list")
    findings: list[ReviewFinding] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("each reported_findings entry must be an object")
        finding = parse_reported_finding(item)
        if finding.id in seen:
            raise ValueError(
                f"duplicate finding id {finding.id!r} in reported_findings"
            )
        seen.add(finding.id)
        findings.append(finding)
    return findings


def assert_reported_finding_ids_unused(
    loop: ReviewLoop,
    reported: Sequence[ReviewFinding],
) -> None:
    """Reject discovery payloads that reuse an existing loop finding id."""

    existing_ids = {finding.id for finding in loop.findings}
    for finding in reported:
        if finding.id in existing_ids:
            raise ValueError(
                f"discovery finding id {finding.id!r} already exists in the loop; "
                "rediscovery must use a new id (optionally with reopens_finding_id)"
            )
        validate_reopens_finding_id(finding, loop.findings)


def parse_discovery_respond_findings(
    loop: ReviewLoop,
    request: Mapping[str, Any],
) -> list[ReviewFinding]:
    """Validate discovery contract fields and return reported findings."""

    validate_finding_set_id_echo(loop, request)
    if "review_completed" not in request:
        raise ValueError("discovery respond requires review_completed")
    completed = request.get("review_completed")
    if not isinstance(completed, bool):
        raise ValueError("review_completed must be a boolean")
    reported = parse_reported_findings(request)
    assert_reported_finding_ids_unused(loop, reported)
    return reported


def merge_discovery_findings(
    loop: ReviewLoop,
    reported: Sequence[ReviewFinding],
) -> list[ReviewFinding]:
    """Append-only merge of discovery findings into loop history.

    Existing finding records are never mutated. Reused IDs are rejected.
    """

    assert_reported_finding_ids_unused(loop, reported)
    return list(loop.findings) + list(reported)


def parse_request_finding_actions(
    request: Mapping[str, Any],
) -> list[FindingAction]:
    """Parse optional finding_actions from a respond payload."""

    if "finding_actions" not in request:
        return []
    raw = request.get("finding_actions")
    if not isinstance(raw, list):
        raise ValueError("finding_actions must be a list")
    return [
        parse_finding_action(item)
        for item in raw
        if isinstance(item, dict)
    ]


DiscoveryDerivedOutcome = Literal[
    "approved",
    "changes_requested",
    "review_incomplete",
    "pending",
]


def derive_discovery_outcome(
    findings: Sequence[ReviewFinding],
    finding_actions: Sequence[FindingAction],
    threshold: ReviewSeverity,
    *,
    review_completed: bool,
    finding_set_id: str | None = None,
) -> DiscoveryDerivedOutcome:
    """Derive lifecycle outcome from findings and revise_at (service-owned)."""

    if not review_completed:
        return "review_incomplete"
    if required_open_findings(findings, threshold):
        return "changes_requested"
    if open_optional_findings_without_owner_action(
        findings,
        finding_actions,
        threshold,
        finding_set_id=finding_set_id,
    ):
        # Optional findings need owner actions; do not force revision.
        return "pending"
    return "approved"


def map_discovery_outcome_to_loop_status(
    outcome: DiscoveryDerivedOutcome,
    *,
    stage: str | None = None,
) -> ReviewLoopStatus:
    """Map derived discovery outcome onto persisted loop status vocabulary."""

    if outcome == "review_incomplete":
        return "review_incomplete"
    if outcome == "pending":
        return "advisory_pending"
    if outcome == "changes_requested":
        return "changes_requested"
    if is_scope_review_stage_name(stage):
        return "approved"
    return "approved"


def build_review_incomplete_marker(
    *,
    stage: str | None,
    finding_set_id: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "stage": stage or "discovery",
        "finding_set_id": finding_set_id,
        "reason": reason,
    }


def apply_discovery_response(
    loop: ReviewLoop,
    request: Mapping[str, Any],
    *,
    stage: str | None = None,
) -> tuple[ReviewLoop, list[ReviewFinding], DiscoveryDerivedOutcome]:
    """Validate, merge, and derive outcome for a discovery respond payload."""

    reported = parse_discovery_respond_findings(loop, request)
    review_completed = bool(request.get("review_completed"))
    finding_set_id = validate_finding_set_id_echo(loop, request)
    merged = merge_discovery_findings(loop, reported)
    incoming_actions = parse_request_finding_actions(request)
    finding_actions = list(loop.finding_actions) + incoming_actions
    threshold = loop_revise_at(loop)
    outcome = derive_discovery_outcome(
        merged,
        finding_actions,
        threshold,
        review_completed=review_completed,
        finding_set_id=finding_set_id,
    )
    incomplete: dict[str, Any] | None = None
    if outcome == "review_incomplete":
        reason = str(request.get("summary") or "").strip() or (
            "Review could not be completed."
        )
        incomplete = build_review_incomplete_marker(
            stage=stage or (loop.active_stage or "initial_review"),
            finding_set_id=finding_set_id,
            reason=reason,
        )
    status = map_discovery_outcome_to_loop_status(outcome, stage=stage)
    updated = replace(
        loop,
        findings=merged,
        finding_actions=finding_actions,
        review_incomplete=incomplete,
        status=status,
    )
    if is_mandatory_review_loop(loop) and outcome == "review_incomplete":
        updated = replace(updated, lifecycle_status="review_incomplete")
    return updated, merged, outcome


def reviewer_package_policy_guidance() -> dict[str, Any]:
    """Severity guidance for reviewer packages (never includes revise_at)."""

    from top_down_planning.domain.review_policy import (
        BUILTIN_FINDING_CATEGORIES,
        SEVERITY_DEFINITIONS,
        SEVERITY_ORDER,
    )

    return {
        "severity_order": list(SEVERITY_ORDER),
        "severity_definitions": dict(SEVERITY_DEFINITIONS),
        "categories": sorted(BUILTIN_FINDING_CATEGORIES),
    }


def needs_advisory_handoff(loop: ReviewLoop) -> bool:
    """True when open optionals need owner actions and no required findings force revision."""

    threshold = loop_revise_at(loop)
    if required_open_findings(loop.findings, threshold):
        return False
    return bool(
        open_optional_findings_without_owner_action(
            loop.findings,
            loop.finding_actions,
            threshold,
            finding_set_id=loop.finding_set_id,
        )
    )


def advisory_handoff_allowed(loop: ReviewLoop) -> bool:
    """At most one advisory handoff per finding_set_id (unless a new set is allocated)."""

    if not needs_advisory_handoff(loop):
        return False
    finding_set_id = str(loop.finding_set_id or "").strip()
    if not finding_set_id:
        return False
    return finding_set_id not in loop.advisory_handoffs_completed


def mark_advisory_handoff_completed(loop: ReviewLoop) -> ReviewLoop:
    """Record that the current finding_set_id received its advisory handoff."""

    finding_set_id = str(loop.finding_set_id or "").strip()
    if not finding_set_id:
        raise ValueError("advisory handoff requires finding_set_id")
    if finding_set_id in loop.advisory_handoffs_completed:
        return loop
    return replace(
        loop,
        advisory_handoffs_completed=[*loop.advisory_handoffs_completed, finding_set_id],
    )


def finding_by_id(
    findings: Sequence[ReviewFinding],
    finding_id: str,
) -> ReviewFinding | None:
    for finding in findings:
        if finding.id == finding_id:
            return finding
    return None


def open_challenge_actions(loop: ReviewLoop) -> list[FindingAction]:
    """Challenge actions whose findings are still open (awaiting verification)."""

    open_ids = {finding.id for finding in open_findings(loop.findings)}
    return [
        action
        for action in loop.finding_actions
        if action.action == "challenge" and action.finding_id in open_ids
    ]


def owner_actions_require_verification(
    actions: Sequence[FindingAction],
) -> bool:
    return any(action.action in {"fix", "challenge"} for action in actions)


def owner_actions_require_revision(actions: Sequence[FindingAction]) -> bool:
    """True when any claimed fix requires an artifact revision cycle."""

    return any(action.action == "fix" for action in actions)


def apply_owner_finding_actions(
    loop: ReviewLoop,
    raw_actions: Sequence[Mapping[str, Any]],
    *,
    actor_role: str,
    artifact_revision: int,
) -> tuple[ReviewLoop, list[FindingAction]]:
    """Validate and append primary-agent finding_actions without mutating finding status.

    Primary agents cannot directly set invalid/superseded; only reviewer
    verification may author those dispositions.
    """

    if actor_role not in {"planner", "producer"}:
        raise ValueError("actor_role must be planner or producer")
    threshold = loop_revise_at(loop)
    finding_set_id = str(loop.finding_set_id or "").strip()
    parsed: list[FindingAction] = []
    for item in raw_actions:
        if not isinstance(item, Mapping):
            raise ValueError("finding_actions entry must be an object")
        payload = dict(item)
        payload.setdefault("actor_role", actor_role)
        payload.setdefault("artifact_revision", artifact_revision)
        if finding_set_id and not str(payload.get("finding_set_id") or "").strip():
            payload["finding_set_id"] = finding_set_id
        action = parse_finding_action(payload)
        if action.actor_role != actor_role:
            raise ValueError(
                f"finding_actions actor_role must be {actor_role!r} for this session"
            )
        finding = finding_by_id(loop.findings, action.finding_id)
        if finding is None:
            raise ValueError(
                f"finding_actions references unknown finding_id {action.finding_id!r}"
            )
        if finding.status in {"invalid", "superseded", "resolved"}:
            raise ValueError(
                f"finding {finding.id!r} is already closed; owner actions are not allowed"
            )
        assert_owner_action_allowed_for_finding(finding, action.action, threshold)
        # VR18: owner actions never rewrite finding status to invalid/superseded.
        parsed.append(action)

    merged_actions = list(loop.finding_actions) + parsed
    updated = replace(loop, finding_actions=merged_actions)
    if findings_permit_approval(
        updated.findings,
        updated.finding_actions,
        threshold,
        finding_set_id=updated.finding_set_id,
    ):
        if is_mandatory_review_loop(updated) and is_scope_review_stage_name(
            updated.active_stage or "initial_review"
        ):
            # Scope-review gate closure uses approved (legacy approve still readable).
            updated = replace(updated, status="approved")
        else:
            updated = replace(updated, status="approved")
    elif required_open_findings(updated.findings, threshold):
        if owner_actions_require_revision(parsed) or open_challenge_actions(updated):
            updated = replace(updated, status="changes_requested")
    return updated, parsed


def is_scope_review_stage(loop: ReviewLoop) -> bool:
    return is_scope_review_stage_name(loop.active_stage)


def is_blocker_stage_active(loop: ReviewLoop) -> bool:
    """Legacy alias for :func:`is_scope_review_stage`."""

    return is_scope_review_stage(loop)


def prepare_review_incomplete_retry(loop: ReviewLoop) -> ReviewLoop:
    """Reset loop to pending for the same stage/finding_set_id without consuming budgets."""

    if loop.review_incomplete is None:
        return loop
    stage = str(
        (loop.review_incomplete or {}).get("stage")
        or loop.active_stage
        or "initial_review"
    ).strip()
    lifecycle = loop.lifecycle_status
    if lifecycle == "review_incomplete":
        if is_scope_review_stage_name(stage):
            lifecycle = "scope_review_pending"
        elif stage == "finding_verification":
            lifecycle = "verification_pending"
        else:
            lifecycle = "review_pending"
    return replace(
        loop,
        status="pending",
        lifecycle_status=lifecycle,  # type: ignore[arg-type]
        active_stage=(
            None
            if stage in {"", "initial_review"}
            else canonicalize_review_stage(stage)  # type: ignore[arg-type]
        ),
        # Budgets intentionally unchanged: revision_cycles / scope_review_rounds.
    )


def budgets_snapshot(loop: ReviewLoop) -> dict[str, int]:
    return {
        "revision_cycles": int(loop.revision_cycles),
        "scope_review_rounds": int(loop.blocker_review_rounds),
    }


def primary_review_resume_fields(loop: ReviewLoop) -> dict[str, Any]:
    """Fields for primary-agent revision/advisory packages (includes revise_at)."""

    threshold = loop_revise_at(loop)
    required = required_open_findings(loop.findings, threshold)
    optional = optional_open_findings(loop.findings, threshold)
    return {
        "revise_at": threshold,
        "finding_set_id": loop.finding_set_id,
        "findings": [finding.to_dict() for finding in loop.findings],
        "required_findings": [finding.to_dict() for finding in required],
        "optional_findings": [finding.to_dict() for finding in optional],
        "finding_actions": [action.to_dict() for action in loop.finding_actions],
        **policy_observability_fields(
            loop.findings,
            loop.finding_actions,
            threshold,
            finding_set_id=loop.finding_set_id,
        ),
    }


def verification_required_for_loop(loop: ReviewLoop) -> bool:
    """True when artifact change, claimed fix, or open challenge requires verification."""

    if owner_actions_require_verification(loop.finding_actions):
        # Prefer actions for the active finding set when present.
        active = [
            action
            for action in loop.finding_actions
            if loop.finding_set_id is None
            or action.finding_set_id == loop.finding_set_id
        ]
        if active:
            return owner_actions_require_verification(active)
        return True
    return False


def parse_initial_review_findings(request: dict[str, Any]) -> list[ReviewFinding]:
    """Parse initial_review findings from a mandatory respond payload."""

    if "finding_results" in request or "blocking_findings" in request:
        raise ValueError(
            "initial_review respond must use findings, not stage Result Contract fields"
        )
    if is_discovery_respond_payload(request):
        # Caller must supply the loop for full discovery validation.
        raise ValueError(
            "initial_review discovery payloads must be parsed with "
            "parse_discovery_respond_findings"
        )
    return parse_findings(request.get("findings") or [])


def findings_from_focused_respond(request: dict[str, Any]) -> list[ReviewFinding]:
    """Parse findings from a focused review respond payload."""

    if request.get("stage") is not None:
        raise ValueError("focused review respond must not include stage")
    if is_discovery_respond_payload(request):
        raise ValueError(
            "focused discovery payloads must be parsed with "
            "parse_discovery_respond_findings"
        )
    return parse_findings(request.get("findings") or [])


def validate_decision(decision: str) -> ReviewDecision:
    """Validate a focused-review decision (approved|changes_requested|blocked)."""

    normalized = str(decision).strip()
    if normalized not in {"approved", "changes_requested", "blocked"}:
        raise ValueError(
            "decision must be one of: approved, changes_requested, blocked"
        )
    return normalized  # type: ignore[return-value]


_MANDATORY_STAGE_DECISIONS: Mapping[str, frozenset[str]] = {
    "initial_review": frozenset({"approved", "changes_requested", "blocked"}),
    "finding_verification": frozenset({"verified", "needs_revision", "blocked"}),
    "scope_review": frozenset(
        {"approved", "changes_requested", "blocked", "approve", "blockers_found"}
    ),
    "scope_blocker_review": frozenset(
        {"approved", "changes_requested", "blocked", "approve", "blockers_found"}
    ),
}


def require_review_respond_stage(request: dict[str, Any]) -> str:
    """Return mandatory review stage; reject when stage is missing or unknown."""

    raw_stage = request.get("stage")
    if raw_stage is None or not str(raw_stage).strip():
        raise ValueError(
            "mandatory review respond requires stage: initial_review, "
            "finding_verification, or scope_review"
        )
    stage = str(raw_stage).strip()
    if stage not in _MANDATORY_STAGE_DECISIONS:
        raise ValueError(
            "stage must be one of: initial_review, finding_verification, "
            "scope_review"
        )
    return stage


def validate_mandatory_stage_decision(stage: str, decision: str) -> MandatoryStageDecision:
    """Validate and return stage-native mandatory review decisions."""

    normalized = str(decision).strip()
    allowed = _MANDATORY_STAGE_DECISIONS.get(stage)
    if allowed is None:
        raise ValueError(f"unknown mandatory review stage: {stage!r}")
    if normalized not in allowed:
        raise ValueError(
            f"{stage} decisions must be one of: {', '.join(sorted(allowed))}"
        )
    return normalized  # type: ignore[return-value]


def mandatory_stage_respond_decision(loop: ReviewLoop) -> str:
    """Stage-native decision from result payloads (initial_review uses loop status)."""

    if loop.status == "pending":
        return "pending"
    if loop.status == "advisory_pending":
        return "advisory_pending"
    if loop.status == "blocked":
        return "blocked"
    if loop.status == "review_incomplete":
        return "review_incomplete"

    stage = loop.active_stage or "initial_review"

    if is_scope_review_stage_name(stage):
        blocker = loop.blocker_review_result
        if not isinstance(blocker, dict):
            raise ValueError("scope_review loop missing scope_review_result")
        raw = str(blocker.get("decision") or "").strip()
        canonical = canonicalize_scope_review_decision(raw)
        if canonical not in {"approved", "changes_requested", "blocked"}:
            raise ValueError(f"invalid scope_review_result.decision: {raw!r}")
        return canonical

    if stage == "finding_verification":
        verification = loop.verification_result
        if not isinstance(verification, dict):
            raise ValueError(
                "finding_verification loop missing verification_result"
            )
        raw = str(verification.get("decision") or "").strip()
        if raw not in {"verified", "needs_revision", "blocked"}:
            raise ValueError(
                f"invalid verification_result.decision: {raw!r}"
            )
        return raw

    if loop.status in {"approved", "changes_requested", "blocked"}:
        return loop.status
    raise ValueError(
        f"initial_review loop has invalid status for orchestration: {loop.status!r}"
    )


def merge_verification_findings(
    loop: ReviewLoop,
    request: dict[str, Any],
) -> tuple[list[ReviewFinding], FindingVerificationResult]:
    """Merge Stage-1 finding_results onto loop findings; never drop uncovered IDs."""

    if "finding_results" not in request:
        raise ValueError("finding_verification respond requires finding_results")

    target_digest = str(request.get("target_digest") or "").strip()
    if not target_digest:
        raise ValueError("finding_verification respond requires target_digest")

    raw_results = request.get("finding_results")
    if not isinstance(raw_results, list):
        raise ValueError("finding_results must be a list")

    entries: list[FindingVerificationEntry] = []
    for item in raw_results:
        if not isinstance(item, dict):
            raise ValueError("each finding_results entry must be an object")
        entries.append(FindingVerificationEntry.from_dict(item))

    side_effects = parse_findings(request.get("new_direct_side_effect_findings") or [])
    disposition_by_id = {entry.finding_id: entry for entry in entries}

    prior_required_open = required_open_findings(
        loop.findings,
        loop_revise_at(loop),
    )
    for finding in prior_required_open:
        if finding.id not in disposition_by_id:
            raise ValueError(
                f"finding_results missing required finding_id {finding.id!r}"
            )

    merged: list[ReviewFinding] = []
    seen_ids: set[str] = set()
    for finding in loop.findings:
        entry = disposition_by_id.get(finding.id)
        if entry is not None:
            merged.append(
                replace(finding, status=entry.disposition)  # type: ignore[arg-type]
            )
            seen_ids.add(finding.id)
        else:
            merged.append(finding)
            seen_ids.add(finding.id)

    for finding in side_effects:
        if finding.id in seen_ids:
            raise ValueError(
                f"duplicate finding id {finding.id!r} in new_direct_side_effect_findings"
            )
        merged.append(finding)
        seen_ids.add(finding.id)

    finding_set_id = str(
        request.get("finding_set_id") or loop.finding_set_id or ""
    ).strip()
    if not finding_set_id:
        raise ValueError("finding_verification respond requires finding_set_id")

    decision = validate_verification_decision(str(request.get("decision") or ""))
    result = FindingVerificationResult(
        target_digest=target_digest,
        decision=decision,
        finding_set_id=finding_set_id,
        finding_results=entries,
        new_direct_side_effect_findings=side_effects,
        summary=str(request.get("summary") or ""),
    )
    validate_verification_closure(loop, result, merged)
    return merged, result


def build_scope_review_result(
    request: dict[str, Any],
    loop: ReviewLoop,
) -> tuple[list[ReviewFinding], ScopeReviewResult]:
    """Build Stage-2 scope review result and findings from a respond payload."""

    target_digest = str(request.get("target_digest") or "").strip()
    if not target_digest:
        raise ValueError("scope_review respond requires target_digest")

    decision = validate_scope_review_decision(str(request.get("decision") or ""))
    scope_id = str(request.get("scope_id") or loop.scope.get("kind") or "").strip()
    if not scope_id:
        raise ValueError("scope_review respond requires scope_id")

    raw_reported = request.get("reported_findings")
    if raw_reported is None:
        raw_reported = request.get("blocking_findings") or []
    reported_findings = parse_findings(raw_reported)
    acceptance = [
        str(item)
        for item in (request.get("acceptance_criteria_checked") or [])
    ]
    canonical = canonicalize_scope_review_decision(decision)
    if canonical == "approved":
        loop_findings = list(loop.findings)
    else:
        loop_findings = merge_blocker_reopen_findings(loop, reported_findings)
    result = ScopeReviewResult(
        target_digest=target_digest,
        decision=canonical,  # type: ignore[arg-type]
        scope_id=scope_id,
        reported_findings=reported_findings,
        acceptance_criteria_checked=acceptance,
        summary=str(request.get("summary") or ""),
    )
    return loop_findings, result


def build_scope_blocker_review_result(
    request: dict[str, Any],
    loop: ReviewLoop,
) -> tuple[list[ReviewFinding], ScopeReviewResult]:
    """Legacy alias for :func:`build_scope_review_result`."""

    return build_scope_review_result(request, loop)


def merge_blocker_reopen_findings(
    loop: ReviewLoop,
    blocking_findings: list[ReviewFinding],
) -> list[ReviewFinding]:
    """Retain prior loop findings for audit; overlay new scope-review ids."""

    new_by_id = {finding.id: finding for finding in blocking_findings}
    merged: list[ReviewFinding] = []
    seen: set[str] = set()
    for finding in loop.findings:
        if finding.id in new_by_id:
            merged.append(new_by_id[finding.id])
        else:
            merged.append(finding)
        seen.add(finding.id)
    for finding in blocking_findings:
        if finding.id not in seen:
            merged.append(finding)
    return merged


def validate_verification_closure(
    loop: ReviewLoop,
    result: FindingVerificationResult,
    merged_findings: list[ReviewFinding],
) -> None:
    """Reject verified when open findings or direct side effects remain."""

    if result.decision != "verified":
        return

    unresolved = blocking_unresolved_finding_ids(
        merged_findings,
        revise_at=loop_revise_at(loop),
    )
    if unresolved:
        raise ValueError(
            "verified decision requires all required findings to be resolved "
            f"or superseded; unresolved: {', '.join(unresolved)}"
        )

    if result.new_direct_side_effect_findings:
        raise ValueError(
            "verified decision cannot include new_direct_side_effect_findings"
        )

    for entry in result.finding_results:
        if entry.direct_side_effects:
            raise ValueError(
                f"finding {entry.finding_id!r} has direct_side_effects; "
                "verified is not allowed"
            )

    if not verification_findings_closed(
        result.finding_results,
        require_all=bool(
            required_open_findings(loop.findings, loop_revise_at(loop))
        ),
    ):
        raise ValueError(
            "verified decision requires closed dispositions for all open required findings"
        )


def validate_review_respond_stage(request: dict[str, Any]) -> str | None:
    """Validate optional stage field for focused reviews (must not be set)."""

    raw_stage = request.get("stage")
    if raw_stage is None or not str(raw_stage).strip():
        return None
    raise ValueError(
        "focused review respond must not include stage; use mandatory stage "
        "contracts for whole_plan and whole_output loops"
    )


def apply_review_response(
    loop: ReviewLoop,
    *,
    target_revision: int,
    decision: ReviewLoopStatus,
    findings: list[ReviewFinding],
    approved_digests: dict[str, str] | None = None,
    verification_result: dict[str, Any] | None = None,
    blocker_review_result: dict[str, Any] | None = None,
    lifecycle_status: MandatoryReviewLifecycleStatus | str | None = None,
) -> ReviewLoop:
    if loop.target_revision != target_revision:
        raise ValueError(
            f"target_revision {target_revision} does not match loop target "
            f"{loop.target_revision}"
        )

    if decision in CLEAR_APPROVAL_STATUSES:
        threshold = loop_revise_at(loop)
        if not findings_permit_approval(
            findings,
            loop.finding_actions,
            threshold,
            finding_set_id=loop.finding_set_id,
        ):
            required_ids = required_open_finding_ids(findings, threshold)
            unacked = unacknowledged_optional_finding_ids(
                findings,
                loop.finding_actions,
                threshold,
                finding_set_id=loop.finding_set_id,
            )
            details: list[str] = []
            if required_ids:
                details.append(
                    "open required findings: " + ", ".join(required_ids)
                )
            if unacked:
                details.append(
                    "unacknowledged optional findings: " + ", ".join(unacked)
                )
            raise ValueError(
                f"{decision!r} decision requires no open required findings and "
                "qualifying owner actions on every open optional finding; "
                + "; ".join(details)
            )

    resolved_lifecycle = lifecycle_status if lifecycle_status is not None else loop.lifecycle_status
    resolved_verification = (
        verification_result
        if verification_result is not None
        else loop.verification_result
    )
    resolved_blocker = (
        blocker_review_result
        if blocker_review_result is not None
        else loop.blocker_review_result
    )

    return replace(
        loop,
        status=decision,
        findings=findings,
        approved_digests=(
            approved_digests if approved_digests is not None else loop.approved_digests
        ),
        lifecycle_status=resolved_lifecycle,  # type: ignore[arg-type]
        verification_result=resolved_verification,
        blocker_review_result=resolved_blocker,
    )


@dataclass
class FindingVerificationEntry:
    """One finding's Stage-1 verification result (Result Contracts)."""

    finding_id: str
    disposition: FindingDisposition
    evidence: list[str] = field(default_factory=list)
    direct_side_effects: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "disposition": self.disposition,
            "evidence": list(self.evidence),
            "direct_side_effects": list(self.direct_side_effects),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> FindingVerificationEntry:
        disposition = validate_finding_disposition(
            str(payload.get("disposition") or "unresolved")
        )
        return cls(
            finding_id=str(payload["finding_id"]),
            disposition=disposition,
            evidence=[str(item) for item in (payload.get("evidence") or [])],
            direct_side_effects=[
                str(item) for item in (payload.get("direct_side_effects") or [])
            ],
        )


@dataclass
class FindingVerificationResult:
    """Stage-1 finding verification/revision result contract."""

    target_digest: str
    decision: VerificationDecision
    finding_set_id: str
    finding_results: list[FindingVerificationEntry] = field(default_factory=list)
    new_direct_side_effect_findings: list[ReviewFinding] = field(default_factory=list)
    summary: str = ""
    stage: ReviewStage = "finding_verification"

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "target_digest": self.target_digest,
            "finding_set_id": self.finding_set_id,
            "decision": self.decision,
            "finding_results": [entry.to_dict() for entry in self.finding_results],
            "new_direct_side_effect_findings": [
                finding.to_dict() for finding in self.new_direct_side_effect_findings
            ],
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> FindingVerificationResult:
        stage = str(payload.get("stage") or "finding_verification").strip()
        if stage != "finding_verification":
            raise ValueError(
                "finding verification result stage must be 'finding_verification'"
            )
        decision = validate_verification_decision(str(payload.get("decision") or ""))
        finding_results = [
            FindingVerificationEntry.from_dict(item)
            for item in (payload.get("finding_results") or [])
            if isinstance(item, dict)
        ]
        side_effects = [
            ReviewFinding.from_dict(item)
            for item in (payload.get("new_direct_side_effect_findings") or [])
            if isinstance(item, dict)
        ]
        return cls(
            target_digest=str(payload.get("target_digest") or ""),
            decision=decision,
            finding_set_id=str(payload.get("finding_set_id") or ""),
            finding_results=finding_results,
            new_direct_side_effect_findings=side_effects,
            summary=str(payload.get("summary") or ""),
            stage="finding_verification",
        )


@dataclass
class ScopeReviewResult:
    """Fresh scope-complete review result contract (mandatory approval gate)."""

    target_digest: str
    decision: ScopeReviewDecision
    scope_id: str
    reported_findings: list[ReviewFinding] = field(default_factory=list)
    acceptance_criteria_checked: list[str] = field(default_factory=list)
    summary: str = ""
    stage: ReviewStage = "scope_review"

    def __init__(
        self,
        target_digest: str,
        decision: ScopeReviewDecision,
        scope_id: str,
        reported_findings: list[ReviewFinding] | None = None,
        acceptance_criteria_checked: list[str] | None = None,
        summary: str = "",
        stage: ReviewStage = "scope_review",
        *,
        blocking_findings: list[ReviewFinding] | None = None,
    ) -> None:
        findings = reported_findings
        if findings is None:
            findings = blocking_findings or []
        self.target_digest = target_digest
        self.decision = decision
        self.scope_id = scope_id
        self.reported_findings = list(findings)
        self.acceptance_criteria_checked = list(acceptance_criteria_checked or [])
        self.summary = summary
        self.stage = (
            SCOPE_REVIEW_STAGE
            if is_scope_review_stage_name(stage)
            else stage
        )

    @property
    def blocking_findings(self) -> list[ReviewFinding]:
        """Legacy alias for :attr:`reported_findings`."""

        return self.reported_findings

    def to_dict(self) -> dict[str, Any]:
        findings_payload = [finding.to_dict() for finding in self.reported_findings]
        decision = canonicalize_scope_review_decision(self.decision)
        return {
            "stage": SCOPE_REVIEW_STAGE,
            "target_digest": self.target_digest,
            "scope_id": self.scope_id,
            "decision": decision,
            "reported_findings": findings_payload,
            "acceptance_criteria_checked": list(self.acceptance_criteria_checked),
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ScopeReviewResult:
        stage_raw = str(payload.get("stage") or SCOPE_REVIEW_STAGE).strip()
        if not is_scope_review_stage_name(stage_raw):
            raise ValueError(
                "scope review result stage must be 'scope_review' "
                "(legacy 'scope_blocker_review' also accepted)"
            )
        decision = validate_scope_review_decision(str(payload.get("decision") or ""))
        raw_findings = payload.get("reported_findings")
        if raw_findings is None:
            raw_findings = payload.get("blocking_findings") or []
        reported = [
            ReviewFinding.from_dict(item)
            for item in raw_findings
            if isinstance(item, dict)
        ]
        return cls(
            target_digest=str(payload.get("target_digest") or ""),
            decision=canonicalize_scope_review_decision(decision),  # type: ignore[arg-type]
            scope_id=str(payload.get("scope_id") or ""),
            reported_findings=reported,
            acceptance_criteria_checked=[
                str(item) for item in (payload.get("acceptance_criteria_checked") or [])
            ],
            summary=str(payload.get("summary") or ""),
            stage=SCOPE_REVIEW_STAGE,
        )


# Legacy alias retained for callers/tests still importing the old name.
ScopeBlockerReviewResult = ScopeReviewResult


def validate_finding_disposition(disposition: str) -> FindingDisposition:
    normalized = str(disposition).strip()
    if normalized not in FINDING_DISPOSITIONS:
        raise ValueError(
            "finding disposition must be one of: "
            + ", ".join(sorted(FINDING_DISPOSITIONS))
        )
    return normalized  # type: ignore[return-value]


def validate_verification_decision(decision: str) -> VerificationDecision:
    normalized = str(decision).strip()
    if normalized not in {"verified", "needs_revision", "blocked"}:
        raise ValueError(
            "verification decision must be one of: verified, needs_revision, blocked"
        )
    return normalized  # type: ignore[return-value]


def validate_scope_review_decision(decision: str) -> ScopeReviewDecision:
    normalized = str(decision).strip()
    if normalized not in {
        "approved",
        "changes_requested",
        "blocked",
        "approve",
        "blockers_found",
    }:
        raise ValueError(
            "scope review decision must be one of: approved, changes_requested, "
            "blocked (legacy: approve, blockers_found)"
        )
    return normalized  # type: ignore[return-value]


def validate_blocker_review_decision(decision: str) -> BlockerReviewDecision:
    """Legacy alias for :func:`validate_scope_review_decision`."""

    return validate_scope_review_decision(decision)


def validate_mandatory_lifecycle_status(
    status: str,
) -> MandatoryReviewLifecycleStatus:
    normalized = str(status).strip()
    if normalized not in MANDATORY_REVIEW_TRANSITIONS:
        raise ValueError(
            "mandatory review lifecycle status must be one of: "
            + ", ".join(sorted(MANDATORY_REVIEW_TRANSITIONS))
        )
    return normalized  # type: ignore[return-value]


def can_transition_mandatory_review(
    current: str,
    nxt: str,
) -> bool:
    """Return whether ``current → nxt`` is an allowed Suggested State Model edge."""

    current_status = validate_mandatory_lifecycle_status(current)
    next_status = validate_mandatory_lifecycle_status(nxt)
    return next_status in MANDATORY_REVIEW_TRANSITIONS[current_status]


def assert_mandatory_review_transition(current: str, nxt: str) -> None:
    if not can_transition_mandatory_review(current, nxt):
        raise ValueError(
            f"illegal mandatory review transition: {current!r} → {nxt!r}"
        )


def digests_equal(left: str | None, right: str | None) -> bool:
    """Digest equality for Digest and Approval Rules (exact string match)."""

    if left is None or right is None:
        return False
    left_norm = str(left).strip()
    right_norm = str(right).strip()
    if not left_norm or not right_norm:
        return False
    return left_norm == right_norm


def stage_digest_matches_artifact(
    *,
    stage_target_digest: str | None,
    current_artifact_digest: str | None,
) -> bool:
    """``stage.target_digest == current_artifact.digest``."""

    return digests_equal(stage_target_digest, current_artifact_digest)


def verification_findings_closed(
    finding_results: list[FindingVerificationEntry],
    *,
    require_all: bool = True,
) -> bool:
    """True when required findings have closed dispositions and no open side effects."""

    if require_all and not finding_results:
        return False
    for entry in finding_results:
        if entry.disposition in OPEN_FINDING_DISPOSITIONS:
            return False
        if entry.direct_side_effects:
            return False
    return True


def is_approval_eligible(
    *,
    verification: FindingVerificationResult | None,
    blocker_review: ScopeReviewResult | None,
    current_artifact_digest: str,
    lifecycle_status: MandatoryReviewLifecycleStatus | str | None = None,
) -> bool:
    """Core Invariant + Digest and Approval Rules for mandatory gates.

    Approval requires verified finding closure, no direct side effects, a fresh
    scope review deciding ``approved`` against the current digest, and must never
    treat ``limit_reached`` / ``blocked`` as approval.
    """

    if lifecycle_status in {"blocked", "limit_reached"}:
        return False
    if blocker_review is None:
        return False
    if not is_scope_review_stage_name(blocker_review.stage):
        return False
    if canonicalize_scope_review_decision(blocker_review.decision) != "approved":
        return False
    if blocker_review.reported_findings:
        return False
    if not stage_digest_matches_artifact(
        stage_target_digest=blocker_review.target_digest,
        current_artifact_digest=current_artifact_digest,
    ):
        return False

    if verification is not None:
        if verification.stage != "finding_verification":
            return False
        if verification.decision != "verified":
            return False
        if verification.new_direct_side_effect_findings:
            return False
        if not verification_findings_closed(verification.finding_results):
            return False
        if not stage_digest_matches_artifact(
            stage_target_digest=verification.target_digest,
            current_artifact_digest=current_artifact_digest,
        ):
            return False

    return True


# Defaults aligned with config.defaults.DEFAULT_CONFIG limits.whole_*_review.
_DEFAULT_MAX_REVISION_CYCLES = 5
_DEFAULT_MAX_SCOPE_REVIEW_ROUNDS = 3
_DEFAULT_MAX_BLOCKER_REVIEW_ROUNDS = _DEFAULT_MAX_SCOPE_REVIEW_ROUNDS

ExhaustedReviewBudget = Literal[
    "verification_revision",
    "scope_review",
    "blocker_review",  # legacy alias
]


@dataclass(frozen=True)
class MandatoryReviewLimits:
    """Loop Bounds for mandatory whole_plan / whole_output review.

    ``max_revision_cycles`` caps verification/revision cycles per finding set.
    ``max_scope_review_rounds`` caps fresh scope-complete reviews per phase.
    ``max_blocker_review_rounds`` remains a readable legacy alias property.
    """

    max_revision_cycles: int = _DEFAULT_MAX_REVISION_CYCLES
    max_scope_review_rounds: int = _DEFAULT_MAX_SCOPE_REVIEW_ROUNDS

    def __init__(
        self,
        max_revision_cycles: int = _DEFAULT_MAX_REVISION_CYCLES,
        max_scope_review_rounds: int | None = None,
        max_blocker_review_rounds: int | None = None,
    ) -> None:
        rounds = max_scope_review_rounds
        if rounds is None:
            rounds = max_blocker_review_rounds
        if rounds is None:
            rounds = _DEFAULT_MAX_SCOPE_REVIEW_ROUNDS
        object.__setattr__(self, "max_revision_cycles", int(max_revision_cycles))
        object.__setattr__(self, "max_scope_review_rounds", int(rounds))

    @property
    def max_blocker_review_rounds(self) -> int:
        return self.max_scope_review_rounds

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> MandatoryReviewLimits:
        raw = dict(payload or {})
        rounds = raw.get("max_scope_review_rounds")
        if rounds is None:
            rounds = raw.get(
                "max_blocker_review_rounds",
                _DEFAULT_MAX_SCOPE_REVIEW_ROUNDS,
            )
        return cls(
            max_revision_cycles=int(
                raw.get("max_revision_cycles", _DEFAULT_MAX_REVISION_CYCLES)
            ),
            max_scope_review_rounds=int(rounds),
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "max_revision_cycles": self.max_revision_cycles,
            "max_scope_review_rounds": self.max_scope_review_rounds,
        }


def mandatory_review_limits_from_config(
    config: Mapping[str, Any] | None,
    review_type: Literal["whole_plan", "whole_output"],
) -> MandatoryReviewLimits:
    """Load stage budgets for a mandatory review type from resolved run config."""

    limits_key = (
        "whole_plan_review" if review_type == "whole_plan" else "whole_output_review"
    )
    section = ((config or {}).get("limits") or {}).get(limits_key)
    if section is not None and not isinstance(section, Mapping):
        raise ValueError(f"limits.{limits_key} must be an object")
    return MandatoryReviewLimits.from_mapping(section)


def verification_revision_budget_exhausted(
    revision_cycles: int,
    limits: MandatoryReviewLimits,
) -> bool:
    return int(revision_cycles) >= int(limits.max_revision_cycles)


def blocker_review_budget_exhausted(
    blocker_review_rounds: int,
    limits: MandatoryReviewLimits,
) -> bool:
    return int(blocker_review_rounds) >= int(limits.max_scope_review_rounds)


scope_review_budget_exhausted = blocker_review_budget_exhausted


@dataclass(frozen=True)
class LimitReachedTerminal:
    """Terminal Loop Bounds result: preserves findings; never an approval."""

    lifecycle_status: Literal["limit_reached"]
    exhausted_budget: ExhaustedReviewBudget
    findings: tuple[ReviewFinding, ...]
    reason: str
    decision: Literal["blocked"] = "blocked"

    def to_dict(self) -> dict[str, Any]:
        return {
            "lifecycle_status": self.lifecycle_status,
            "exhausted_budget": normalize_exhausted_budget(self.exhausted_budget),
            "findings": [finding.to_dict() for finding in self.findings],
            "reason": self.reason,
            "decision": self.decision,
            "approved": False,
        }


def build_limit_reached_terminal(
    *,
    exhausted_budget: ExhaustedReviewBudget,
    findings: list[ReviewFinding],
    limits: MandatoryReviewLimits,
) -> LimitReachedTerminal:
    """Build a ``limit_reached`` terminal that preserves unresolved findings.

    ``limit_reached`` must never convert into approval (Loop Bounds).
    """

    exhausted = normalize_exhausted_budget(exhausted_budget) or exhausted_budget
    if exhausted == "verification_revision":
        reason = (
            "mandatory review exceeded max_revision_cycles "
            f"({limits.max_revision_cycles})"
        )
    elif exhausted == "scope_review":
        reason = (
            "mandatory review exceeded max_scope_review_rounds "
            f"({limits.max_scope_review_rounds})"
        )
    else:
        raise ValueError(f"unknown exhausted budget: {exhausted_budget!r}")

    return LimitReachedTerminal(
        lifecycle_status="limit_reached",
        exhausted_budget=exhausted,  # type: ignore[arg-type]
        findings=tuple(findings),
        reason=reason,
    )


def reject_approval_when_budget_exhausted(
    *,
    revision_cycles: int,
    blocker_review_rounds: int,
    limits: MandatoryReviewLimits,
    findings: list[ReviewFinding],
) -> LimitReachedTerminal | None:
    """If a Loop Bounds budget is exhausted, return a non-approving terminal.

    Exhausted budgets never yield approval. Callers must not treat a ``None``
    return as approval — still evaluate ``is_approval_eligible`` separately.
    """

    if verification_revision_budget_exhausted(revision_cycles, limits):
        return build_limit_reached_terminal(
            exhausted_budget="verification_revision",
            findings=findings,
            limits=limits,
        )
    if scope_review_budget_exhausted(blocker_review_rounds, limits):
        return build_limit_reached_terminal(
            exhausted_budget="scope_review",
            findings=findings,
            limits=limits,
        )
    return None


def approval_allowed_under_loop_bounds(
    *,
    revision_cycles: int,
    blocker_review_rounds: int,
    limits: MandatoryReviewLimits,
    verification: FindingVerificationResult | None,
    blocker_review: ScopeReviewResult | None,
    current_artifact_digest: str,
    findings: list[ReviewFinding],
    lifecycle_status: MandatoryReviewLifecycleStatus | str | None = None,
) -> bool:
    """True only when budgets remain and Core Invariant approval eligibility holds.

    ``limit_reached`` / exhausted budgets never convert into approval.
    """

    terminal = reject_approval_when_budget_exhausted(
        revision_cycles=revision_cycles,
        blocker_review_rounds=blocker_review_rounds,
        limits=limits,
        findings=findings,
    )
    if terminal is not None:
        return False
    return is_approval_eligible(
        verification=verification,
        blocker_review=blocker_review,
        current_artifact_digest=current_artifact_digest,
        lifecycle_status=lifecycle_status,
    )


def mandatory_approval_allowed(
    loop: ReviewLoop,
    *,
    current_artifact_digest: str,
    limits: MandatoryReviewLimits,
) -> bool:
    """Evaluate Core Invariant + Loop Bounds for a persisted mandatory loop."""

    verification: FindingVerificationResult | None = None
    if loop.verification_result is not None:
        verification = FindingVerificationResult.from_dict(loop.verification_result)
    blocker_review: ScopeReviewResult | None = None
    if loop.blocker_review_result is not None:
        blocker_review = ScopeReviewResult.from_dict(loop.blocker_review_result)
    return approval_allowed_under_loop_bounds(
        revision_cycles=loop.revision_cycles,
        blocker_review_rounds=loop.blocker_review_rounds,
        limits=limits,
        verification=verification,
        blocker_review=blocker_review,
        current_artifact_digest=current_artifact_digest,
        findings=loop.findings,
        lifecycle_status=loop.lifecycle_status,
    )
