"""Finding-family models, fingerprints, and policy-aware derivation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from top_down_planning.domain.artifact_refs import (
    ArtifactRef,
    artifact_ref_to_dict,
    artifact_refs_equal,
    parse_artifact_ref_list,
)
from top_down_planning.domain.review_policy import severity_at_or_above
from top_down_planning.domain.review_rule_registry import (
    fingerprint_protocol_version,
    is_builtin_rule_id,
    is_custom_rule_id,
    normalize_rule_definition,
    normalize_subject_key,
    validate_rule_id,
)
from top_down_planning.domain.digest import digest_canonical_payload
from top_down_planning.domain.mandatory_audit_passes import (
    mandatory_audit_pass_ids_for_loop,
)

if TYPE_CHECKING:
    from top_down_planning.domain.reviews import (
        FindingAction,
        ReviewFinding,
        ReviewLoop,
    )

FamilyScopeKind = Literal[
    "active-plan",
    "focused-plan",
    "whole-output",
    "focused-output",
]

FamilyOperationalStatus = Literal[
    "open",
    "owner_sweep_pending",
    "verification_pending",
    "closed",
]

FamilySweepStage = Literal[
    "discovery",
    "owner_fix",
    "verification",
    "scope_review",
]

FamilySweepActorRole = Literal["reviewer", "planner", "producer"]

FAMILY_RESULT_DISPOSITIONS = frozenset({"closed", "open"})

FAMILY_SCOPE_KINDS: frozenset[str] = frozenset(
    {"active-plan", "focused-plan", "whole-output", "focused-output"}
)


@dataclass
class FindingFamily:
    id: str
    finding_set_id: str
    rule_id: str
    subject_key: str
    scope_kind: FamilyScopeKind
    family_fingerprint: str
    title: str
    seed_finding_id: str
    confirmed_finding_ids: list[str]
    candidate_refs: list[ArtifactRef]
    recommended_change: str
    rule_definition: str | None = None
    reopens_family_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "finding_set_id": self.finding_set_id,
            "rule_id": self.rule_id,
            "subject_key": self.subject_key,
            "scope_kind": self.scope_kind,
            "family_fingerprint": self.family_fingerprint,
            "title": self.title,
            "seed_finding_id": self.seed_finding_id,
            "confirmed_finding_ids": list(self.confirmed_finding_ids),
            "candidate_refs": [
                artifact_ref_to_dict(ref) for ref in self.candidate_refs
            ],
            "recommended_change": self.recommended_change,
        }
        if self.rule_definition is not None:
            payload["rule_definition"] = self.rule_definition
        if self.reopens_family_id is not None:
            payload["reopens_family_id"] = self.reopens_family_id
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> FindingFamily:
        scope_kind = str(payload.get("scope_kind") or "").strip()
        if scope_kind not in FAMILY_SCOPE_KINDS:
            raise ValueError(f"unsupported family scope_kind: {scope_kind!r}")
        confirmed_raw = payload.get("confirmed_finding_ids") or []
        if not isinstance(confirmed_raw, list) or not confirmed_raw:
            raise ValueError("finding family requires non-empty confirmed_finding_ids")
        confirmed_finding_ids = [str(item).strip() for item in confirmed_raw]
        if len(set(confirmed_finding_ids)) != len(confirmed_finding_ids):
            raise ValueError("confirmed_finding_ids must be unique")
        seed = str(payload.get("seed_finding_id") or "").strip()
        if seed not in confirmed_finding_ids:
            raise ValueError("seed_finding_id must be included in confirmed_finding_ids")
        rule_id = validate_rule_id(str(payload.get("rule_id") or ""))
        rule_definition_raw = payload.get("rule_definition")
        rule_definition = (
            normalize_rule_definition(str(rule_definition_raw))
            if rule_definition_raw is not None and str(rule_definition_raw).strip()
            else None
        )
        if is_custom_rule_id(rule_id) and rule_definition is None:
            raise ValueError("custom rule families require rule_definition")
        if is_builtin_rule_id(rule_id) and rule_definition is not None:
            raise ValueError("built-in rule families must not include rule_definition")
        return cls(
            id=str(payload["id"]),
            finding_set_id=str(payload.get("finding_set_id") or "").strip(),
            rule_id=rule_id,
            subject_key=str(payload.get("subject_key") or ""),
            scope_kind=scope_kind,  # type: ignore[arg-type]
            family_fingerprint=str(payload.get("family_fingerprint") or "").strip(),
            title=str(payload.get("title") or ""),
            seed_finding_id=seed,
            confirmed_finding_ids=confirmed_finding_ids,
            candidate_refs=parse_artifact_ref_list(payload.get("candidate_refs")),
            recommended_change=str(payload.get("recommended_change") or ""),
            rule_definition=rule_definition,
            reopens_family_id=(
                str(payload.get("reopens_family_id")).strip()
                if payload.get("reopens_family_id")
                else None
            ),
        )


@dataclass
class FamilySweepRecord:
    id: str
    family_id: str
    actor_role: FamilySweepActorRole
    stage: FamilySweepStage
    artifact_revision: int
    artifact_digest: str
    finding_set_id: str
    searched_refs: list[str]
    search_dimensions: list[str]
    additional_fixed_refs: list[ArtifactRef]
    remaining_instance_refs: list[ArtifactRef]
    completed: bool
    summary: str
    evidence: list[str] = field(default_factory=list)
    idempotency_key: str | None = None
    request_digest: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "family_id": self.family_id,
            "actor_role": self.actor_role,
            "stage": self.stage,
            "artifact_revision": self.artifact_revision,
            "artifact_digest": self.artifact_digest,
            "finding_set_id": self.finding_set_id,
            "searched_refs": list(self.searched_refs),
            "search_dimensions": list(self.search_dimensions),
            "additional_fixed_refs": [
                artifact_ref_to_dict(ref) for ref in self.additional_fixed_refs
            ],
            "remaining_instance_refs": [
                artifact_ref_to_dict(ref) for ref in self.remaining_instance_refs
            ],
            "completed": self.completed,
            "summary": self.summary,
            "evidence": list(self.evidence),
        }
        if self.idempotency_key is not None:
            payload["idempotency_key"] = self.idempotency_key
        if self.request_digest is not None:
            payload["request_digest"] = self.request_digest
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> FamilySweepRecord:
        stage = str(payload.get("stage") or "").strip()
        if stage not in {"discovery", "owner_fix", "verification", "scope_review"}:
            raise ValueError(f"unsupported family sweep stage: {stage!r}")
        actor_role = str(payload.get("actor_role") or "").strip()
        if actor_role not in {"reviewer", "planner", "producer"}:
            raise ValueError(f"unsupported family sweep actor_role: {actor_role!r}")
        return cls(
            id=str(payload["id"]),
            family_id=str(payload.get("family_id") or "").strip(),
            actor_role=actor_role,  # type: ignore[arg-type]
            stage=stage,  # type: ignore[arg-type]
            artifact_revision=int(payload.get("artifact_revision") or 0),
            artifact_digest=str(payload.get("artifact_digest") or "").strip(),
            finding_set_id=str(payload.get("finding_set_id") or "").strip(),
            searched_refs=[
                str(item).strip()
                for item in (payload.get("searched_refs") or [])
                if str(item).strip()
            ],
            search_dimensions=[
                str(item).strip()
                for item in (payload.get("search_dimensions") or [])
                if str(item).strip()
            ],
            additional_fixed_refs=parse_artifact_ref_list(
                payload.get("additional_fixed_refs")
            ),
            remaining_instance_refs=parse_artifact_ref_list(
                payload.get("remaining_instance_refs")
            ),
            completed=bool(payload.get("completed")),
            summary=str(payload.get("summary") or ""),
            evidence=[
                str(item)
                for item in (payload.get("evidence") or [])
                if str(item).strip()
            ],
            idempotency_key=(
                str(payload.get("idempotency_key")).strip()
                if payload.get("idempotency_key")
                else None
            ),
            request_digest=(
                str(payload.get("request_digest")).strip()
                if payload.get("request_digest")
                else None
            ),
        )


@dataclass
class AuditAttestationPass:
    pass_id: str
    completed: bool
    scope_id: str | None = None
    search_dimensions: list[str] = field(default_factory=list)
    inspected_refs: list[str] = field(default_factory=list)
    rubric_item_ids: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "pass_id": self.pass_id,
            "completed": self.completed,
            "search_dimensions": list(self.search_dimensions),
            "inspected_refs": list(self.inspected_refs),
            "rubric_item_ids": list(self.rubric_item_ids),
            "summary": self.summary,
        }
        if self.scope_id is not None:
            payload["scope_id"] = self.scope_id
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> AuditAttestationPass:
        return cls(
            pass_id=str(payload.get("pass_id") or "").strip(),
            completed=bool(payload.get("completed")),
            scope_id=(
                str(payload.get("scope_id")).strip()
                if payload.get("scope_id")
                else None
            ),
            search_dimensions=[
                str(item).strip()
                for item in (payload.get("search_dimensions") or [])
                if str(item).strip()
            ],
            inspected_refs=[
                str(item).strip()
                for item in (payload.get("inspected_refs") or [])
                if str(item).strip()
            ],
            rubric_item_ids=[
                str(item).strip()
                for item in (payload.get("rubric_item_ids") or [])
                if str(item).strip()
            ],
            summary=str(payload.get("summary") or ""),
        )


@dataclass
class AuditAttestationRun:
    id: str
    finding_set_id: str
    artifact_revision: int
    artifact_digest: str
    passes: list[AuditAttestationPass]
    recorded_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "finding_set_id": self.finding_set_id,
            "artifact_revision": self.artifact_revision,
            "artifact_digest": self.artifact_digest,
            "passes": [item.to_dict() for item in self.passes],
            "recorded_at": self.recorded_at,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> AuditAttestationRun:
        passes = [
            AuditAttestationPass.from_dict(item)
            for item in (payload.get("passes") or [])
            if isinstance(item, Mapping)
        ]
        return cls(
            id=str(payload["id"]),
            finding_set_id=str(payload.get("finding_set_id") or "").strip(),
            artifact_revision=int(payload.get("artifact_revision") or 0),
            artifact_digest=str(payload.get("artifact_digest") or "").strip(),
            passes=passes,
            recorded_at=str(payload.get("recorded_at") or ""),
        )


def _review_helpers():
    from top_down_planning.domain import reviews as reviews_mod

    return reviews_mod


def compute_family_fingerprint(
    *,
    rule_id: str,
    subject_key: str,
    scope_kind: FamilyScopeKind,
    rule_definition: str | None = None,
) -> str:
    normalized_subject = normalize_subject_key(subject_key)
    validated_rule = validate_rule_id(rule_id)
    payload: dict[str, Any] = {
        "rule_id": validated_rule,
        "subject_key": normalized_subject,
        "scope_kind": scope_kind,
        "protocol_version": fingerprint_protocol_version(),
    }
    if is_custom_rule_id(validated_rule):
        if rule_definition is None:
            raise ValueError("custom rules require rule_definition for fingerprint")
        payload["rule_definition"] = normalize_rule_definition(rule_definition)
    return digest_canonical_payload(payload)


def family_by_id(loop: ReviewLoop, family_id: str) -> FindingFamily | None:
    for family in loop.finding_families:
        if family.id == family_id:
            return family
    return None


def family_findings(
    loop: ReviewLoop,
    family_id: str,
    *,
    finding_set_id: str | None = None,
) -> list[ReviewFinding]:
    family = family_by_id(loop, family_id)
    if family is None:
        return []
    set_id = finding_set_id or family.finding_set_id
    confirmed = set(family.confirmed_finding_ids)
    scoped_ids: set[str] | None = None
    if finding_set_id is not None:
        scoped_ids = set(loop.finding_ids_by_set.get(set_id, []))
    return [
        finding
        for finding in loop.findings
        if finding.family_id == family_id
        and finding.id in confirmed
        and (scoped_ids is None or finding.id in scoped_ids)
    ]


def _effective_actions(
    loop: ReviewLoop,
    proposed_actions: Sequence[FindingAction] = (),
) -> dict[str, FindingAction]:
    reviews = _review_helpers()
    finding_set_id = str(loop.finding_set_id or "").strip() or None
    merged = list(loop.finding_actions) + list(proposed_actions)
    return reviews.effective_owner_actions(merged, finding_set_id=finding_set_id)


def family_required_members(
    loop: ReviewLoop,
    family_id: str,
) -> list[ReviewFinding]:
    reviews = _review_helpers()
    threshold = reviews.loop_revise_at(loop)
    return [
        finding
        for finding in family_findings(loop, family_id)
        if severity_at_or_above(finding.severity, threshold)
    ]


def family_open_required_members(
    loop: ReviewLoop,
    family_id: str,
) -> list[ReviewFinding]:
    reviews = _review_helpers()
    return [
        finding
        for finding in family_required_members(loop, family_id)
        if reviews.is_open_finding_status(finding.status)
    ]


def family_verification_members(
    loop: ReviewLoop,
    family_id: str,
    proposed_actions: Sequence[FindingAction] = (),
) -> list[ReviewFinding]:
    effective = _effective_actions(loop, proposed_actions)
    members: list[ReviewFinding] = []
    for finding in family_findings(loop, family_id):
        action = effective.get(finding.id)
        if action is not None and action.action in {"fix", "challenge"}:
            members.append(finding)
    return members


def family_unverified_members(
    loop: ReviewLoop,
    family_id: str,
    proposed_actions: Sequence[FindingAction] = (),
) -> list[ReviewFinding]:
    reviews = _review_helpers()
    return [
        finding
        for finding in family_verification_members(
            loop,
            family_id,
            proposed_actions,
        )
        if reviews.is_open_finding_status(finding.status)
    ]


def family_verification_sweeps(
    loop: ReviewLoop,
    family_id: str,
) -> list[FamilySweepRecord]:
    return [
        sweep
        for sweep in loop.family_sweeps
        if sweep.family_id == family_id and sweep.stage == "verification"
    ]


def family_owner_sweeps(loop: ReviewLoop, family_id: str) -> list[FamilySweepRecord]:
    return [
        sweep
        for sweep in loop.family_sweeps
        if sweep.family_id == family_id and sweep.stage == "owner_fix"
    ]


def family_reviewer_sweeps(
    loop: ReviewLoop,
    family_id: str,
) -> list[FamilySweepRecord]:
    return [
        sweep
        for sweep in loop.family_sweeps
        if sweep.family_id == family_id
        and sweep.stage in {"verification", "discovery", "scope_review"}
    ]


def family_discovery_sweep(
    loop: ReviewLoop,
    family_id: str,
    *,
    artifact_revision: int | None = None,
    artifact_digest: str | None = None,
) -> FamilySweepRecord | None:
    matching = [
        sweep
        for sweep in loop.family_sweeps
        if sweep.family_id == family_id
        and sweep.stage in {"discovery", "scope_review"}
        and (
            artifact_revision is None
            or sweep.artifact_revision == artifact_revision
        )
        and (
            artifact_digest is None
            or sweep.artifact_digest == artifact_digest
        )
    ]
    return matching[-1] if matching else None


def _audit_passes_completed_for_artifact(
    loop: ReviewLoop,
    *,
    artifact_revision: int | None = None,
    artifact_digest: str | None = None,
) -> int:
    matching = [
        run
        for run in loop.audit_runs
        if (
            artifact_revision is None
            or run.artifact_revision == artifact_revision
        )
        and (
            artifact_digest is None
            or run.artifact_digest == artifact_digest
        )
    ]
    if not matching:
        return 0
    latest = matching[-1]
    return sum(1 for audit_pass in latest.passes if audit_pass.completed)


def family_requires_owner_sweep(
    loop: ReviewLoop,
    family_id: str,
    proposed_actions: Sequence[FindingAction] = (),
) -> bool:
    effective = _effective_actions(loop, proposed_actions)
    for finding in family_verification_members(loop, family_id, proposed_actions):
        action = effective.get(finding.id)
        if action is not None and action.action == "fix":
            return True
    return False


def family_requires_reviewer_verification(
    loop: ReviewLoop,
    family_id: str,
    proposed_actions: Sequence[FindingAction] = (),
) -> bool:
    return bool(family_verification_members(loop, family_id, proposed_actions))


def _has_valid_verification_sweep(
    loop: ReviewLoop,
    family_id: str,
    *,
    artifact_revision: int | None = None,
    artifact_digest: str | None = None,
) -> bool:
    for sweep in reversed(family_verification_sweeps(loop, family_id)):
        if not sweep.completed:
            continue
        if artifact_revision is not None and sweep.artifact_revision != artifact_revision:
            continue
        if artifact_digest is not None and sweep.artifact_digest != artifact_digest:
            continue
        return True
    return False


def _has_valid_owner_sweep(
    loop: ReviewLoop,
    family_id: str,
    *,
    artifact_revision: int | None = None,
    artifact_digest: str | None = None,
) -> bool:
    sweeps = family_owner_sweeps(loop, family_id)
    for sweep in reversed(sweeps):
        if not sweep.completed:
            continue
        if sweep.remaining_instance_refs:
            continue
        if artifact_revision is not None and sweep.artifact_revision != artifact_revision:
            continue
        if artifact_digest is not None and sweep.artifact_digest != artifact_digest:
            continue
        return True
    return False


def derive_family_operational_status(
    loop: ReviewLoop,
    family_id: str,
    proposed_actions: Sequence[FindingAction] = (),
    *,
    artifact_revision: int | None = None,
    artifact_digest: str | None = None,
) -> FamilyOperationalStatus:
    effective = _effective_actions(loop, proposed_actions)
    for finding in family_open_required_members(loop, family_id):
        action = effective.get(finding.id)
        if action is None or action.action not in {"fix", "challenge"}:
            return "open"
    if family_requires_owner_sweep(loop, family_id, proposed_actions):
        if not _has_valid_owner_sweep(
            loop,
            family_id,
            artifact_revision=artifact_revision,
            artifact_digest=artifact_digest,
        ):
            return "owner_sweep_pending"
    if family_unverified_members(loop, family_id, proposed_actions):
        return "verification_pending"
    if family_requires_reviewer_verification(loop, family_id, proposed_actions):
        if not _has_valid_verification_sweep(
            loop,
            family_id,
            artifact_revision=artifact_revision,
            artifact_digest=artifact_digest,
        ):
            return "verification_pending"
    return "closed"


def family_has_open_policy_relevant_members(
    loop: ReviewLoop,
    family_id: str,
    proposed_actions: Sequence[FindingAction] = (),
) -> bool:
    return bool(family_open_required_members(loop, family_id)) or bool(
        family_unverified_members(loop, family_id, proposed_actions)
    )


def family_permits_approval(
    loop: ReviewLoop,
    family_id: str,
    proposed_actions: Sequence[FindingAction] = (),
    *,
    artifact_revision: int | None = None,
    artifact_digest: str | None = None,
) -> bool:
    return (
        derive_family_operational_status(
            loop,
            family_id,
            proposed_actions,
            artifact_revision=artifact_revision,
            artifact_digest=artifact_digest,
        )
        == "closed"
    )


def active_families(
    loop: ReviewLoop,
    *,
    artifact_revision: int | None = None,
    artifact_digest: str | None = None,
) -> list[FindingFamily]:
    finding_set_id = str(loop.finding_set_id or "").strip()
    active: list[FindingFamily] = []
    for family in loop.finding_families:
        if family.finding_set_id != finding_set_id:
            continue
        if (
            derive_family_operational_status(
                loop,
                family.id,
                artifact_revision=artifact_revision,
                artifact_digest=artifact_digest,
            )
            != "closed"
        ):
            active.append(family)
    return active


def families_requiring_verification_approval(
    loop: ReviewLoop,
    *,
    artifact_revision: int | None = None,
    artifact_digest: str | None = None,
) -> list[FindingFamily]:
    finding_set_id = str(loop.finding_set_id or "").strip()
    blocking: list[FindingFamily] = []
    for family in loop.finding_families:
        if family.finding_set_id != finding_set_id:
            continue
        if not family_requires_reviewer_verification(loop, family.id):
            continue
        if not family_permits_approval(
            loop,
            family.id,
            artifact_revision=artifact_revision,
            artifact_digest=artifact_digest,
        ):
            blocking.append(family)
    return blocking


def required_open_family_ids(
    loop: ReviewLoop,
    *,
    artifact_revision: int | None = None,
    artifact_digest: str | None = None,
) -> list[str]:
    return sorted(
        family.id
        for family in active_families(
            loop,
            artifact_revision=artifact_revision,
            artifact_digest=artifact_digest,
        )
    )


def compute_effective_fix_target_ids(
    loop: ReviewLoop,
    family_id: str,
    *,
    target_finding_ids: Sequence[str],
    challenged_required_ids: set[str],
) -> list[str]:
    reviews = _review_helpers()
    family = family_by_id(loop, family_id)
    if family is None:
        raise ValueError(f"unknown family_id {family_id!r}")
    confirmed_ids = set(family.confirmed_finding_ids)
    required_ids = {
        finding.id for finding in family_required_members(loop, family_id)
    }
    optional_targets: set[str] = set()
    for finding_id in target_finding_ids:
        if finding_id in required_ids:
            continue
        finding = reviews.finding_by_id(loop.findings, finding_id)
        if finding is None or finding.family_id != family_id:
            raise ValueError(
                f"optional target_finding_ids entry {finding_id!r} must belong to "
                f"family {family_id!r}"
            )
        if finding_id not in confirmed_ids:
            raise ValueError(
                f"optional target_finding_ids entry {finding_id!r} is not a "
                f"confirmed member of family {family_id!r}"
            )
        optional_targets.add(finding_id)
    required_open = {
        finding.id
        for finding in family_open_required_members(loop, family_id)
        if finding.id not in challenged_required_ids
    }
    effective = sorted(required_open | optional_targets)
    for finding_id in effective:
        finding = reviews.finding_by_id(loop.findings, finding_id)
        if finding is None or finding.family_id != family_id:
            raise ValueError(
                f"effective fix target {finding_id!r} must belong to family {family_id!r}"
            )
    return effective


def family_fix_idempotency_key(
    *,
    family_id: str,
    finding_set_id: str,
    artifact_revision: int,
    artifact_digest: str,
    actor_role: str,
) -> str:
    return digest_canonical_payload(
        {
            "family_id": family_id,
            "finding_set_id": finding_set_id,
            "artifact_revision": artifact_revision,
            "artifact_digest": artifact_digest,
            "actor_role": actor_role,
        }
    )


def compute_family_fix_request_digest(
    *,
    effective_fix_target_ids: Sequence[str],
    rationale: str,
    changed_refs: Sequence[str],
    owner_sweep: Mapping[str, Any],
) -> str:
    return digest_canonical_payload(
        {
            "effective_fix_target_ids": sorted(effective_fix_target_ids),
            "rationale": rationale,
            "changed_refs": sorted(changed_refs),
            "owner_sweep": dict(owner_sweep),
        }
    )


def find_closed_family_by_fingerprint(
    loop: ReviewLoop,
    fingerprint: str,
) -> FindingFamily | None:
    matches = [
        family
        for family in loop.finding_families
        if family.family_fingerprint == fingerprint
        and derive_family_operational_status(loop, family.id) == "closed"
    ]
    if not matches:
        return None
    return matches[-1]


def family_disposition_counts(
    loop: ReviewLoop,
    family_id: str,
    proposed_actions: Sequence[FindingAction] = (),
) -> dict[str, int]:
    effective = _effective_actions(loop, proposed_actions)
    counts = {
        "fixed_member_count": 0,
        "invalid_member_count": 0,
        "superseded_member_count": 0,
        "deferred_member_count": 0,
        "accepted_as_is_member_count": 0,
    }
    for finding in family_findings(loop, family_id):
        if finding.status == "invalid":
            counts["invalid_member_count"] += 1
        elif finding.status == "superseded":
            counts["superseded_member_count"] += 1
        else:
            action = effective.get(finding.id)
            if action is not None and action.action == "fix":
                counts["fixed_member_count"] += 1
            elif action is not None and action.action == "defer":
                counts["deferred_member_count"] += 1
            elif action is not None and action.action == "accept_as_is":
                counts["accepted_as_is_member_count"] += 1
    return counts


def instance_ref_matches_prior(
    instance_ref: ArtifactRef | None,
    prior: ReviewFinding,
) -> bool:
    if instance_ref is None or prior.instance_ref is None:
        return False
    return artifact_refs_equal(instance_ref, prior.instance_ref)


def validate_candidate_refs_do_not_duplicate_confirmed(
    family: FindingFamily,
    findings_by_id: Mapping[str, ReviewFinding],
) -> None:
    confirmed_refs = []
    for finding_id in family.confirmed_finding_ids:
        finding = findings_by_id.get(finding_id)
        if finding is not None and finding.instance_ref is not None:
            confirmed_refs.append(finding.instance_ref)
    for candidate in family.candidate_refs:
        for confirmed in confirmed_refs:
            if artifact_refs_equal(candidate, confirmed):
                raise ValueError(
                    "candidate_refs must not duplicate confirmed finding instance_ref"
                )


def parse_finding_families(raw: Any) -> list[FindingFamily]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("finding_families must be a list")
    return [FindingFamily.from_dict(item) for item in raw if isinstance(item, Mapping)]


def parse_family_sweeps(raw: Any) -> list[FamilySweepRecord]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("family_sweeps must be a list")
    return [FamilySweepRecord.from_dict(item) for item in raw if isinstance(item, Mapping)]


def parse_audit_runs(raw: Any) -> list[AuditAttestationRun]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("audit_runs must be a list")
    return [AuditAttestationRun.from_dict(item) for item in raw if isinstance(item, Mapping)]


def family_observability_fields(
    loop: ReviewLoop,
    *,
    artifact_revision: int | None = None,
    artifact_digest: str | None = None,
) -> dict[str, Any]:
    """Derived family and audit counters for review responses and snapshots."""

    from top_down_planning.domain.reviews import loop_uses_finding_families

    if not loop_uses_finding_families(loop):
        return {}

    required_open = required_open_family_ids(
        loop,
        artifact_revision=artifact_revision,
        artifact_digest=artifact_digest,
    )
    awaiting_owner: list[str] = []
    awaiting_verification: list[str] = []
    for family in active_families(
        loop,
        artifact_revision=artifact_revision,
        artifact_digest=artifact_digest,
    ):
        status = derive_family_operational_status(
            loop,
            family.id,
            artifact_revision=artifact_revision,
            artifact_digest=artifact_digest,
        )
        if status == "owner_sweep_pending":
            awaiting_owner.append(family.id)
        elif status == "verification_pending":
            awaiting_verification.append(family.id)

    audit_completed = _audit_passes_completed_for_artifact(
        loop,
        artifact_revision=artifact_revision,
        artifact_digest=artifact_digest,
    )

    return {
        "family_count": len(loop.finding_families),
        "required_open_family_count": len(required_open),
        "required_open_family_ids": required_open,
        "families_awaiting_owner_sweep": awaiting_owner,
        "families_awaiting_verification": awaiting_verification,
        "regressed_family_count": sum(
            1 for family in loop.finding_families if family.reopens_family_id
        ),
        "audit_passes_completed": audit_completed,
        "audit_passes_required": len(mandatory_audit_pass_ids_for_loop(loop)),
    }


def build_active_family_view(
    loop: ReviewLoop,
    *,
    artifact_revision: int | None = None,
    artifact_digest: str | None = None,
) -> dict[str, Any]:
    finding_set_id = str(loop.finding_set_id or "").strip()
    families = []
    for family in active_families(
        loop,
        artifact_revision=artifact_revision,
        artifact_digest=artifact_digest,
    ):
        members = [
            finding.to_dict()
            for finding in loop.findings
            if finding.family_id == family.id
            and finding.id in set(family.confirmed_finding_ids)
        ]
        family_payload: dict[str, Any] = {
            **family.to_dict(),
            "members": members,
            "operational_status": derive_family_operational_status(
                loop,
                family.id,
                artifact_revision=artifact_revision,
                artifact_digest=artifact_digest,
            ),
            "disposition_counts": family_disposition_counts(loop, family.id),
        }
        discovery = family_discovery_sweep(
            loop,
            family.id,
            artifact_revision=artifact_revision,
            artifact_digest=artifact_digest,
        )
        if discovery is not None:
            family_payload["discovery_sweep"] = {
                "search_dimensions": list(discovery.search_dimensions),
                "searched_refs": list(discovery.searched_refs),
                "completed": discovery.completed,
            }
        families.append(family_payload)
    return {
        "finding_set_id": finding_set_id or None,
        "families": families,
        "required_open_family_ids": required_open_family_ids(
            loop,
            artifact_revision=artifact_revision,
            artifact_digest=artifact_digest,
        ),
    }


def build_family_verification_view(
    loop: ReviewLoop,
    *,
    artifact_revision: int | None = None,
    artifact_digest: str | None = None,
) -> dict[str, Any]:
    finding_set_id = str(loop.finding_set_id or "").strip()
    families = []
    for family in active_families(
        loop,
        artifact_revision=artifact_revision,
        artifact_digest=artifact_digest,
    ):
        families.append(
            {
                **family.to_dict(),
                "owner_sweeps": [
                    sweep.to_dict()
                    for sweep in family_owner_sweeps(loop, family.id)
                ],
                "reviewer_sweeps": [
                    sweep.to_dict()
                    for sweep in family_reviewer_sweeps(loop, family.id)
                ],
                "operational_status": derive_family_operational_status(
                    loop,
                    family.id,
                    artifact_revision=artifact_revision,
                    artifact_digest=artifact_digest,
                ),
            }
        )
    return {
        "finding_set_id": finding_set_id or None,
        "families": families,
    }
