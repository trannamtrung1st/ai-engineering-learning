"""Review loop models and helpers (proposal §11; two-stage mandatory review)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

_ACTIVE_REVIEW_BLOCKING_STATUSES = frozenset(
    {"changes_requested", "needs_revision", "blockers_found"}
)
PLAN_REVIEW_TYPES = frozenset({"focused_plan", "whole_plan"})
OUTPUT_REVIEW_TYPES = frozenset({"focused_output", "whole_output"})

ReviewLoopType = Literal["whole_plan", "whole_output", "focused_plan", "focused_output"]
ReviewDecision = Literal["approved", "changes_requested", "blocked"]
ReviewLoopStatus = Literal[
    "pending",
    "approved",
    "changes_requested",
    "blocked",
    "verified",
    "needs_revision",
    "approve",
    "blockers_found",
]
MandatoryStageDecision = Literal[
    "approved",
    "changes_requested",
    "blocked",
    "verified",
    "needs_revision",
    "approve",
    "blockers_found",
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
ReviewStage = Literal["finding_verification", "scope_blocker_review"]
VerificationDecision = Literal["verified", "needs_revision", "blocked"]
BlockerReviewDecision = Literal["approve", "blockers_found", "blocked"]

# Suggested State Model for mandatory whole_* loops
MandatoryReviewLifecycleStatus = Literal[
    "review_pending",
    "findings_open",
    "revision_in_progress",
    "verification_pending",
    "findings_closed",
    "blocker_review_pending",
    "approved",
    "blocked",
    "limit_reached",
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

MANDATORY_REVIEW_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "review_pending": frozenset({"findings_open", "blocker_review_pending"}),
    "findings_open": frozenset({"revision_in_progress", "blocked"}),
    "revision_in_progress": frozenset({"verification_pending", "limit_reached"}),
    "verification_pending": frozenset(
        {"findings_closed", "revision_in_progress", "blocked", "limit_reached"}
    ),
    "findings_closed": frozenset({"blocker_review_pending", "limit_reached"}),
    "blocker_review_pending": frozenset(
        {"approved", "findings_open", "blocked", "limit_reached"}
    ),
    "approved": frozenset(),
    "blocked": frozenset(),
    "limit_reached": frozenset(),
}


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
    # Two-stage mandatory loop fields (optional; focused loops leave unset).
    lifecycle_status: MandatoryReviewLifecycleStatus | None = None
    active_stage: ReviewStage | None = None
    finding_set_id: str | None = None
    blocker_review_rounds: int = 0
    verification_result: dict[str, Any] | None = None
    blocker_review_result: dict[str, Any] | None = None
    exhausted_budget: ExhaustedReviewBudget | None = None

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
        if self.lifecycle_status is not None:
            payload["lifecycle_status"] = self.lifecycle_status
        if self.active_stage is not None:
            payload["active_stage"] = self.active_stage
        if self.finding_set_id is not None:
            payload["finding_set_id"] = self.finding_set_id
        if self.blocker_review_rounds:
            payload["blocker_review_rounds"] = self.blocker_review_rounds
        if self.verification_result is not None:
            payload["verification_result"] = dict(self.verification_result)
        if self.blocker_review_result is not None:
            payload["blocker_review_result"] = dict(self.blocker_review_result)
        if self.exhausted_budget is not None:
            payload["exhausted_budget"] = self.exhausted_budget
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
        lifecycle_status = (
            str(lifecycle_raw).strip()  # type: ignore[assignment]
            if lifecycle_raw is not None and str(lifecycle_raw).strip()
            else None
        )
        stage_raw = payload.get("active_stage")
        active_stage = (
            str(stage_raw).strip()  # type: ignore[assignment]
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
        blocker_raw = payload.get("blocker_review_result")
        blocker_review_result = (
            dict(blocker_raw) if isinstance(blocker_raw, dict) else None
        )
        exhausted_raw = payload.get("exhausted_budget")
        exhausted_budget = (
            str(exhausted_raw).strip()  # type: ignore[assignment]
            if exhausted_raw is not None and str(exhausted_raw).strip()
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
            lifecycle_status=lifecycle_status,  # type: ignore[arg-type]
            active_stage=active_stage,  # type: ignore[arg-type]
            finding_set_id=finding_set_id,
            blocker_review_rounds=int(payload.get("blocker_review_rounds") or 0),
            verification_result=verification_result,
            blocker_review_result=blocker_review_result,
            exhausted_budget=exhausted_budget,
        )


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
        return True
    blocker = loop.blocker_review_result
    if is_mandatory_review_loop(loop) and isinstance(blocker, dict):
        if blocker.get("decision") == "approve":
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
            if not is_open_finding_status(finding.status):
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


def is_open_finding_status(status: str) -> bool:
    """True when a finding still requires verification/revision attention."""

    return str(status).strip() in OPEN_FINDING_DISPOSITIONS


def blocking_unresolved_finding_ids(findings: list[ReviewFinding]) -> list[str]:
    unresolved: list[str] = []
    for finding in findings:
        if finding.importance != "blocking":
            continue
        if not is_open_finding_status(finding.status):
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
        if is_terminal_review_loop(loop):
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
        if not is_open_finding_status(finding.status):
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
        if not is_open_finding_status(finding.status):
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
        if payload.get("status") != "approve":
            continue
        target_revision = payload.get("target_revision")
        if target_revision is None:
            continue
        if int(target_revision) != output_revision:
            continue
        if not is_mandatory_gate_approval_record(payload):
            continue
        return payload
    return None


def is_mandatory_gate_approval_record(payload: Mapping[str, Any]) -> bool:
    """True when a persisted mandatory loop completed the two-stage approval gate."""

    if payload.get("status") != "approve":
        return False
    if payload.get("lifecycle_status") != "approved":
        return False
    if payload.get("active_stage") != "scope_blocker_review":
        return False
    blocker_raw = payload.get("blocker_review_result")
    if not isinstance(blocker_raw, dict):
        return False
    if blocker_raw.get("stage") != "scope_blocker_review":
        return False
    if blocker_raw.get("decision") != "approve":
        return False
    if blocker_raw.get("blocking_findings"):
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
        if payload.get("status") != "approve":
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
    "scope_blocker_review": frozenset({"approve", "blockers_found", "blocked"}),
}


def require_review_respond_stage(request: dict[str, Any]) -> str:
    """Return mandatory review stage; reject when stage is missing or unknown."""

    raw_stage = request.get("stage")
    if raw_stage is None or not str(raw_stage).strip():
        raise ValueError(
            "mandatory review respond requires stage: initial_review, "
            "finding_verification, or scope_blocker_review"
        )
    stage = str(raw_stage).strip()
    if stage not in _MANDATORY_STAGE_DECISIONS:
        raise ValueError(
            "stage must be one of: initial_review, finding_verification, "
            "scope_blocker_review"
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
    if loop.status == "blocked":
        return "blocked"

    stage = loop.active_stage or "initial_review"

    if stage == "scope_blocker_review":
        blocker = loop.blocker_review_result
        if not isinstance(blocker, dict):
            raise ValueError(
                "scope_blocker_review loop missing blocker_review_result"
            )
        raw = str(blocker.get("decision") or "").strip()
        if raw not in {"approve", "blockers_found", "blocked"}:
            raise ValueError(
                f"invalid blocker_review_result.decision: {raw!r}"
            )
        return raw

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


def parse_initial_review_findings(request: dict[str, Any]) -> list[ReviewFinding]:
    """Parse initial_review findings from a mandatory respond payload."""

    if "finding_results" in request or "blocking_findings" in request:
        raise ValueError(
            "initial_review respond must use findings, not stage Result Contract fields"
        )
    return parse_findings(request.get("findings") or [])


def findings_from_focused_respond(request: dict[str, Any]) -> list[ReviewFinding]:
    """Parse findings from a focused review respond payload."""

    if request.get("stage") is not None:
        raise ValueError("focused review respond must not include stage")
    return parse_findings(request.get("findings") or [])


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

    prior_blocking_open = [
        finding
        for finding in loop.findings
        if finding.importance == "blocking" and is_open_finding_status(finding.status)
    ]
    for finding in prior_blocking_open:
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
                ReviewFinding(
                    id=finding.id,
                    importance=finding.importance,
                    target_refs=list(finding.target_refs),
                    issue=finding.issue,
                    required_change=finding.required_change,
                    status=entry.disposition,  # type: ignore[arg-type]
                )
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


def build_scope_blocker_review_result(
    request: dict[str, Any],
    loop: ReviewLoop,
) -> tuple[list[ReviewFinding], ScopeBlockerReviewResult]:
    """Build Stage-2 blocker review result and findings from a respond payload."""

    target_digest = str(request.get("target_digest") or "").strip()
    if not target_digest:
        raise ValueError("scope_blocker_review respond requires target_digest")

    decision = validate_blocker_review_decision(str(request.get("decision") or ""))
    scope_id = str(request.get("scope_id") or loop.scope.get("kind") or "").strip()
    if not scope_id:
        raise ValueError("scope_blocker_review respond requires scope_id")

    blocking_findings = parse_findings(request.get("blocking_findings") or [])
    acceptance = [
        str(item)
        for item in (request.get("acceptance_criteria_checked") or [])
    ]
    if decision == "approve":
        loop_findings = list(loop.findings)
    else:
        loop_findings = merge_blocker_reopen_findings(loop, blocking_findings)
    result = ScopeBlockerReviewResult(
        target_digest=target_digest,
        decision=decision,
        scope_id=scope_id,
        blocking_findings=blocking_findings,
        acceptance_criteria_checked=acceptance,
        summary=str(request.get("summary") or ""),
    )
    return loop_findings, result


def merge_blocker_reopen_findings(
    loop: ReviewLoop,
    blocking_findings: list[ReviewFinding],
) -> list[ReviewFinding]:
    """Retain prior loop findings for audit; overlay new blocker ids."""

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

    unresolved = blocking_unresolved_finding_ids(merged_findings)
    if unresolved:
        raise ValueError(
            "verified decision requires all blocking findings to be resolved "
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
            [
                finding
                for finding in loop.findings
                if finding.importance == "blocking"
                and is_open_finding_status(finding.status)
            ]
        ),
    ):
        raise ValueError(
            "verified decision requires closed dispositions for all open blocking findings"
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
        unresolved = blocking_unresolved_finding_ids(findings)
        if unresolved:
            raise ValueError(
                f"{decision!r} decision requires all blocking findings to be resolved "
                f"or superseded; unresolved: {', '.join(unresolved)}"
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
        lifecycle_status=resolved_lifecycle,  # type: ignore[arg-type]
        active_stage=loop.active_stage,
        finding_set_id=loop.finding_set_id,
        blocker_review_rounds=loop.blocker_review_rounds,
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
class ScopeBlockerReviewResult:
    """Stage-2 scope-complete blocker review result contract."""

    target_digest: str
    decision: BlockerReviewDecision
    scope_id: str
    blocking_findings: list[ReviewFinding] = field(default_factory=list)
    acceptance_criteria_checked: list[str] = field(default_factory=list)
    summary: str = ""
    stage: ReviewStage = "scope_blocker_review"

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "target_digest": self.target_digest,
            "scope_id": self.scope_id,
            "decision": self.decision,
            "blocking_findings": [
                finding.to_dict() for finding in self.blocking_findings
            ],
            "acceptance_criteria_checked": list(self.acceptance_criteria_checked),
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ScopeBlockerReviewResult:
        stage = str(payload.get("stage") or "scope_blocker_review").strip()
        if stage != "scope_blocker_review":
            raise ValueError(
                "blocker review result stage must be 'scope_blocker_review'"
            )
        decision = validate_blocker_review_decision(str(payload.get("decision") or ""))
        blocking = [
            ReviewFinding.from_dict(item)
            for item in (payload.get("blocking_findings") or [])
            if isinstance(item, dict)
        ]
        return cls(
            target_digest=str(payload.get("target_digest") or ""),
            decision=decision,
            scope_id=str(payload.get("scope_id") or ""),
            blocking_findings=blocking,
            acceptance_criteria_checked=[
                str(item) for item in (payload.get("acceptance_criteria_checked") or [])
            ],
            summary=str(payload.get("summary") or ""),
            stage="scope_blocker_review",
        )


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


def validate_blocker_review_decision(decision: str) -> BlockerReviewDecision:
    normalized = str(decision).strip()
    if normalized not in {"approve", "blockers_found", "blocked"}:
        raise ValueError(
            "blocker review decision must be one of: approve, blockers_found, blocked"
        )
    return normalized  # type: ignore[return-value]


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
    blocker_review: ScopeBlockerReviewResult | None,
    current_artifact_digest: str,
    lifecycle_status: MandatoryReviewLifecycleStatus | str | None = None,
) -> bool:
    """Core Invariant + Digest and Approval Rules for mandatory gates.

    Approval requires verified finding closure, no direct side effects, a fresh
    blocker review deciding ``approve`` against the current digest, and must never
    treat ``limit_reached`` / ``blocked`` as approval.
    """

    if lifecycle_status in {"blocked", "limit_reached"}:
        return False
    if blocker_review is None:
        return False
    if blocker_review.stage != "scope_blocker_review":
        return False
    if blocker_review.decision != "approve":
        return False
    if blocker_review.blocking_findings:
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
_DEFAULT_MAX_BLOCKER_REVIEW_ROUNDS = 3

ExhaustedReviewBudget = Literal["verification_revision", "blocker_review"]


@dataclass(frozen=True)
class MandatoryReviewLimits:
    """Loop Bounds for mandatory whole_plan / whole_output review.

    ``max_revision_cycles`` caps verification/revision cycles per finding set.
    ``max_blocker_review_rounds`` caps fresh scope-complete blocker reviews per phase.
    """

    max_revision_cycles: int = _DEFAULT_MAX_REVISION_CYCLES
    max_blocker_review_rounds: int = _DEFAULT_MAX_BLOCKER_REVIEW_ROUNDS

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> MandatoryReviewLimits:
        raw = dict(payload or {})
        return cls(
            max_revision_cycles=int(
                raw.get("max_revision_cycles", _DEFAULT_MAX_REVISION_CYCLES)
            ),
            max_blocker_review_rounds=int(
                raw.get(
                    "max_blocker_review_rounds",
                    _DEFAULT_MAX_BLOCKER_REVIEW_ROUNDS,
                )
            ),
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "max_revision_cycles": self.max_revision_cycles,
            "max_blocker_review_rounds": self.max_blocker_review_rounds,
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
    return int(blocker_review_rounds) >= int(limits.max_blocker_review_rounds)


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
            "exhausted_budget": self.exhausted_budget,
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

    if exhausted_budget == "verification_revision":
        reason = (
            "mandatory review exceeded max_revision_cycles "
            f"({limits.max_revision_cycles})"
        )
    elif exhausted_budget == "blocker_review":
        reason = (
            "mandatory review exceeded max_blocker_review_rounds "
            f"({limits.max_blocker_review_rounds})"
        )
    else:
        raise ValueError(f"unknown exhausted budget: {exhausted_budget!r}")

    return LimitReachedTerminal(
        lifecycle_status="limit_reached",
        exhausted_budget=exhausted_budget,
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
    if blocker_review_budget_exhausted(blocker_review_rounds, limits):
        return build_limit_reached_terminal(
            exhausted_budget="blocker_review",
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
    blocker_review: ScopeBlockerReviewResult | None,
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
    blocker_review: ScopeBlockerReviewResult | None = None
    if loop.blocker_review_result is not None:
        blocker_review = ScopeBlockerReviewResult.from_dict(loop.blocker_review_result)
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
