"""Review loop models and helpers (proposal §11; mandatory review gates)."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from top_down_planning.domain.finding_families import (
    AuditAttestationRun,
    FamilySweepRecord,
    FindingFamily,
    parse_audit_runs,
    parse_family_sweeps,
    parse_finding_families,
)
from top_down_planning.domain.artifact_refs import (
    ArtifactRef,
    artifact_ref_to_dict,
    parse_artifact_ref,
)
from top_down_planning.domain.session_bindings import (
    SessionBinding,
    binding_provider_session_id,
    new_session_binding,
)

from top_down_planning.domain.review_policy import (
    BUILTIN_REVISE_AT,
    CATEGORY_DEFINITIONS,
    FINDING_CATEGORY_ORDER,
    FindingCategory,
    ReviewSeverity,
    SEVERITY_DEFINITIONS,
    SEVERITY_ORDER,
    severity_at_or_above,
    validate_finding_category,
    validate_review_severity,
)

# Persisted review-record schema version (separate from run-record schema_version).
LEGACY_REVIEW_RECORD_SCHEMA_VERSION = 1
LEGACY_REVIEW_CONTRACT_VERSION = 1
CURRENT_REVIEW_RECORD_SCHEMA_VERSION = 2
CURRENT_REVIEW_CONTRACT_VERSION = 2
SUPPORTED_REVIEW_RECORD_SCHEMA_VERSIONS = frozenset({CURRENT_REVIEW_RECORD_SCHEMA_VERSION})
SUPPORTED_REVIEW_CONTRACT_VERSIONS = frozenset({CURRENT_REVIEW_CONTRACT_VERSION})

_ACTIVE_REVIEW_BLOCKING_STATUSES = frozenset(
    {"changes_requested", "needs_revision"}
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
    "review_incomplete",
]
MandatoryStageDecision = Literal[
    "approved",
    "changes_requested",
    "blocked",
    "verified",
    "needs_revision",
    "review_incomplete",
]
REVISION_REQUESTED_STATUSES = frozenset(
    {"changes_requested", "needs_revision"}
)
CLEAR_APPROVAL_STATUSES = frozenset({"approved", "verified"})

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
# Recommended Naming / Result Contracts
ReviewStage = Literal[
    "finding_verification",
    "scope_review",
]
VerificationDecision = Literal["verified", "needs_revision", "blocked"]
ScopeReviewDecision = Literal[
    "approved",
    "changes_requested",
    "blocked",
]

SCOPE_REVIEW_STAGE = "scope_review"
SCOPE_REVIEW_STAGES = frozenset({SCOPE_REVIEW_STAGE})
_LEGACY_REVIEW_STAGE_NAMES = frozenset({"scope_blocker_review"})
_LEGACY_LIFECYCLE_STATUS_NAMES = frozenset({"blocker_review_pending"})
_LEGACY_SCOPE_REVIEW_DECISIONS = frozenset({"approve", "blockers_found"})
_LEGACY_LOOP_STATUS_NAMES = frozenset({"approve", "blockers_found"})

# Suggested State Model for mandatory whole_* loops
MandatoryReviewLifecycleStatus = Literal[
    "review_pending",
    "findings_open",
    "revision_in_progress",
    "verification_pending",
    "findings_closed",
    "scope_review_pending",
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
SUPPORTED_REVIEW_LOOP_TYPES: frozenset[str] = frozenset(
    {"whole_plan", "whole_output", "focused_plan", "focused_output"}
)
SUPPORTED_REVIEW_LOOP_STATUSES: frozenset[str] = frozenset(
    {
        "pending",
        "advisory_pending",
        "approved",
        "changes_requested",
        "blocked",
        "verified",
        "needs_revision",
        "review_incomplete",
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
ChallengeReason = Literal[
    "invalid",
    "duplicate",
    "already_satisfied",
    "conflicts_with_contract",
    "conflicts_with_finding",
    "recommendation_not_viable",
]

OPTIONAL_OWNER_RESPONSES: frozenset[str] = frozenset(
    {"fix", "challenge", "defer", "accept_as_is"}
)
OPTIONAL_NO_VERIFICATION_ACTIONS: frozenset[str] = frozenset(
    {"defer", "accept_as_is"}
)
DEFAULT_OPTIONAL_OWNER_ACTIONS: frozenset[str] = OPTIONAL_NO_VERIFICATION_ACTIONS
REQUIRED_FINDING_OWNER_ACTIONS: frozenset[str] = frozenset({"fix", "challenge"})
CHALLENGE_PROPOSED_DISPOSITIONS: frozenset[str] = frozenset({"invalid", "superseded"})
CHALLENGE_REASONS: frozenset[str] = frozenset(
    {
        "invalid",
        "duplicate",
        "already_satisfied",
        "conflicts_with_contract",
        "conflicts_with_finding",
        "recommendation_not_viable",
    }
)
ACTIONS_REQUIRING_RATIONALE: frozenset[str] = frozenset(
    {"defer", "accept_as_is", "challenge"}
)
CONVERGENCE_WARNING_MIN_SCOPE_REVIEW_ROUNDS = 3
CONVERGENCE_WARNING_RECENT_FINDING_SETS = 3

MANDATORY_REVIEW_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "review_pending": frozenset(
        {
            "findings_open",
            "scope_review_pending",
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
    "findings_closed": frozenset({"scope_review_pending", "limit_reached"}),
    "scope_review_pending": frozenset(
        {"approved", "findings_open", "blocked", "limit_reached", "review_incomplete"}
    ),
    "approved": frozenset(),
    "blocked": frozenset(),
    # Resume after limit extension revives the same loop (budgets preserved).
    "limit_reached": frozenset({"findings_closed", "revision_in_progress"}),
    "review_incomplete": frozenset(
        {
            "review_pending",
            "findings_open",
            "scope_review_pending",
            "verification_pending",
        }
    ),
}


def _reject_legacy_review_stage(stage: str) -> None:
    if stage in _LEGACY_REVIEW_STAGE_NAMES:
        raise ValueError(
            f"legacy review stage {stage!r} is not accepted; use scope_review"
        )


def _reject_legacy_lifecycle_status(status: str) -> None:
    if status in _LEGACY_LIFECYCLE_STATUS_NAMES:
        raise ValueError(
            f"legacy lifecycle status {status!r} is not accepted; "
            "use scope_review_pending"
        )


def _reject_legacy_scope_review_decision(decision: str) -> None:
    if decision in _LEGACY_SCOPE_REVIEW_DECISIONS:
        raise ValueError(
            f"legacy scope review decision {decision!r} is not accepted; "
            "use approved, changes_requested, or blocked"
        )


def validate_review_stage(stage: str | None) -> str | None:
    """Validate a persisted or request review stage name."""

    if stage is None:
        return None
    normalized = str(stage).strip()
    if not normalized:
        return None
    _reject_legacy_review_stage(normalized)
    if normalized not in {
        "initial_review",
        "finding_verification",
        SCOPE_REVIEW_STAGE,
    }:
        raise ValueError(
            "review stage must be one of: initial_review, finding_verification, "
            "scope_review"
        )
    return normalized


def is_scope_review_stage_name(stage: str | None) -> bool:
    return str(stage or "").strip() == SCOPE_REVIEW_STAGE


def validate_lifecycle_status(status: str | None) -> str | None:
    if status is None:
        return None
    normalized = str(status).strip()
    if not normalized:
        return None
    _reject_legacy_lifecycle_status(normalized)
    if normalized not in MANDATORY_REVIEW_TRANSITIONS:
        raise ValueError(
            "lifecycle status must be one of: "
            + ", ".join(sorted(MANDATORY_REVIEW_TRANSITIONS))
        )
    return normalized


def validate_finding_status(status: str) -> FindingStatus:
    normalized = str(status).strip()
    if normalized not in FINDING_DISPOSITIONS:
        raise ValueError(
            "finding status must be one of: "
            + ", ".join(sorted(FINDING_DISPOSITIONS))
        )
    return normalized  # type: ignore[return-value]


def validate_review_loop_status(status: str) -> ReviewLoopStatus:
    normalized = str(status).strip()
    if normalized in _LEGACY_LOOP_STATUS_NAMES:
        raise ValueError(
            f"legacy review loop status {normalized!r} is not accepted"
        )
    if normalized not in SUPPORTED_REVIEW_LOOP_STATUSES:
        raise ValueError(
            "review loop status must be one of: "
            + ", ".join(sorted(SUPPORTED_REVIEW_LOOP_STATUSES))
        )
    return normalized  # type: ignore[return-value]


def validate_review_loop_type(loop_type: str) -> ReviewLoopType:
    normalized = str(loop_type).strip()
    if not normalized:
        raise ValueError("review loop type is required")
    if normalized not in SUPPORTED_REVIEW_LOOP_TYPES:
        raise ValueError(
            "review loop type must be one of: "
            + ", ".join(sorted(SUPPORTED_REVIEW_LOOP_TYPES))
        )
    return normalized  # type: ignore[return-value]


def _require_non_negative_int(value: Any, field_label: str, *, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_label} must be an integer")
    if value < 0:
        raise ValueError(f"{field_label} must be non-negative")
    return value


def validate_scope_review_decision_value(decision: str) -> str:
    normalized = str(decision).strip()
    _reject_legacy_scope_review_decision(normalized)
    if normalized not in {"approved", "changes_requested", "blocked"}:
        raise ValueError(
            "scope review decision must be one of: approved, changes_requested, "
            "blocked"
        )
    return normalized


def normalize_exhausted_budget(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if normalized == "blocker_review":
        raise ValueError(
            "legacy exhausted_budget value blocker_review is not accepted; "
            "use scope_review"
        )
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
    family_id: str | None = None
    instance_ref: ArtifactRef | None = None

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
        if self.family_id is not None:
            payload["family_id"] = self.family_id
        if self.instance_ref is not None:
            payload["instance_ref"] = artifact_ref_to_dict(self.instance_ref)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ReviewFinding:
        severity = _severity_from_payload(payload)
        category_raw = payload.get("category")
        if category_raw is None or not str(category_raw).strip():
            raise ValueError("finding requires category")
        category = validate_finding_category(str(category_raw))

        if "recommended_change" not in payload:
            raise ValueError("finding requires recommended_change")
        recommended_change = str(payload.get("recommended_change") or "")
        if payload.get("importance") is not None or payload.get("required_change") is not None:
            raise ValueError(
                "legacy finding fields importance and required_change are not accepted"
            )

        reopens_raw = payload.get("reopens_finding_id")
        reopens_finding_id = (
            str(reopens_raw).strip()
            if reopens_raw is not None and str(reopens_raw).strip()
            else None
        )
        evidence_raw = payload.get("evidence") or []
        if not isinstance(evidence_raw, list):
            raise ValueError("finding evidence must be a list")
        evidence = []
        for index, item in enumerate(evidence_raw):
            if not isinstance(item, str):
                raise ValueError(f"finding evidence[{index}] must be a string")
            evidence.append(item)

        target_refs_raw = payload.get("target_refs") or []
        if not isinstance(target_refs_raw, list):
            raise ValueError("finding target_refs must be a list")
        target_refs: list[str] = []
        for index, ref in enumerate(target_refs_raw):
            if not isinstance(ref, str):
                raise ValueError(f"finding target_refs[{index}] must be a string")
            target_refs.append(ref)

        family_raw = payload.get("family_id")
        family_id = (
            str(family_raw).strip()
            if family_raw is not None and str(family_raw).strip()
            else None
        )
        instance_ref_raw = payload.get("instance_ref")
        instance_ref = (
            parse_artifact_ref(instance_ref_raw)
            if isinstance(instance_ref_raw, Mapping)
            else None
        )

        return cls(
            id=str(payload["id"]),
            severity=severity,
            category=category,
            target_refs=target_refs,
            issue=str(payload.get("issue") or ""),
            recommended_change=recommended_change,
            status=validate_finding_status(str(payload.get("status") or "unresolved")),
            evidence=evidence,
            reopens_finding_id=reopens_finding_id,
            family_id=family_id,
            instance_ref=instance_ref,
        )


def _severity_from_payload(payload: Mapping[str, Any]) -> ReviewSeverity:
    if payload.get("severity") is None or not str(payload.get("severity")).strip():
        raise ValueError("finding requires severity")
    if payload.get("importance") is not None:
        raise ValueError("legacy finding field importance is not accepted")
    return validate_review_severity(str(payload["severity"]))


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
    challenge_reason: ChallengeReason | None = None
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
        if self.challenge_reason is not None:
            payload["challenge_reason"] = self.challenge_reason
        if self.superseded_by_finding_id is not None:
            payload["superseded_by_finding_id"] = self.superseded_by_finding_id
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> FindingAction:
        return parse_finding_action(payload)


def validate_finding_owner_action(action: str) -> FindingOwnerAction:
    normalized = str(action).strip()
    if normalized not in OPTIONAL_OWNER_RESPONSES:
        raise ValueError(
            "finding action must be one of: "
            + ", ".join(sorted(OPTIONAL_OWNER_RESPONSES))
        )
    return normalized  # type: ignore[return-value]


def validate_challenge_reason(reason: str) -> ChallengeReason:
    normalized = str(reason).strip()
    if normalized not in CHALLENGE_REASONS:
        raise ValueError(
            "challenge_reason must be one of: "
            + ", ".join(sorted(CHALLENGE_REASONS))
        )
    return normalized  # type: ignore[return-value]


def validate_default_optional_action(action: str) -> FindingOwnerAction:
    normalized = str(action).strip()
    if normalized not in DEFAULT_OPTIONAL_OWNER_ACTIONS:
        raise ValueError(
            "default_optional_action must be one of: "
            + ", ".join(sorted(DEFAULT_OPTIONAL_OWNER_ACTIONS))
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
        challenge_reason_raw = payload.get("challenge_reason")
        if challenge_reason_raw is None or not str(challenge_reason_raw).strip():
            raise ValueError("challenge requires challenge_reason")
        challenge_reason = validate_challenge_reason(str(challenge_reason_raw))
        if proposed_disposition == "superseded" and not superseded_by_finding_id:
            raise ValueError(
                "challenge with proposed_disposition superseded requires "
                "superseded_by_finding_id"
            )
    else:
        challenge_reason = None
        challenge_reason_raw = payload.get("challenge_reason")
        if challenge_reason_raw is not None and str(challenge_reason_raw).strip():
            raise ValueError(
                "challenge_reason is only valid for challenge actions"
            )
        if proposed_disposition is not None or superseded_by_finding_id is not None:
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
        challenge_reason=challenge_reason if action == "challenge" else None,
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


def uses_finding_family_protocol(loop: ReviewLoop) -> bool:
    """True when discovery/verification must use finding families and audit attestation."""

    return loop.review_contract_version == CURRENT_REVIEW_CONTRACT_VERSION


def supports_optional_families(loop: ReviewLoop) -> bool:
    """True when the loop type may use optional focused finding families."""

    return loop.type in {"focused_plan", "focused_output"}


def loop_uses_finding_families(loop: ReviewLoop) -> bool:
    """True when the loop persists finding-family state."""

    if uses_finding_family_protocol(loop):
        return True
    return supports_optional_families(loop) and bool(loop.finding_families)


def is_mandatory_whole_review(loop: ReviewLoop) -> bool:
    """True for mandatory whole-plan or whole-output review loops."""

    return loop.type in {"whole_plan", "whole_output"}


def parse_review_version_fields(payload: Mapping[str, Any]) -> tuple[int, int]:
    """Parse persisted review record and contract schema versions (v2-only)."""

    if "review_schema_version" in payload:
        raise ValueError(
            "legacy field review_schema_version is not accepted; "
            "use review_record_schema_version"
        )
    if "review_record_schema_version" not in payload:
        raise ValueError("review_record_schema_version is required")
    if "review_contract_version" not in payload:
        raise ValueError("review_contract_version is required")

    record_version = _require_non_negative_int(
        payload["review_record_schema_version"],
        "review_record_schema_version",
    )
    contract_version = _require_non_negative_int(
        payload["review_contract_version"],
        "review_contract_version",
    )

    if record_version not in SUPPORTED_REVIEW_RECORD_SCHEMA_VERSIONS:
        raise ValueError(
            f"unsupported review_record_schema_version: {record_version!r}; "
            f"supported: {sorted(SUPPORTED_REVIEW_RECORD_SCHEMA_VERSIONS)}"
        )
    if contract_version not in SUPPORTED_REVIEW_CONTRACT_VERSIONS:
        raise ValueError(
            f"unsupported review_contract_version: {contract_version!r}; "
            f"supported: {sorted(SUPPORTED_REVIEW_CONTRACT_VERSIONS)}"
        )
    return record_version, contract_version


@dataclass
class ReviewLoop:
    id: str
    type: ReviewLoopType
    target_revision: int
    scope: dict[str, Any]
    status: ReviewLoopStatus = "pending"
    findings: list[ReviewFinding] = field(default_factory=list)
    revision_cycles: int = 0
    revision: int = 0
    approved_digests: dict[str, str] | None = None
    reviewer_binding: SessionBinding | None = None
    # Mandatory review loop fields (optional; focused loops leave unset).
    lifecycle_status: MandatoryReviewLifecycleStatus | None = None
    active_stage: ReviewStage | None = None
    finding_set_id: str | None = None
    scope_review_rounds: int = 0
    verification_result: dict[str, Any] | None = None
    scope_review_result: dict[str, Any] | None = None
    exhausted_budget: ExhaustedReviewBudget | None = None
    # Severity-threshold review fields (proposal review-record model).
    review_record_schema_version: int = CURRENT_REVIEW_RECORD_SCHEMA_VERSION
    review_contract_version: int = CURRENT_REVIEW_CONTRACT_VERSION
    revise_at: ReviewSeverity | None = None
    finding_actions: list[FindingAction] = field(default_factory=list)
    review_incomplete: dict[str, Any] | None = None
    advisory_handoffs_completed: list[str] = field(default_factory=list)
    finding_ids_by_set: dict[str, list[str]] = field(default_factory=dict)
    finding_families: list[FindingFamily] = field(default_factory=list)
    family_sweeps: list[FamilySweepRecord] = field(default_factory=list)
    audit_runs: list[AuditAttestationRun] = field(default_factory=list)
    gate_agent_turns: int = 0

    @property
    def reviewer_session_id(self) -> str | None:
        return binding_provider_session_id(self.reviewer_binding)

    def to_dict(self) -> dict[str, Any]:
        binding = self.reviewer_binding
        payload: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "target_revision": self.target_revision,
            "scope": dict(self.scope),
            "status": self.status,
            "findings": [finding.to_dict() for finding in self.findings],
            "revision_cycles": self.revision_cycles,
            "revision": int(self.revision),
            "review_record_schema_version": self.review_record_schema_version,
            "review_contract_version": self.review_contract_version,
            "finding_actions": [action.to_dict() for action in self.finding_actions],
            "review_incomplete": (
                dict(self.review_incomplete)
                if self.review_incomplete is not None
                else None
            ),
            "advisory_handoffs_completed": list(self.advisory_handoffs_completed),
        }
        if self.finding_ids_by_set:
            payload["finding_ids_by_set"] = {
                key: list(value) for key, value in self.finding_ids_by_set.items()
            }
        if binding is not None:
            payload["reviewer_binding"] = binding.to_dict()
        if self.revise_at is not None:
            payload["revise_at"] = self.revise_at
        if self.approved_digests is not None:
            payload["approved_digests"] = dict(self.approved_digests)
        if self.lifecycle_status is not None:
            payload["lifecycle_status"] = self.lifecycle_status
        if self.active_stage is not None:
            payload["active_stage"] = self.active_stage
        if self.finding_set_id is not None:
            payload["finding_set_id"] = self.finding_set_id
        rounds = int(self.scope_review_rounds)
        if rounds:
            payload["scope_review_rounds"] = rounds
        if self.verification_result is not None:
            payload["verification_result"] = dict(self.verification_result)
        if self.scope_review_result is not None:
            payload["scope_review_result"] = dict(self.scope_review_result)
        if self.exhausted_budget is not None:
            payload["exhausted_budget"] = normalize_exhausted_budget(self.exhausted_budget)
        if self.finding_families:
            payload["finding_families"] = [
                family.to_dict() for family in self.finding_families
            ]
        if self.family_sweeps:
            payload["family_sweeps"] = [
                sweep.to_dict() for sweep in self.family_sweeps
            ]
        if self.audit_runs:
            payload["audit_runs"] = [run.to_dict() for run in self.audit_runs]
        payload["gate_agent_turns"] = int(self.gate_agent_turns)
        return payload

    def with_reviewer_session_released(self) -> ReviewLoop:
        """Release reviewer binding so orchestration allocates a fresh session."""

        binding = self.reviewer_binding
        if binding is None:
            return replace(self, reviewer_binding=None)
        if binding.state == "unbound" and not binding.provider_session_id:
            return replace(self, reviewer_binding=binding)
        if not binding.provider_session_id:
            return replace(self, reviewer_binding=None)
        released = binding.released_for_reallocation()
        return replace(self, reviewer_binding=released)

    def with_reviewer_provider_session_id(
        self,
        provider_session_id: str,
        *,
        provider: str | None = "cursor",
        model: str | None = None,
    ) -> ReviewLoop:
        binding = self.reviewer_binding
        if binding is None:
            binding = new_session_binding(
                role="reviewer",
                kind="reviewer",
                state="starting",
            )
        updated_binding = binding.with_provider_session_id(
            provider_session_id,
            provider=provider,
            model=model,
        )
        return replace(
            self,
            reviewer_binding=updated_binding,
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ReviewLoop:
        raw_type = payload.get("type")
        loop_type = validate_review_loop_type(str(raw_type or ""))

        findings_raw = payload.get("findings") or []
        if not isinstance(findings_raw, list):
            raise ValueError("findings must be a list")
        findings: list[ReviewFinding] = []
        for index, item in enumerate(findings_raw):
            if not isinstance(item, dict):
                raise ValueError(f"findings[{index}] must be an object")
            findings.append(ReviewFinding.from_dict(item))
        approved = payload.get("approved_digests")
        approved_digests = (
            {str(key): str(value) for key, value in approved.items()}
            if isinstance(approved, dict)
            else None
        )
        lifecycle_raw = payload.get("lifecycle_status")
        lifecycle_status = validate_lifecycle_status(
            str(lifecycle_raw).strip()
            if lifecycle_raw is not None and str(lifecycle_raw).strip()
            else None
        )
        stage_raw = payload.get("active_stage")
        active_stage = validate_review_stage(
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
        if blocker_raw is None and payload.get("blocker_review_result") is not None:
            raise ValueError(
                "legacy field blocker_review_result is not accepted; use scope_review_result"
            )
        scope_review_result = (
            dict(blocker_raw) if isinstance(blocker_raw, dict) else None
        )
        exhausted_raw = payload.get("exhausted_budget")
        exhausted_budget = normalize_exhausted_budget(
            str(exhausted_raw).strip()
            if exhausted_raw is not None and str(exhausted_raw).strip()
            else None
        )
        rounds_raw = payload.get("scope_review_rounds")
        if rounds_raw is None and payload.get("blocker_review_rounds") is not None:
            raise ValueError(
                "legacy field blocker_review_rounds is not accepted; "
                "use scope_review_rounds"
            )
        scope_review_rounds = _require_non_negative_int(
            rounds_raw,
            "scope_review_rounds",
        )
        review_record_schema_version, review_contract_version = (
            parse_review_version_fields(payload)
        )

        revise_raw = payload.get("revise_at")
        revise_at: ReviewSeverity | None = None
        if revise_raw is not None and str(revise_raw).strip():
            revise_at = validate_review_severity(str(revise_raw))
        if revise_at is None and loop_type in BUILTIN_REVISE_AT:
            raise ValueError(
                f"review loop {payload.get('id')!r} is missing required revise_at"
            )

        status_raw = validate_review_loop_status(str(payload.get("status") or "pending"))

        finding_actions = []
        for index, item in enumerate(payload.get("finding_actions") or []):
            if not isinstance(item, dict):
                raise ValueError(f"finding_actions[{index}] must be an object")
            finding_actions.append(parse_finding_action(item))
        incomplete_raw = payload.get("review_incomplete")
        review_incomplete = (
            dict(incomplete_raw) if isinstance(incomplete_raw, dict) else None
        )
        advisory_handoffs_completed = [
            str(item).strip()
            for item in (payload.get("advisory_handoffs_completed") or [])
            if str(item).strip()
        ]
        finding_ids_by_set: dict[str, list[str]] = {}
        raw_ids_by_set = payload.get("finding_ids_by_set")
        if raw_ids_by_set is None:
            raw_ids_by_set = {}
        if not isinstance(raw_ids_by_set, dict):
            raise ValueError("finding_ids_by_set must be an object")
        for key, value in raw_ids_by_set.items():
            set_id = str(key).strip()
            if not set_id:
                raise ValueError("finding_ids_by_set keys must be non-empty strings")
            if not isinstance(value, list):
                raise ValueError(f"finding_ids_by_set[{set_id!r}] must be a list")
            normalized_ids: list[str] = []
            for index, item in enumerate(value):
                if not isinstance(item, str) or not item.strip():
                    raise ValueError(
                        f"finding_ids_by_set[{set_id!r}][{index}] must be a non-empty string"
                    )
                normalized_ids.append(item.strip())
            finding_ids_by_set[set_id] = normalized_ids
        binding_raw = payload.get("reviewer_binding")
        reviewer_binding: SessionBinding | None = None
        if isinstance(binding_raw, dict) and binding_raw.get("session_instance_id"):
            reviewer_binding = SessionBinding.from_dict(binding_raw)
        if "reviewer_session_id" in payload:
            raise ValueError(
                "legacy review field reviewer_session_id is not accepted; use reviewer_binding"
            )

        finding_families = parse_finding_families(payload.get("finding_families"))
        family_sweeps = parse_family_sweeps(payload.get("family_sweeps"))
        audit_runs = parse_audit_runs(payload.get("audit_runs"))

        return cls(
            id=str(payload["id"]),
            type=loop_type,  # type: ignore[arg-type]
            target_revision=_require_non_negative_int(
                payload.get("target_revision"),
                "target_revision",
            ),
            scope=dict(payload.get("scope") or {}),
            status=status_raw,  # type: ignore[arg-type]
            findings=findings,
            revision_cycles=_require_non_negative_int(
                payload.get("revision_cycles"),
                "revision_cycles",
            ),
            revision=_require_non_negative_int(payload.get("revision"), "revision"),
            approved_digests=approved_digests,
            reviewer_binding=reviewer_binding,
            lifecycle_status=lifecycle_status,  # type: ignore[arg-type]
            active_stage=active_stage,  # type: ignore[arg-type]
            finding_set_id=finding_set_id,
            scope_review_rounds=scope_review_rounds,
            verification_result=verification_result,
            scope_review_result=scope_review_result,
            exhausted_budget=exhausted_budget,  # type: ignore[arg-type]
            review_record_schema_version=review_record_schema_version,
            review_contract_version=review_contract_version,
            revise_at=revise_at,
            finding_actions=finding_actions,
            review_incomplete=review_incomplete,
            advisory_handoffs_completed=advisory_handoffs_completed,
            finding_ids_by_set=finding_ids_by_set,
            finding_families=finding_families,
            family_sweeps=family_sweeps,
            audit_runs=audit_runs,
            gate_agent_turns=_require_non_negative_int(
                payload.get("gate_agent_turns"),
                "gate_agent_turns",
            ),
        )


_REVIEW_GATE_LIMIT_DEFAULTS = {"max_agent_turns_per_gate": 5}


def review_gate_limits_from_config(
    config: Mapping[str, Any] | None,
) -> dict[str, int]:
    """Load per-gate reviewer turn budget from resolved run config."""

    section = ((config or {}).get("limits") or {}).get("review")
    if section is not None and not isinstance(section, Mapping):
        raise ValueError("limits.review must be an object")
    mapping = section if isinstance(section, Mapping) else {}
    return {
        "max_agent_turns_per_gate": int(
            mapping.get(
                "max_agent_turns_per_gate",
                _REVIEW_GATE_LIMIT_DEFAULTS["max_agent_turns_per_gate"],
            )
        ),
    }


def increment_gate_agent_turns(loop: ReviewLoop) -> ReviewLoop:
    return replace(loop, gate_agent_turns=int(loop.gate_agent_turns) + 1)


def reset_gate_agent_turns(loop: ReviewLoop) -> ReviewLoop:
    return replace(loop, gate_agent_turns=0)


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


def is_limit_reached_review_loop(loop: ReviewLoop) -> bool:
    """True when a mandatory loop paused on Loop Bounds exhaustion."""

    return (
        is_mandatory_review_loop(loop)
        and loop.lifecycle_status == "limit_reached"
    )


def is_terminal_review_loop(loop: ReviewLoop) -> bool:
    # limit_reached uses status=blocked, so it is terminal for mutation/conflict
    # purposes. Resume selection continues that loop via _get_or_create_active_loop.
    if loop.status == "blocked":
        return True
    if is_mandatory_review_loop(loop):
        return loop.lifecycle_status == "approved"
    return loop.status == "approved"


def is_review_respond_closed(loop: ReviewLoop) -> bool:
    """True when ``review respond`` must reject further reviewer decisions."""

    # limit_reached uses status=blocked, so is_terminal_review_loop covers it.
    if is_terminal_review_loop(loop):
        return True
    if (
        is_mandatory_review_loop(loop)
        and loop.status == "approved"
        and loop.lifecycle_status == "approved"
        and is_scope_review_stage_name(loop.active_stage)
    ):
        return True
    blocker = loop.scope_review_result
    if is_mandatory_review_loop(loop) and isinstance(blocker, dict):
        decision_raw = str(blocker.get("decision") or "").strip()
        if decision_raw:
            try:
                decision = validate_scope_review_decision_value(decision_raw)
            except ValueError:
                decision = ""
            else:
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


def is_known_finding_status(status: str) -> bool:
    return str(status).strip() in FINDING_DISPOSITIONS


def is_open_finding_status(status: str) -> bool:
    """True when a finding still requires verification/revision attention."""

    normalized = str(status).strip()
    return normalized in OPEN_FINDING_DISPOSITIONS


def is_unresolved_finding_status(status: str) -> bool:
    """True when a finding blocks progress (open or unknown/corrupt status)."""

    normalized = str(status).strip()
    if normalized in OPEN_FINDING_DISPOSITIONS:
        return True
    return normalized not in FINDING_DISPOSITIONS


def findings_have_unknown_status(findings: Sequence[ReviewFinding]) -> bool:
    return any(not is_known_finding_status(finding.status) for finding in findings)


def loop_revise_at(loop: ReviewLoop) -> ReviewSeverity:
    """Return the loop's persisted revise_at threshold."""

    if loop.revise_at is None:
        raise ValueError(f"review loop {loop.id!r} is missing required revise_at")
    return loop.revise_at


def open_findings(findings: Sequence[ReviewFinding]) -> list[ReviewFinding]:
    return [
        finding
        for finding in findings
        if is_unresolved_finding_status(finding.status)
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


def scoped_finding_actions(
    finding_actions: Sequence[FindingAction],
    finding_set_id: str | None,
) -> list[FindingAction]:
    """Return actions recorded for ``finding_set_id`` when set is provided."""

    if not finding_set_id:
        return list(finding_actions)
    return [
        action
        for action in finding_actions
        if action.finding_set_id == finding_set_id
    ]


def effective_owner_actions(
    finding_actions: Sequence[FindingAction],
    *,
    finding_set_id: str | None = None,
) -> dict[str, FindingAction]:
    """Latest owner action per finding within the scoped finding set."""

    effective: dict[str, FindingAction] = {}
    for action in scoped_finding_actions(finding_actions, finding_set_id):
        effective[action.finding_id] = action
    return effective


def open_optional_findings_missing_owner_response(
    findings: Sequence[ReviewFinding],
    finding_actions: Sequence[FindingAction],
    threshold: ReviewSeverity,
    *,
    finding_set_id: str | None = None,
) -> list[ReviewFinding]:
    """Optional open findings lacking any owner response for the active finding set."""

    effective = effective_owner_actions(
        finding_actions,
        finding_set_id=finding_set_id,
    )
    responded = {
        finding_id
        for finding_id, action in effective.items()
        if action.action in OPTIONAL_OWNER_RESPONSES
    }
    return [
        finding
        for finding in optional_open_findings(findings, threshold)
        if finding.id not in responded
    ]


def open_optional_findings_missing_owner_response_in_active_set(
    findings: Sequence[ReviewFinding],
    finding_actions: Sequence[FindingAction],
    threshold: ReviewSeverity,
    *,
    finding_set_id: str | None = None,
    finding_ids_in_active_set: set[str] | None = None,
) -> list[ReviewFinding]:
    """Optional findings needing owner response for the current discovery pass.

    When ``finding_ids_in_active_set`` is empty, carried optional findings from
    prior passes do not require a new advisory handoff. When ``None``, every
    open optional without a scoped response is treated as missing (legacy).
    """

    if finding_ids_in_active_set is not None and not finding_ids_in_active_set:
        return []
    missing = open_optional_findings_missing_owner_response(
        findings,
        finding_actions,
        threshold,
        finding_set_id=finding_set_id,
    )
    if finding_ids_in_active_set is None:
        return missing
    return [finding for finding in missing if finding.id in finding_ids_in_active_set]


def active_finding_ids_for_advisory_policy(
    loop: ReviewLoop,
    *,
    reported_finding_ids: Iterable[str] | None = None,
) -> set[str] | None:
    """Finding ids in the current discovery pass for advisory/outcome policy.

    Returns ``None`` for legacy loops without ``finding_ids_by_set`` tracking
    (every open optional counts). Returns an empty set when the active pass has
    no reported findings yet (carried optionals do not re-trigger handoff).
    """

    finding_set_id = str(loop.finding_set_id or "").strip()
    active = set(loop.finding_ids_by_set.get(finding_set_id, []))
    if reported_finding_ids:
        active |= set(reported_finding_ids)
    if not loop.finding_ids_by_set:
        return None
    if not active:
        return set()
    return active


def open_optional_findings_blocking_approval(
    findings: Sequence[ReviewFinding],
    finding_actions: Sequence[FindingAction],
    threshold: ReviewSeverity,
    *,
    finding_set_id: str | None = None,
) -> list[ReviewFinding]:
    """Optional open findings that block approval without reviewer verification.

    Approval may proceed only when every optional finding has defer or
    accept_as_is. Findings with fix/challenge or no response remain blocking.
    """

    effective = effective_owner_actions(
        finding_actions,
        finding_set_id=finding_set_id,
    )
    no_verification = {
        finding_id
        for finding_id, action in effective.items()
        if action.action in OPTIONAL_NO_VERIFICATION_ACTIONS
    }
    return [
        finding
        for finding in optional_open_findings(findings, threshold)
        if finding.id not in no_verification
    ]


def optional_finding_ids_missing_owner_response(
    findings: Sequence[ReviewFinding],
    finding_actions: Sequence[FindingAction],
    threshold: ReviewSeverity,
    *,
    finding_set_id: str | None = None,
) -> list[str]:
    return [
        finding.id
        for finding in open_optional_findings_missing_owner_response(
            findings,
            finding_actions,
            threshold,
            finding_set_id=finding_set_id,
        )
    ]


def optional_finding_ids_requiring_verification(
    findings: Sequence[ReviewFinding],
    finding_actions: Sequence[FindingAction],
    threshold: ReviewSeverity,
    *,
    finding_set_id: str | None = None,
) -> list[str]:
    """Optional open findings with fix/challenge responses awaiting verification."""

    effective = effective_owner_actions(
        finding_actions,
        finding_set_id=finding_set_id,
    )
    optional_ids = {
        finding.id for finding in optional_open_findings(findings, threshold)
    }
    return sorted(
        finding_id
        for finding_id in optional_ids
        if finding_id in effective
        and effective[finding_id].action in {"fix", "challenge"}
    )


def findings_permit_approval(
    findings: Sequence[ReviewFinding],
    finding_actions: Sequence[FindingAction],
    threshold: ReviewSeverity,
    *,
    finding_set_id: str | None = None,
) -> bool:
    """True when required findings are clear and optionals need no verification."""

    if findings_have_unknown_status(findings):
        return False
    if required_open_findings(findings, threshold):
        return False
    if open_optional_findings_blocking_approval(
        findings,
        finding_actions,
        threshold,
        finding_set_id=finding_set_id,
    ):
        return False
    return True


def findings_permit_approval_for_loop(
    loop: ReviewLoop,
    findings: Sequence[ReviewFinding] | None = None,
) -> bool:
    """True when the loop may approve, scoped to the active discovery pass."""

    resolved = loop.findings if findings is None else findings
    if findings_have_unknown_status(resolved):
        return False
    threshold = loop_revise_at(loop)
    if required_open_findings(resolved, threshold):
        return False
    active = active_finding_ids_for_advisory_policy(loop)
    if active is not None and not active:
        return True
    finding_set_id = str(loop.finding_set_id or "").strip() or None
    if active is None:
        return findings_permit_approval(
            resolved,
            loop.finding_actions,
            threshold,
            finding_set_id=None,
        )
    blocking = open_optional_findings_blocking_approval(
        resolved,
        loop.finding_actions,
        threshold,
        finding_set_id=finding_set_id,
    )
    active_blocking = [finding for finding in blocking if finding.id in active]
    return not active_blocking


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
    elif normalized not in OPTIONAL_OWNER_RESPONSES:
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
    finding_ids_in_active_set: set[str] | None = None,
) -> dict[str, Any]:
    """Derived threshold/requirement state for review responses and events."""

    required_ids = required_open_finding_ids(findings, threshold)
    optional_ids = optional_open_finding_ids(findings, threshold)
    missing_response_ids = [
        finding.id
        for finding in open_optional_findings_missing_owner_response_in_active_set(
            findings,
            finding_actions,
            threshold,
            finding_set_id=finding_set_id,
            finding_ids_in_active_set=finding_ids_in_active_set,
        )
    ]
    verification_required_ids = optional_finding_ids_requiring_verification(
        findings,
        finding_actions,
        threshold,
        finding_set_id=finding_set_id,
    )
    if finding_ids_in_active_set is not None:
        if not finding_ids_in_active_set:
            verification_required_ids = []
        else:
            verification_required_ids = [
                finding_id
                for finding_id in verification_required_ids
                if finding_id in finding_ids_in_active_set
            ]
    return {
        "revise_at": threshold,
        "finding_count": len(findings),
        "required_open_finding_count": len(required_ids),
        "optional_open_finding_count": len(optional_ids),
        "required_open_finding_ids": required_ids,
        "optional_open_finding_ids": optional_ids,
        "optional_finding_ids_missing_owner_response": missing_response_ids,
        "optional_finding_ids_requiring_verification": verification_required_ids,
    }


def policy_observability_fields_for_loop(loop: ReviewLoop) -> dict[str, Any]:
    """Observability fields scoped to the loop's active discovery pass."""

    threshold = loop_revise_at(loop)
    return policy_observability_fields(
        loop.findings,
        loop.finding_actions,
        threshold,
        finding_set_id=loop.finding_set_id,
        finding_ids_in_active_set=active_finding_ids_for_advisory_policy(loop),
    )


def required_unresolved_finding_ids(
    findings: list[ReviewFinding],
    *,
    revise_at: ReviewSeverity,
) -> list[str]:
    """Return open finding ids at or above ``revise_at``."""

    return required_open_finding_ids(findings, revise_at)


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
        required_unresolved_finding_ids(
            loop.findings,
            revise_at=loop_revise_at(loop),
        )
    )


_WHOLE_SCOPE_KINDS = frozenset({"whole_plan", "whole_output"})


def validate_focused_scope(scope: Any, review_type: str) -> dict[str, Any]:
    """Validate a bounded focused-review scope (proposal §5.1)."""

    if not isinstance(scope, dict):
        raise ValueError("scope must be an object")

    kind = str(scope.get("kind") or review_type).strip()
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
    *,
    review_type: str | None = None,
) -> None:
    allowed = {str(item_id) for item_id in (scope.get("item_ids") or [])}
    if not allowed:
        raise ValueError("focused review scope is missing item_ids")

    allowed_kinds = None
    if review_type in {"focused_plan", "focused_output"}:
        from top_down_planning.domain.artifact_refs import focused_allowed_ref_kinds

        allowed_kinds = focused_allowed_ref_kinds(review_type)

    for finding in findings:
        for ref in finding.target_refs:
            if str(ref) not in allowed:
                raise ValueError(
                    f"finding {finding.id} target_ref {ref!r} is outside declared scope"
                )
        if finding.instance_ref is not None and allowed_kinds is not None:
            from top_down_planning.domain.artifact_refs import (
                validate_artifact_ref_within_scope,
            )

            validate_artifact_ref_within_scope(
                finding.instance_ref,
                allowed_item_ids=allowed,
                allowed_kinds=allowed_kinds,
                context=f"finding {finding.id} instance_ref",
            )


def validate_finding_families_within_scope(
    loop: ReviewLoop,
    scope: dict[str, Any],
    *,
    review_type: str,
) -> None:
    """Ensure optional focused family candidate_refs stay within scope.item_ids."""

    if not loop.finding_families:
        return

    allowed = {str(item_id) for item_id in (scope.get("item_ids") or [])}
    if not allowed:
        raise ValueError("focused review scope is missing item_ids")

    from top_down_planning.domain.artifact_refs import (
        focused_allowed_ref_kinds,
        validate_artifact_ref_within_scope,
    )

    allowed_kinds = focused_allowed_ref_kinds(review_type)
    for family in loop.finding_families:
        for index, ref in enumerate(family.candidate_refs):
            validate_artifact_ref_within_scope(
                ref,
                allowed_item_ids=allowed,
                allowed_kinds=allowed_kinds,
                context=f"family {family.id} candidate_refs[{index}]",
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
            required_unresolved_finding_ids(
                loop.findings,
                revise_at=loop_revise_at(loop),
            )
        )

    return blocked


def required_unresolved_finding_ids_from_payload(review: dict[str, Any]) -> list[str]:
    findings_raw = review.get("findings") or []
    if not isinstance(findings_raw, list):
        raise ValueError("findings must be a list")
    findings: list[ReviewFinding] = []
    for index, item in enumerate(findings_raw):
        if not isinstance(item, dict):
            raise ValueError(f"findings[{index}] must be an object")
        findings.append(ReviewFinding.from_dict(item))
    revise_raw = review.get("revise_at")
    if revise_raw is None or not str(revise_raw).strip():
        raise ValueError(
            "review record requires revise_at for threshold-aware unresolved finding ids"
        )
    revise_at = validate_review_severity(str(revise_raw))
    return required_unresolved_finding_ids(findings, revise_at=revise_at)


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


_ACTIVE_REVIEW_LOOP_TYPES = frozenset(
    {"whole_plan", "whole_output", "focused_plan", "focused_output"}
)


def find_conflicting_active_review_loops(
    reviews: list[dict[str, Any]],
) -> list[str]:
    """Return active non-terminal loop ids when more than one concurrent loop exists."""

    active_ids: list[str] = []
    for payload in reviews:
        loop_type = str(payload.get("type") or "")
        if loop_type not in _ACTIVE_REVIEW_LOOP_TYPES:
            continue
        loop = ReviewLoop.from_dict(payload)
        if is_terminal_review_loop(loop):
            continue
        active_ids.append(loop.id)
    if len(active_ids) > 1:
        return active_ids
    return []


def claimed_fix_open_findings(loop: ReviewLoop) -> list[ReviewFinding]:
    """Open findings the primary agent claimed to fix for the active finding set."""

    fix_ids = {
        action.finding_id
        for action in loop.finding_actions
        if action.action == "fix"
        and (
            loop.finding_set_id is None
            or action.finding_set_id is None
            or action.finding_set_id == loop.finding_set_id
        )
    }
    return [finding for finding in open_findings(loop.findings) if finding.id in fix_ids]


def evidence_revision_target_ids_for_loop(loop: ReviewLoop) -> set[str]:
    """Required open targets plus voluntary claimed-fix targets."""

    targets: set[str] = set()
    for finding in required_open_findings(loop.findings, loop_revise_at(loop)):
        targets.update(str(ref) for ref in finding.target_refs)
    for finding in claimed_fix_open_findings(loop):
        targets.update(str(ref) for ref in finding.target_refs)
    return targets


def whole_output_revision_target_ids(reviews: list[dict[str, Any]]) -> set[str]:
    """Plan item ids for mandatory + voluntary evidence revision on whole-output."""

    loop = find_active_review_loop(reviews, "whole_output")
    if loop is None:
        return set()
    return evidence_revision_target_ids_for_loop(loop)


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
    targets = evidence_revision_target_ids_for_loop(loop)
    if not targets:
        required = required_open_findings(loop.findings, loop_revise_at(loop))
        if not required and not claimed_fix_open_findings(loop):
            return set()
        return scope_items
    return targets & scope_items if scope_items else targets


def find_whole_output_approval(
    reviews: list[dict[str, Any]],
    output_revision: int,
) -> dict[str, Any] | None:
    for payload in reversed(reviews):
        if payload.get("type") != "whole_output":
            continue
        if str(payload.get("status") or "").strip() != "approved":
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
    if status != "approved":
        return False
    if payload.get("lifecycle_status") != "approved":
        return False
    if not is_scope_review_stage_name(str(payload.get("active_stage") or "")):
        return False
    blocker_raw = payload.get("scope_review_result")
    if not isinstance(blocker_raw, dict):
        blocker_raw = payload.get("scope_review_result")
    if not isinstance(blocker_raw, dict):
        return False
    if not is_scope_review_stage_name(str(blocker_raw.get("stage") or "")):
        return False
    decision_raw = str(blocker_raw.get("decision") or "").strip()
    if not decision_raw:
        return False
    try:
        decision = validate_scope_review_decision_value(decision_raw)
    except ValueError:
        return False
    if decision != "approved":
        return False
    if not str(blocker_raw.get("target_digest") or "").strip():
        return False
    findings_raw = payload.get("findings") or []
    if not isinstance(findings_raw, list):
        raise ValueError("findings must be a list")
    findings: list[ReviewFinding] = []
    for index, item in enumerate(findings_raw):
        if not isinstance(item, dict):
            raise ValueError(f"findings[{index}] must be an object")
        findings.append(ReviewFinding.from_dict(item))
    finding_actions_raw = payload.get("finding_actions") or []
    if not isinstance(finding_actions_raw, list):
        raise ValueError("finding_actions must be a list")
    finding_actions = []
    for index, item in enumerate(finding_actions_raw):
        if not isinstance(item, dict):
            raise ValueError(f"finding_actions[{index}] must be an object")
        finding_actions.append(parse_finding_action(item))
    revise_raw = payload.get("revise_at")
    if revise_raw is None or not str(revise_raw).strip():
        raise ValueError("mandatory gate approval record requires revise_at")
    revise_at = validate_review_severity(str(revise_raw))
    if not findings_permit_approval(findings, finding_actions, revise_at):
        return False
    return True


def find_whole_plan_approval(
    reviews: list[dict[str, Any]],
    plan_revision: int,
) -> dict[str, Any] | None:
    for payload in reversed(reviews):
        if payload.get("type") != "whole_plan":
            continue
        if str(payload.get("status") or "").strip() != "approved":
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
    echo the same identifier, or when a finding_verification / scope_review
    stage already allocated an id. Otherwise allocates a new id for a fresh
    discovery pass.
    """

    if loop.review_incomplete is not None and loop.finding_set_id:
        return loop, loop.finding_set_id
    if loop.finding_set_id and loop.active_stage in {
        "finding_verification",
        SCOPE_REVIEW_STAGE,
    }:
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
                "rediscovery must use a new id; the service derives reopen lineage "
                "from fingerprint and instance_ref after scope review"
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


def record_discovery_finding_ids(
    loop: ReviewLoop,
    finding_set_id: str,
    reported: Sequence[ReviewFinding],
) -> dict[str, list[str]]:
    """Track finding ids introduced in each discovery finding set."""

    by_set = {key: list(value) for key, value in loop.finding_ids_by_set.items()}
    existing = list(by_set.get(finding_set_id, []))
    for finding in reported:
        if finding.id not in existing:
            existing.append(finding.id)
    by_set[finding_set_id] = existing
    return by_set


def parse_request_finding_actions(
    request: Mapping[str, Any],
) -> list[FindingAction]:
    """Parse optional finding_actions from a respond payload."""

    if "finding_actions" not in request:
        return []
    raw = request.get("finding_actions")
    if not isinstance(raw, list):
        raise ValueError("finding_actions must be a list")
    actions: list[FindingAction] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"finding_actions[{index}] must be an object")
        actions.append(parse_finding_action(item))
    return actions


DiscoveryDerivedOutcome = Literal[
    "approved",
    "changes_requested",
    "blocked",
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
    finding_ids_in_active_set: set[str] | None = None,
) -> DiscoveryDerivedOutcome:
    """Derive lifecycle outcome from findings and revise_at (service-owned)."""

    if not review_completed:
        return "review_incomplete"
    if required_open_findings(findings, threshold):
        return "changes_requested"
    if (
        finding_ids_in_active_set is not None
        and not finding_ids_in_active_set
    ):
        return "approved"
    if open_optional_findings_missing_owner_response_in_active_set(
        findings,
        finding_actions,
        threshold,
        finding_set_id=finding_set_id,
        finding_ids_in_active_set=finding_ids_in_active_set,
    ):
        # Optional findings need owner actions; do not force revision.
        return "pending"
    optional_ids = {
        finding.id for finding in optional_open_findings(findings, threshold)
    }
    if finding_ids_in_active_set is not None:
        optional_ids &= finding_ids_in_active_set
    effective = effective_owner_actions(
        finding_actions,
        finding_set_id=finding_set_id,
    )
    relevant_actions = [
        effective[finding_id]
        for finding_id in optional_ids
        if finding_id in effective
    ]
    if owner_actions_require_verification(relevant_actions):
        return "changes_requested"
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
    if outcome == "blocked":
        return "blocked"
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

    explicit_blocked = bool(request.get("block_review"))
    if request.get("decision") is not None:
        raise ValueError(
            "discovery respond must not include decision; use block_review to halt "
            "scope review without reporting findings"
        )
    if explicit_blocked:
        finding_set_id = validate_finding_set_id_echo(loop, request)
        reported = parse_reported_findings(request) if request.get("reported_findings") else []
        if reported:
            assert_reported_finding_ids_unused(loop, reported)
            merged = merge_discovery_findings(loop, reported)
        else:
            merged = list(loop.findings)
        updated = replace(
            loop,
            findings=merged,
            status="blocked",
        )
        return updated, merged, "blocked"

    reported = parse_discovery_respond_findings(loop, request)
    review_completed = bool(request.get("review_completed"))
    finding_set_id = validate_finding_set_id_echo(loop, request)
    merged = merge_discovery_findings(loop, reported)
    incoming_actions = parse_request_finding_actions(request)
    finding_actions = list(loop.finding_actions) + incoming_actions
    threshold = loop_revise_at(loop)
    active_for_handoff = active_finding_ids_for_advisory_policy(
        loop,
        reported_finding_ids=[finding.id for finding in reported],
    )
    outcome = derive_discovery_outcome(
        merged,
        finding_actions,
        threshold,
        review_completed=review_completed,
        finding_set_id=finding_set_id,
        finding_ids_in_active_set=active_for_handoff,
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
        finding_ids_by_set=record_discovery_finding_ids(
            loop,
            finding_set_id,
            reported,
        ),
        review_incomplete=incomplete,
        status=status,
    )
    if is_scope_review_stage_name(stage or "") and outcome == "pending":
        updated = replace(updated, scope_review_result=None)
    if (
        is_scope_review_stage_name(stage or "")
        and review_completed
        and outcome != "review_incomplete"
    ):
        updated = replace(
            updated,
            scope_review_rounds=loop.scope_review_rounds + 1,
        )
    if is_mandatory_review_loop(loop) and outcome == "review_incomplete":
        updated = replace(updated, lifecycle_status="review_incomplete")
    return updated, merged, outcome


def reviewer_package_policy_guidance() -> dict[str, Any]:
    """Severity and category guidance for reviewer packages (never includes revise_at)."""

    return {
        "severity_order": list(SEVERITY_ORDER),
        "severity_definitions": dict(SEVERITY_DEFINITIONS),
        "category_definitions": {
            category: CATEGORY_DEFINITIONS[category]
            for category in FINDING_CATEGORY_ORDER
        },
    }


def needs_advisory_handoff(loop: ReviewLoop) -> bool:
    """True when open optionals need owner actions and no required findings force revision."""

    threshold = loop_revise_at(loop)
    if required_open_findings(loop.findings, threshold):
        return False
    finding_set_id = str(loop.finding_set_id or "").strip() or None
    active_for_handoff = active_finding_ids_for_advisory_policy(loop)
    return bool(
        open_optional_findings_missing_owner_response_in_active_set(
            loop.findings,
            loop.finding_actions,
            threshold,
            finding_set_id=finding_set_id,
            finding_ids_in_active_set=active_for_handoff,
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


def complete_advisory_handoff_if_owner_responses_recorded(
    loop: ReviewLoop,
) -> ReviewLoop:
    """Mark handoff complete when optionals already have owner responses."""

    if needs_advisory_handoff(loop):
        return loop
    finding_set_id = str(loop.finding_set_id or "").strip()
    if not finding_set_id or finding_set_id in loop.advisory_handoffs_completed:
        return loop
    active = active_finding_ids_for_advisory_policy(loop)
    if active is not None and not active:
        return loop
    threshold = loop_revise_at(loop)
    if active is not None:
        if open_optional_findings_missing_owner_response_in_active_set(
            loop.findings,
            loop.finding_actions,
            threshold,
            finding_set_id=finding_set_id,
            finding_ids_in_active_set=active,
        ):
            return loop
    elif not optional_open_findings(loop.findings, threshold):
        return loop
    return mark_advisory_handoff_completed(loop)


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


def mark_advisory_handoff_incomplete(
    loop: ReviewLoop,
    *,
    missing_finding_ids: list[str],
    reason: str | None = None,
) -> ReviewLoop:
    """Persist review_incomplete marker for an unfinished advisory owner handoff."""

    finding_set_id = str(loop.finding_set_id or "").strip()
    if not finding_set_id:
        raise ValueError("advisory handoff incomplete requires finding_set_id")
    message = reason or (
        "advisory handoff incomplete: optional findings lack owner responses"
    )
    marker = build_review_incomplete_marker(
        stage="advisory_handoff",
        finding_set_id=finding_set_id,
        reason=message,
    )
    marker["missing_owner_action_ids"] = list(missing_finding_ids)
    updates: dict[str, Any] = {
        "status": "review_incomplete",
        "review_incomplete": marker,
    }
    if is_mandatory_review_loop(loop):
        updates["lifecycle_status"] = "review_incomplete"
    return replace(loop, **updates)


def primary_owner_role_for_review(loop: ReviewLoop) -> str:
    if loop.type in {"whole_output", "focused_output"}:
        return "producer"
    return "planner"


def finding_by_id(
    findings: Sequence[ReviewFinding],
    finding_id: str,
) -> ReviewFinding | None:
    for finding in findings:
        if finding.id == finding_id:
            return finding
    return None


def finding_actions_for_active_set(loop: ReviewLoop) -> list[FindingAction]:
    """Owner actions recorded for the loop's current finding set."""

    return scoped_finding_actions(loop.finding_actions, loop.finding_set_id)


def open_challenge_actions(loop: ReviewLoop) -> list[FindingAction]:
    """Challenge actions whose findings are still open (awaiting verification)."""

    open_ids = {finding.id for finding in open_findings(loop.findings)}
    effective = effective_owner_actions(
        loop.finding_actions,
        finding_set_id=loop.finding_set_id,
    )
    return [
        action
        for finding_id, action in effective.items()
        if action.action == "challenge" and finding_id in open_ids
    ]


def owner_actions_require_verification(
    actions: Sequence[FindingAction],
) -> bool:
    return any(action.action in {"fix", "challenge"} for action in actions)


def owner_actions_require_revision(actions: Sequence[FindingAction]) -> bool:
    """True when any claimed fix requires an artifact revision cycle."""

    return any(action.action == "fix" for action in actions)


def expand_finding_actions_with_default(
    loop: ReviewLoop,
    raw_actions: Sequence[Mapping[str, Any]],
    *,
    default_optional_action: str | None,
    actor_role: str,
    artifact_revision: int,
) -> list[dict[str, Any]]:
    """Apply batch default_optional_action to remaining optional findings in the set."""

    explicit = [dict(item) for item in raw_actions if isinstance(item, Mapping)]
    default_action: FindingOwnerAction | None = None
    if default_optional_action is not None and str(default_optional_action).strip():
        default_action = validate_default_optional_action(default_optional_action)
    if not explicit and default_action is None:
        raise ValueError(
            "record_finding_actions requires finding_actions or default_optional_action"
        )

    finding_set_id = str(loop.finding_set_id or "").strip()
    explicit_ids = {
        str(item.get("finding_id") or "").strip()
        for item in explicit
        if str(item.get("finding_id") or "").strip()
    }
    scoped_existing_ids = {
        action.finding_id
        for action in loop.finding_actions
        if not finding_set_id or action.finding_set_id == finding_set_id
    }
    expanded = list(explicit)
    if default_action is not None:
        threshold = loop_revise_at(loop)
        current_set_ids = (
            set(loop.finding_ids_by_set.get(finding_set_id, []))
            if finding_set_id
            else set()
        )
        for finding in optional_open_findings(loop.findings, threshold):
            if finding.id in explicit_ids or finding.id in scoped_existing_ids:
                continue
            if current_set_ids and finding.id not in current_set_ids:
                continue
            expanded.append(
                {
                    "finding_id": finding.id,
                    "action": default_action,
                    "actor_role": actor_role,
                    "artifact_revision": artifact_revision,
                    "finding_set_id": finding_set_id,
                    "rationale": (
                        f"Batch default_optional_action: {default_action}"
                    ),
                }
            )

    if not expanded:
        raise ValueError(
            "no finding_actions to record; explicit actions and "
            "default_optional_action did not match any optional findings"
        )
    return expanded


def build_review_convergence_warning(loop: ReviewLoop) -> str | None:
    """Informational warning for repeated scope-review rounds without approval."""

    if loop.lifecycle_status == "approved":
        return None
    rounds = int(loop.scope_review_rounds)
    if rounds < CONVERGENCE_WARNING_MIN_SCOPE_REVIEW_ROUNDS:
        return None

    threshold = loop_revise_at(loop)
    open_required = required_open_findings(loop.findings, threshold)
    open_optional = optional_open_findings(loop.findings, threshold)
    lines = [
        "Review convergence warning:",
        (
            f"{rounds} scope-review round(s) have completed without approval."
        ),
    ]
    if loop.finding_ids_by_set:
        recent = list(loop.finding_ids_by_set.items())[
            -CONVERGENCE_WARNING_RECENT_FINDING_SETS:
        ]
        counts = [len(ids) for _set_id, ids in recent if ids]
        if counts:
            joined = ", ".join(str(count) for count in counts)
            lines.append(
                f"The latest {len(counts)} round(s) added {joined} finding(s)."
            )
    if not open_required and open_optional:
        lines.append("All prior required findings are closed.")
        lines.append("The current round contains optional findings only.")
    if uses_finding_family_protocol(loop):
        from top_down_planning.domain.finding_families import (
            derive_family_operational_status,
            family_owner_sweeps,
        )

        regressed = [
            family.id
            for family in loop.finding_families
            if family.reopens_family_id
        ]
        if regressed:
            lines.append(
                "Service-derived regression reopened "
                f"{len(regressed)} closed famil(ies): {', '.join(regressed)}."
            )
        partial = [
            family.id
            for family in loop.finding_families
            if family_owner_sweeps(loop, family.id)
            and derive_family_operational_status(loop, family.id) != "closed"
        ]
        if partial:
            lines.append(
                f"{len(partial)} famil(ies) remain open after owner sweeps: "
                f"{', '.join(partial)}."
            )
        if len(loop.finding_ids_by_set) >= 2:
            set_ids = list(loop.finding_ids_by_set.keys())
            current_set = set_ids[-1]
            prior_fingerprints = {
                family.family_fingerprint
                for family in loop.finding_families
                if family.finding_set_id != current_set
            }
            new_families = [
                family.id
                for family in loop.finding_families
                if family.finding_set_id == current_set
                and family.family_fingerprint not in prior_fingerprints
            ]
            if new_families:
                lines.append(
                    "Latest scope round introduced new defect families: "
                    f"{', '.join(new_families)}."
                )
    return "\n".join(lines)


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
    scoped_existing_ids = {
        action.finding_id
        for action in loop.finding_actions
        if not finding_set_id or action.finding_set_id == finding_set_id
    }
    parsed: list[FindingAction] = []
    batch_action_ids: set[str] = set()
    for item in raw_actions:
        if not isinstance(item, Mapping):
            raise ValueError("finding_actions entry must be an object")
        payload = dict(item)
        payload.setdefault("actor_role", actor_role)
        payload.setdefault("artifact_revision", artifact_revision)
        if finding_set_id and not str(payload.get("finding_set_id") or "").strip():
            payload["finding_set_id"] = finding_set_id
        action = parse_finding_action(payload)
        if action.finding_id in scoped_existing_ids:
            raise ValueError(
                f"finding {action.finding_id!r} already has an owner action "
                f"for finding_set_id {action.finding_set_id!r}"
            )
        if action.finding_id in batch_action_ids:
            raise ValueError(
                f"finding {action.finding_id!r} appears more than once in finding_actions"
            )
        batch_action_ids.add(action.finding_id)
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
        if action.action == "fix" and artifact_revision <= loop.target_revision:
            raise ValueError(
                f"fix action for finding {action.finding_id!r} requires artifact "
                f"revision to advance past review target_revision "
                f"{loop.target_revision}; got artifact_revision {artifact_revision}"
            )
        # VR18: owner actions never rewrite finding status to invalid/superseded.
        parsed.append(action)

    merged_actions = list(loop.finding_actions) + parsed
    updated = replace(loop, finding_actions=merged_actions)
    if findings_permit_approval(
        updated.findings,
        updated.finding_actions,
        threshold,
        finding_set_id=finding_set_id or None,
    ):
        updated = replace(updated, status="approved")
    elif required_open_findings(updated.findings, threshold):
        if owner_actions_require_revision(parsed) or open_challenge_actions(updated):
            updated = replace(updated, status="changes_requested")
    elif owner_actions_require_revision(parsed):
        updated = replace(updated, status="changes_requested")
    return updated, parsed


def is_scope_review_stage(loop: ReviewLoop) -> bool:
    return is_scope_review_stage_name(loop.active_stage)


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
        if stage == "advisory_handoff":
            lifecycle = "review_pending"  # type: ignore[assignment]
        elif is_scope_review_stage_name(stage):
            lifecycle = "scope_review_pending"
        elif stage == "finding_verification":
            lifecycle = "verification_pending"
        else:
            lifecycle = "review_pending"
    status: ReviewLoopStatus = "pending"
    if stage == "advisory_handoff":
        status = "advisory_pending"
    return replace(
        loop,
        status=status,
        lifecycle_status=lifecycle,  # type: ignore[arg-type]
        active_stage=(
            None
            if stage in {"", "initial_review", "discovery", "advisory_handoff"}
            else validate_review_stage(stage)  # type: ignore[arg-type]
        ),
        # Budgets intentionally unchanged: revision_cycles / scope_review_rounds.
    )


def prepare_limit_reached_retry(loop: ReviewLoop) -> ReviewLoop:
    """Revive a ``limit_reached`` mandatory loop after a limit extension.

    Preserves ``revision_cycles`` / ``scope_review_rounds`` so an extended
    ``max_*`` continues the same phase budget instead of opening a new loop.
    """

    if not is_limit_reached_review_loop(loop):
        return loop

    exhausted = normalize_exhausted_budget(loop.exhausted_budget)
    if exhausted == "scope_review":
        # Re-enter the path that calls ``_begin_scope_review`` with the same
        # consumed scope_review_rounds under the raised max.
        assert_mandatory_review_transition("limit_reached", "findings_closed")
        return reset_gate_agent_turns(
            replace(
                loop,
                status="approved",
                lifecycle_status="findings_closed",
                active_stage=None,
                exhausted_budget=None,
                scope_review_result=None,
            ).with_reviewer_session_released()
        )

    if exhausted == "verification_revision":
        # Re-enter primary owner revision for the already-consumed cycle
        # (needs_primary_revision_resume) without double-counting.
        assert_mandatory_review_transition("limit_reached", "revision_in_progress")
        return reset_gate_agent_turns(
            replace(
                loop,
                status="pending",
                lifecycle_status="revision_in_progress",
                active_stage="finding_verification",
                exhausted_budget=None,
            ).with_reviewer_session_released()
        )

    raise ValueError(
        f"cannot retry limit_reached loop without exhausted_budget; "
        f"got {loop.exhausted_budget!r}"
    )


def budgets_snapshot(loop: ReviewLoop) -> dict[str, int]:
    return {
        "revision_cycles": int(loop.revision_cycles),
        "scope_review_rounds": int(loop.scope_review_rounds),
        "gate_agent_turns": int(loop.gate_agent_turns),
    }


def review_gate_budgets_for_package(
    loop: ReviewLoop,
    config: dict[str, Any],
) -> dict[str, int]:
    """Budget counters and configured gate-turn cap for reviewer packages."""

    limits = review_gate_limits_from_config(config)
    return {
        **budgets_snapshot(loop),
        "max_agent_turns_per_gate": int(limits["max_agent_turns_per_gate"]),
    }


def build_active_findings_view(loop: ReviewLoop) -> dict[str, Any]:
    """Compact owner/reviewer package fields omitting closed finding history."""

    finding_set_id = str(loop.finding_set_id or "").strip()
    open_all = open_findings(loop.findings)
    current_ids = set(loop.finding_ids_by_set.get(finding_set_id, []))
    if current_ids:
        new_findings = [finding for finding in open_all if finding.id in current_ids]
        carried_open_findings = [
            finding for finding in open_all if finding.id not in current_ids
        ]
    else:
        new_findings = list(open_all)
        carried_open_findings = []

    scoped_actions = scoped_finding_actions(
        loop.finding_actions,
        finding_set_id or None,
    )
    effective = effective_owner_actions(
        scoped_actions,
        finding_set_id=finding_set_id or None,
    )
    verification_targets = [
        finding
        for finding in open_all
        if finding.id in effective
        and effective[finding.id].action in {"fix", "challenge"}
    ]
    closed_count = len(loop.findings) - len(open_all)
    convergence_warning = build_review_convergence_warning(loop)
    history_summary: dict[str, Any] = {
        "total": len(loop.findings),
        "closed": closed_count,
        "open": len(open_all),
        "advisory_handoffs_completed": len(loop.advisory_handoffs_completed),
        "finding_set_id": finding_set_id or None,
        "scope_review_rounds": int(loop.scope_review_rounds),
    }
    if convergence_warning is not None:
        history_summary["convergence_warning"] = convergence_warning
    return {
        "new_findings": [finding.to_dict() for finding in new_findings],
        "carried_open_findings": [
            finding.to_dict() for finding in carried_open_findings
        ],
        "verification_targets": [
            finding.to_dict() for finding in verification_targets
        ],
        "current_finding_actions": [action.to_dict() for action in scoped_actions],
        "history_summary": history_summary,
        "history_ref": {
            "kind": "review_loop_findings",
            "loop_id": loop.id,
            "finding_set_id": finding_set_id or None,
        },
    }


PrimaryOwnerFindingHandoff = Literal["revision", "advisory"]


def _budget_dimension(consumed: int, maximum: int) -> dict[str, int]:
    consumed_value = int(consumed)
    maximum_value = int(maximum)
    return {
        "consumed": consumed_value,
        "max": maximum_value,
        "remaining": max(0, maximum_value - consumed_value),
    }


def build_review_budget_fields(
    loop: ReviewLoop,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Consumed/max/remaining review budgets for primary-agent handoff packages."""

    loop_type = str(loop.type or "").strip()
    if loop_type in {"whole_plan", "whole_output"}:
        review_type = "whole_plan" if loop_type == "whole_plan" else "whole_output"
        limits = mandatory_review_limits_from_config(config, review_type)
        return {
            "revision_cycles": _budget_dimension(
                loop.revision_cycles,
                limits.max_revision_cycles,
            ),
            "scope_review_rounds": _budget_dimension(
                loop.scope_review_rounds,
                limits.max_scope_review_rounds,
            ),
        }

    if loop_type in {"focused_plan", "focused_output"}:
        max_cycles = focused_review_revision_limit_from_config(
            config,
            loop_type,  # type: ignore[arg-type]
        )
        return {
            "revision_cycles": _budget_dimension(loop.revision_cycles, max_cycles),
        }

    raise ValueError(f"unsupported review loop type for review_budget: {loop_type!r}")


_DEFAULT_FOCUSED_PLAN_REVIEW_MAX_REVISION_CYCLES = 3
_DEFAULT_FOCUSED_OUTPUT_REVIEW_MAX_REVISION_CYCLES = 3


def focused_review_revision_limit_from_config(
    config: Mapping[str, Any],
    review_type: Literal["focused_plan", "focused_output"],
) -> int:
    """Load per-loop revision budget for focused plan/output review."""

    limits_key = (
        "focused_plan_review"
        if review_type == "focused_plan"
        else "focused_output_review"
    )
    section = (config.get("limits") or {}).get(limits_key) or {}
    default_cycles = (
        _DEFAULT_FOCUSED_PLAN_REVIEW_MAX_REVISION_CYCLES
        if review_type == "focused_plan"
        else _DEFAULT_FOCUSED_OUTPUT_REVIEW_MAX_REVISION_CYCLES
    )
    return int(
        section.get(
            "max_revision_cycles_per_loop",
            default_cycles,
        )
    )


def build_primary_owner_finding_guidance(
    *,
    handoff: PrimaryOwnerFindingHandoff,
    loop: ReviewLoop,
    config: Mapping[str, Any],
) -> str:
    """Budget-aware owner guidance for primary review handoff resume packages."""

    threshold = loop_revise_at(loop)
    optional_count = len(optional_open_finding_ids(loop.findings, threshold))
    budget = build_review_budget_fields(loop, config)

    if handoff == "revision":
        lines = [
            (
                "Fix every open required finding (severity at or above revise_at). "
                "For optional findings, prefer defer or accept_as_is via record-actions "
                "unless the fix is trivially included in required work. "
                "Optional fix or challenge triggers reviewer verification and consumes a "
                "revision cycle; defer and accept_as_is do not. "
                "Required findings may only use fix or challenge."
            ),
        ]
        if uses_finding_family_protocol(loop):
            lines.append(
                (
                    "Treat each entry in active_families as one repair unit. Search "
                    "the whole active plan using rule_id, subject_key, scope_kind, "
                    "candidate_refs, and search dimensions before fixing. Apply all "
                    "confirmed and newly discovered equivalent locations in one plan "
                    "apply where possible, then record one family_fix with a completed "
                    "owner_sweep (empty remaining_instance_refs) at the current "
                    "target_revision and target_digest. Use target_finding_ids to "
                    "list optional members explicitly; required open members are "
                    "included automatically. `record-actions` rejects stale "
                    "target_digest values. After the artifact revision advances, "
                    "re-call record-actions at the new revision and digest to "
                    "rebind the sweep without duplicating fix actions. Fixing only "
                    "the seed finding does not close the family."
                )
            )
        elif loop_uses_finding_families(loop):
            lines.append(
                (
                    "Related defects are grouped in active_families. Address every "
                    "open confirmed member within scope via per-finding record-actions; "
                    "fixing only the seed finding does not close the group."
                )
            )
    else:
        lines = [
            (
                "Record owner responses for all optional findings via record-actions. "
                "Prefer accept_as_is when the issue is valid but not worth another review "
                "round; use defer when you intend to address it later. "
                "Use fix or challenge only when the finding is materially wrong or the "
                "improvement is worth a verification cycle. "
                "Bulk-close remaining optionals with default_optional_action when "
                "appropriate."
            ),
        ]
        if is_mandatory_review_loop(loop):
            lines.append(
                "Recording owner responses does not complete mandatory review. "
                "The reviewer must still run a scope_review respond with decision "
                "approved on the current artifact digest before the run advances."
            )

    if optional_count > 0:
        lines.append(
            f"{optional_count} optional finding(s) are open; conserve revision budget "
            "by resolving them with defer or accept_as_is when fixes are not required."
        )

    revision = budget["revision_cycles"]
    if revision["remaining"] <= 1:
        lines.append(
            "Review budget: "
            f"{revision['remaining']} revision cycle(s) remaining "
            f"({revision['consumed']}/{revision['max']} used). "
            "Do not spend them on optional fixes."
        )
    scope = budget.get("scope_review_rounds")
    if scope is not None and scope["remaining"] <= 1:
        lines.append(
            "Scope-review budget: "
            f"{scope['remaining']} round(s) remaining "
            f"({scope['consumed']}/{scope['max']} used)."
        )

    return " ".join(lines)


def primary_review_resume_fields(
    loop: ReviewLoop,
    *,
    config: Mapping[str, Any],
    artifact_revision: int | None = None,
    artifact_digest: str | None = None,
) -> dict[str, Any]:
    """Fields for primary-agent revision/advisory packages (includes revise_at)."""

    threshold = loop_revise_at(loop)
    fields: dict[str, Any] = {
        "revise_at": threshold,
        "finding_set_id": loop.finding_set_id,
        **build_active_findings_view(loop),
        **policy_observability_fields_for_loop(loop),
        "review_budget": build_review_budget_fields(loop, config),
    }
    if loop_uses_finding_families(loop):
        from top_down_planning.domain.finding_families import (
            build_active_family_view,
            family_observability_fields,
        )

        fields["active_families"] = build_active_family_view(
            loop,
            artifact_revision=artifact_revision,
            artifact_digest=artifact_digest,
        )
        fields.update(
            family_observability_fields(
                loop,
                artifact_revision=artifact_revision,
                artifact_digest=artifact_digest,
            )
        )
    if is_mandatory_review_loop(loop):
        fields.update(build_record_actions_gate_fields(loop))
    return fields


def verification_required_for_loop(loop: ReviewLoop) -> bool:
    """True when artifact change, claimed fix, or open challenge requires verification."""

    open_ids = {finding.id for finding in open_findings(loop.findings)}
    effective = effective_owner_actions(
        loop.finding_actions,
        finding_set_id=loop.finding_set_id,
    )
    relevant = [
        action
        for finding_id, action in effective.items()
        if finding_id in open_ids and action.action in {"fix", "challenge"}
    ]
    return owner_actions_require_verification(relevant)


def validate_decision(decision: str) -> ReviewDecision:
    """Validate a focused-review decision (approved|changes_requested|blocked)."""

    normalized = str(decision).strip()
    if normalized not in {"approved", "changes_requested", "blocked"}:
        raise ValueError(
            "decision must be one of: approved, changes_requested, blocked"
        )
    return normalized  # type: ignore[return-value]


_MANDATORY_STAGE_DECISIONS: Mapping[str, frozenset[str]] = {
    "finding_verification": frozenset({"verified", "needs_revision", "blocked"}),
}


def require_review_respond_stage(request: dict[str, Any]) -> str:
    """Return mandatory review stage; reject when stage is missing or unknown."""

    raw_stage = request.get("stage")
    if raw_stage is None or not str(raw_stage).strip():
        raise ValueError(
            "mandatory review respond requires stage: initial_review, "
            "finding_verification, or scope_review"
        )
    stage = validate_review_stage(str(raw_stage).strip())
    if stage is None:
        raise ValueError(
            "stage must be one of: initial_review, finding_verification, scope_review"
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

    stage = loop.active_stage or "initial_review"

    if is_scope_review_stage_name(stage):
        blocker = loop.scope_review_result
        if isinstance(blocker, dict):
            raw = str(blocker.get("decision") or "").strip()
            canonical = validate_scope_review_decision_value(raw)
            if canonical not in {"approved", "changes_requested", "blocked"}:
                raise ValueError(f"invalid scope_review_result.decision: {raw!r}")
            return canonical
        if loop.status == "pending":
            return "pending"
        if loop.status == "approved":
            return "pending"
        if loop.status in {"changes_requested", "blocked", "advisory_pending"}:
            return loop.status
        raise ValueError("scope_review loop missing scope_review_result")

    if stage == "finding_verification":
        verification = loop.verification_result
        if isinstance(verification, dict):
            raw = str(verification.get("decision") or "").strip()
            if raw not in {"verified", "needs_revision", "blocked"}:
                raise ValueError(
                    f"invalid verification_result.decision: {raw!r}"
                )
            return raw
        if loop.status == "pending":
            return "pending"
        if loop.status in {"changes_requested", "blocked", "approved"}:
            return loop.status
        raise ValueError(
            "finding_verification loop missing verification_result"
        )

    if loop.status == "pending":
        return "pending"
    if loop.status == "advisory_pending":
        return "advisory_pending"
    if loop.status == "blocked":
        return "blocked"
    if loop.status == "review_incomplete":
        return "review_incomplete"

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

    challenges_by_id = {
        action.finding_id: action for action in open_challenge_actions(loop)
    }
    for finding_id in challenges_by_id:
        if finding_id not in disposition_by_id:
            raise ValueError(
                f"finding_results missing challenged finding_id {finding_id!r}"
            )

    loop_finding_ids = {finding.id for finding in loop.findings}
    for entry in entries:
        challenge = challenges_by_id.get(entry.finding_id)
        if challenge is None or entry.disposition != "superseded":
            continue
        link = str(challenge.superseded_by_finding_id or "").strip()
        if not link:
            raise ValueError(
                f"superseded disposition for challenged finding {entry.finding_id!r} "
                "requires challenge superseded_by_finding_id"
            )
        if link not in loop_finding_ids:
            raise ValueError(
                f"superseded_by_finding_id {link!r} must reference a finding in the "
                "same loop"
            )
        if link == entry.finding_id:
            raise ValueError(
                f"superseded_by_finding_id must not equal finding {entry.finding_id!r}"
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


def merge_scope_review_findings(
    loop: ReviewLoop,
    reported_findings: list[ReviewFinding],
) -> list[ReviewFinding]:
    """Append new scope-review findings; never mutate existing records."""

    existing_ids = {finding.id for finding in loop.findings}
    merged = list(loop.findings)
    for finding in reported_findings:
        if finding.id in existing_ids:
            raise ValueError(
                f"scope review finding id {finding.id!r} already exists in the loop; "
                "rediscovery must use a new id; the service derives reopen lineage "
                "from fingerprint and instance_ref"
            )
        merged.append(finding)
        existing_ids.add(finding.id)
    return merged


def validate_verification_closure(
    loop: ReviewLoop,
    result: FindingVerificationResult,
    merged_findings: list[ReviewFinding],
) -> None:
    """Reject verified when open findings or direct side effects remain."""

    if result.decision != "verified":
        return

    unresolved = required_unresolved_finding_ids(
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
    scope_review_result: dict[str, Any] | None = None,
    lifecycle_status: MandatoryReviewLifecycleStatus | str | None = None,
) -> ReviewLoop:
    if loop.target_revision != target_revision:
        raise ValueError(
            f"target_revision {target_revision} does not match loop target "
            f"{loop.target_revision}"
        )

    if decision in CLEAR_APPROVAL_STATUSES:
        threshold = loop_revise_at(loop)
        permit_approval = (
            findings_permit_approval_for_loop(loop, findings)
            if loop.finding_ids_by_set
            else findings_permit_approval(
                findings,
                loop.finding_actions,
                threshold,
                finding_set_id=loop.finding_set_id,
            )
        )
        if not permit_approval:
            required_ids = required_open_finding_ids(findings, threshold)
            active = (
                active_finding_ids_for_advisory_policy(loop)
                if loop.finding_ids_by_set
                else None
            )
            missing_response_ids = [
                finding.id
                for finding in open_optional_findings_missing_owner_response_in_active_set(
                    findings,
                    loop.finding_actions,
                    threshold,
                    finding_set_id=loop.finding_set_id,
                    finding_ids_in_active_set=active,
                )
            ]
            verification_required_ids = optional_finding_ids_requiring_verification(
                findings,
                loop.finding_actions,
                threshold,
                finding_set_id=loop.finding_set_id,
            )
            if active is not None:
                if not active:
                    verification_required_ids = []
                else:
                    verification_required_ids = [
                        finding_id
                        for finding_id in verification_required_ids
                        if finding_id in active
                    ]
            details: list[str] = []
            if required_ids:
                details.append(
                    "open required findings: " + ", ".join(required_ids)
                )
            if missing_response_ids:
                details.append(
                    "optional findings missing owner response: "
                    + ", ".join(missing_response_ids)
                )
            if verification_required_ids:
                details.append(
                    "optional findings requiring reviewer verification: "
                    + ", ".join(verification_required_ids)
                )
            raise ValueError(
                f"{decision!r} decision requires no open required findings and "
                "defer or accept_as_is on every open optional finding; "
                + "; ".join(details)
            )

    resolved_lifecycle = lifecycle_status if lifecycle_status is not None else loop.lifecycle_status
    resolved_verification = (
        verification_result
        if verification_result is not None
        else loop.verification_result
    )
    resolved_blocker = (
        scope_review_result
        if scope_review_result is not None
        else loop.scope_review_result
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
        scope_review_result=resolved_blocker,
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
        finding_results_raw = payload.get("finding_results") or []
        if not isinstance(finding_results_raw, list):
            raise ValueError("finding_results must be a list")
        finding_results = []
        for index, item in enumerate(finding_results_raw):
            if not isinstance(item, dict):
                raise ValueError(f"finding_results[{index}] must be an object")
            finding_results.append(FindingVerificationEntry.from_dict(item))
        side_effects_raw = payload.get("new_direct_side_effect_findings") or []
        if not isinstance(side_effects_raw, list):
            raise ValueError("new_direct_side_effect_findings must be a list")
        side_effects = []
        for index, item in enumerate(side_effects_raw):
            if not isinstance(item, dict):
                raise ValueError(
                    f"new_direct_side_effect_findings[{index}] must be an object"
                )
            side_effects.append(ReviewFinding.from_dict(item))
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
    ) -> None:
        self.target_digest = target_digest
        self.decision = validate_scope_review_decision_value(decision)
        self.scope_id = scope_id
        self.reported_findings = list(reported_findings or [])
        self.acceptance_criteria_checked = list(acceptance_criteria_checked or [])
        self.summary = summary
        self.stage = SCOPE_REVIEW_STAGE

    def to_dict(self) -> dict[str, Any]:
        findings_payload = [finding.to_dict() for finding in self.reported_findings]
        return {
            "stage": SCOPE_REVIEW_STAGE,
            "target_digest": self.target_digest,
            "scope_id": self.scope_id,
            "decision": self.decision,
            "reported_findings": findings_payload,
            "acceptance_criteria_checked": list(self.acceptance_criteria_checked),
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ScopeReviewResult:
        stage_raw = str(payload.get("stage") or SCOPE_REVIEW_STAGE).strip()
        validate_review_stage(stage_raw)
        if payload.get("blocking_findings") is not None:
            raise ValueError("legacy field blocking_findings is not accepted")
        decision = validate_scope_review_decision_value(str(payload.get("decision") or ""))
        raw_findings = payload.get("reported_findings") or []
        if not isinstance(raw_findings, list):
            raise ValueError("reported_findings must be a list")
        reported = []
        for index, item in enumerate(raw_findings):
            if not isinstance(item, dict):
                raise ValueError(f"reported_findings[{index}] must be an object")
            reported.append(ReviewFinding.from_dict(item))
        return cls(
            target_digest=str(payload.get("target_digest") or ""),
            decision=decision,  # type: ignore[arg-type]
            scope_id=str(payload.get("scope_id") or ""),
            reported_findings=reported,
            acceptance_criteria_checked=[
                str(item) for item in (payload.get("acceptance_criteria_checked") or [])
            ],
            summary=str(payload.get("summary") or ""),
            stage=SCOPE_REVIEW_STAGE,
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


def validate_scope_review_decision(decision: str) -> ScopeReviewDecision:
    return validate_scope_review_decision_value(decision)  # type: ignore[return-value]


def validate_mandatory_lifecycle_status(
    status: str,
) -> MandatoryReviewLifecycleStatus:
    normalized = validate_lifecycle_status(status)
    if normalized is None:
        raise ValueError("mandatory review lifecycle status is required")
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
    scope_review_result: ScopeReviewResult | None,
    current_artifact_digest: str,
    lifecycle_status: MandatoryReviewLifecycleStatus | str | None = None,
    findings: Sequence[ReviewFinding] | None = None,
    finding_actions: Sequence[FindingAction] | None = None,
    revise_at: ReviewSeverity | None = None,
) -> bool:
    """Core Invariant + Digest and Approval Rules for mandatory gates.

    Approval requires verified finding closure, no direct side effects, a fresh
    scope review deciding ``approved`` against the current digest, and must never
    treat ``limit_reached`` / ``blocked`` as approval.
    """

    if lifecycle_status in {"blocked", "limit_reached"}:
        return False
    if scope_review_result is None:
        return False
    if not is_scope_review_stage_name(scope_review_result.stage):
        return False
    if validate_scope_review_decision_value(scope_review_result.decision) != "approved":
        return False
    if findings is not None:
        if revise_at is None:
            raise ValueError("is_approval_eligible requires revise_at when findings are provided")
        if not findings_permit_approval(
            findings,
            finding_actions or [],
            revise_at,
        ):
            return False
    elif scope_review_result.reported_findings:
        return False
    if not stage_digest_matches_artifact(
        stage_target_digest=scope_review_result.target_digest,
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

ExhaustedReviewBudget = Literal[
    "verification_revision",
    "scope_review",
]


@dataclass(frozen=True)
class MandatoryReviewLimits:
    """Loop Bounds for mandatory whole_plan / whole_output review.

    ``max_revision_cycles`` caps verification/revision cycles per finding set.
    ``max_scope_review_rounds`` caps fresh scope-complete reviews per phase.
    """

    max_revision_cycles: int = _DEFAULT_MAX_REVISION_CYCLES
    max_scope_review_rounds: int = _DEFAULT_MAX_SCOPE_REVIEW_ROUNDS

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> MandatoryReviewLimits:
        raw = dict(payload or {})
        if raw.get("max_blocker_review_rounds") is not None:
            raise ValueError(
                "legacy config key max_blocker_review_rounds is not accepted; "
                "use max_scope_review_rounds"
            )
        rounds = raw.get(
            "max_scope_review_rounds",
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


def scope_review_budget_exhausted(
    scope_review_rounds: int,
    limits: MandatoryReviewLimits,
) -> bool:
    return int(scope_review_rounds) >= int(limits.max_scope_review_rounds)


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
    """Build a ``limit_reached`` pause that preserves unresolved findings.

    ``limit_reached`` must never convert into approval (Loop Bounds). Resume
    after raising the exhausted limit revives the same loop via
    ``prepare_limit_reached_retry`` (budgets preserved).
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
    scope_review_rounds: int,
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
    if scope_review_budget_exhausted(scope_review_rounds, limits):
        return build_limit_reached_terminal(
            exhausted_budget="scope_review",
            findings=findings,
            limits=limits,
        )
    return None


def approval_allowed_under_loop_bounds(
    *,
    revision_cycles: int,
    scope_review_rounds: int,
    limits: MandatoryReviewLimits,
    verification: FindingVerificationResult | None,
    scope_review_result: ScopeReviewResult | None,
    current_artifact_digest: str,
    findings: list[ReviewFinding],
    finding_actions: list[FindingAction] | None = None,
    revise_at: ReviewSeverity | None = None,
    lifecycle_status: MandatoryReviewLifecycleStatus | str | None = None,
) -> bool:
    """True only when budgets remain and Core Invariant approval eligibility holds.

    ``limit_reached`` / exhausted budgets never convert into approval.
    """

    terminal = reject_approval_when_budget_exhausted(
        revision_cycles=revision_cycles,
        scope_review_rounds=scope_review_rounds,
        limits=limits,
        findings=findings,
    )
    if terminal is not None:
        return False
    return is_approval_eligible(
        verification=verification,
        scope_review_result=scope_review_result,
        current_artifact_digest=current_artifact_digest,
        lifecycle_status=lifecycle_status,
        findings=findings,
        finding_actions=finding_actions,
        revise_at=revise_at,
    )


def scope_review_approval_recorded(loop: ReviewLoop) -> bool:
    """True when a scope-review respond with decision approved is persisted."""

    raw = loop.scope_review_result
    if not isinstance(raw, dict):
        return False
    stage = str(raw.get("stage") or loop.active_stage or "").strip()
    if not is_scope_review_stage_name(stage):
        return False
    decision_raw = str(raw.get("decision") or "").strip()
    if not decision_raw:
        return False
    try:
        decision = validate_scope_review_decision_value(decision_raw)
    except ValueError:
        return False
    return decision == "approved"


def needs_fresh_scope_review_clear(loop: ReviewLoop) -> bool:
    """True when scope_review stage lacks a persisted approved scope_review_result."""

    return is_scope_review_stage_name(loop.active_stage) and not scope_review_approval_recorded(
        loop
    )


def ready_for_mandatory_final_approval(loop: ReviewLoop) -> bool:
    """True when mandatory gate may call complete_approval (scope clear on file)."""

    return is_scope_review_stage_name(loop.active_stage) and scope_review_approval_recorded(loop)


def mandatory_gate_next_actor(loop: ReviewLoop) -> str | None:
    """Next actor required to advance a mandatory whole_* gate, if any."""

    if not is_mandatory_review_loop(loop):
        return None
    if loop.lifecycle_status == "approved":
        return None
    if loop.status == "advisory_pending" or needs_advisory_handoff(loop):
        return "planner"
    if needs_fresh_scope_review_clear(loop):
        return "reviewer"
    if loop.status == "approved" and not ready_for_mandatory_final_approval(loop):
        return "reviewer"
    return None


def build_record_actions_gate_fields(loop: ReviewLoop) -> dict[str, Any]:
    """Gate-position fields for record-actions responses."""

    fields: dict[str, Any] = {
        "lifecycle_status": loop.lifecycle_status,
        "active_stage": loop.active_stage,
    }
    if not is_mandatory_review_loop(loop):
        return fields
    gate_pending = loop.lifecycle_status != "approved"
    fields["mandatory_gate_pending"] = gate_pending
    next_actor = mandatory_gate_next_actor(loop)
    if next_actor is not None:
        fields["next_required_actor"] = next_actor
    return fields


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
    scope_review: ScopeReviewResult | None = None
    if loop.scope_review_result is not None:
        scope_review = ScopeReviewResult.from_dict(loop.scope_review_result)
    return approval_allowed_under_loop_bounds(
        revision_cycles=loop.revision_cycles,
        scope_review_rounds=loop.scope_review_rounds,
        limits=limits,
        verification=verification,
        scope_review_result=scope_review,
        current_artifact_digest=current_artifact_digest,
        findings=loop.findings,
        finding_actions=loop.finding_actions,
        revise_at=loop_revise_at(loop),
        lifecycle_status=loop.lifecycle_status,
    )
