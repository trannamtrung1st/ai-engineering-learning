"""Mandatory family verification merge and closure gates."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any
from uuid import uuid4

from top_down_planning.domain.artifact_refs import (
    parse_artifact_ref_list,
    validate_artifact_ref_kinds,
)
from top_down_planning.domain.finding_families import (
    FAMILY_RESULT_DISPOSITIONS,
    FamilySweepRecord,
    active_families,
    derive_family_operational_status,
    families_requiring_verification_approval,
    family_by_id,
)
from top_down_planning.domain.reviews import (
    FindingVerificationResult,
    ReviewFinding,
    ReviewLoop,
    merge_verification_findings,
    parse_reported_findings,
    record_discovery_finding_ids,
)


def _new_sweep_id() -> str:
    return f"sweep-{uuid4().hex[:12]}"


def _parse_verification_sweep(
    sweep_raw: Mapping[str, Any],
    *,
    family_id: str,
    finding_set_id: str,
    artifact_revision: int,
    artifact_digest: str,
) -> FamilySweepRecord:
    sweep_revision = sweep_raw.get("artifact_revision")
    if sweep_revision is None:
        raise ValueError(f"family {family_id!r} verification_sweep requires artifact_revision")
    if int(sweep_revision) != artifact_revision:
        raise ValueError(f"family {family_id!r} verification_sweep artifact_revision mismatch")
    sweep_digest = str(sweep_raw.get("artifact_digest") or "").strip()
    if not sweep_digest:
        raise ValueError(f"family {family_id!r} verification_sweep requires artifact_digest")
    if sweep_digest != artifact_digest:
        raise ValueError(f"family {family_id!r} verification_sweep artifact_digest mismatch")
    completed = bool(sweep_raw.get("completed"))
    searched_refs = [
        str(item).strip()
        for item in (sweep_raw.get("searched_refs") or [])
        if str(item).strip()
    ]
    search_dimensions = [
        str(item).strip()
        for item in (sweep_raw.get("search_dimensions") or [])
        if str(item).strip()
    ]
    summary = str(sweep_raw.get("summary") or "").strip()
    if completed:
        if not searched_refs:
            raise ValueError(
                f"family {family_id!r} completed verification_sweep requires searched_refs"
            )
        if not search_dimensions:
            raise ValueError(
                f"family {family_id!r} completed verification_sweep requires "
                "search_dimensions"
            )
        if not summary:
            raise ValueError(
                f"family {family_id!r} completed verification_sweep requires summary"
            )
    return FamilySweepRecord(
        id=_new_sweep_id(),
        family_id=family_id,
        actor_role="reviewer",
        stage="verification",
        artifact_revision=artifact_revision,
        artifact_digest=artifact_digest,
        finding_set_id=finding_set_id,
        searched_refs=searched_refs,
        search_dimensions=search_dimensions,
        additional_fixed_refs=[],
        remaining_instance_refs=parse_artifact_ref_list(
            sweep_raw.get("remaining_instance_refs")
        ),
        completed=completed,
        summary=summary,
        evidence=[
            str(item)
            for item in (sweep_raw.get("evidence") or [])
            if str(item).strip()
        ],
    )


def merge_mandatory_family_verification(
    loop: ReviewLoop,
    request: dict[str, Any],
    *,
    artifact_revision: int,
    artifact_digest: str,
    allowed_artifact_ref_kinds: frozenset[str] = frozenset(),
) -> tuple[list[ReviewFinding], FindingVerificationResult, ReviewLoop, list[dict[str, Any]]]:
    findings, result = merge_verification_findings(loop, request)
    raw_results = request.get("family_results") or []
    if not isinstance(raw_results, list):
        raise ValueError("family_results must be a list")

    updated_loop = replace(loop, findings=findings)
    new_sweeps: list[FamilySweepRecord] = []
    events: list[dict[str, Any]] = []
    finding_set_id = str(loop.finding_set_id or "").strip()
    appended_findings: list[ReviewFinding] = []

    active = active_families(
        updated_loop,
        artifact_revision=artifact_revision,
        artifact_digest=artifact_digest,
    )
    if raw_results or active:
        results_by_family = {}
        for raw in raw_results:
            if not isinstance(raw, Mapping):
                raise ValueError("each family_result must be an object")
            family_id = str(raw.get("family_id") or "").strip()
            results_by_family[family_id] = raw
        for family in active:
            raw = results_by_family.get(family.id)
            if raw is None:
                raise ValueError(
                    f"missing family_result for active family {family.id!r}"
                )
            disposition = str(raw.get("disposition") or "").strip()
            if disposition not in FAMILY_RESULT_DISPOSITIONS:
                raise ValueError(
                    f"family {family.id!r} disposition must be one of "
                    f"{sorted(FAMILY_RESULT_DISPOSITIONS)}"
                )
            sweep_raw = raw.get("verification_sweep")
            if not isinstance(sweep_raw, Mapping):
                raise ValueError(
                    f"family {family.id!r} requires verification_sweep"
                )
            new_sweeps.append(
                _parse_verification_sweep(
                    sweep_raw,
                    family_id=family.id,
                    finding_set_id=finding_set_id,
                    artifact_revision=artifact_revision,
                    artifact_digest=artifact_digest,
                )
            )
            if allowed_artifact_ref_kinds:
                validate_artifact_ref_kinds(
                    parse_artifact_ref_list(sweep_raw.get("remaining_instance_refs")),
                    allowed_artifact_ref_kinds,
                    context=f"family {family.id!r} remaining_instance_refs",
                )
            remaining_findings = raw.get("remaining_instance_findings") or []
            if remaining_findings:
                appended = parse_reported_findings(
                    {"reported_findings": remaining_findings}
                )
                for finding in appended:
                    if finding.family_id != family.id:
                        raise ValueError(
                            "remaining_instance_findings must belong to family"
                        )
                    if finding.instance_ref is not None and allowed_artifact_ref_kinds:
                        validate_artifact_ref_kinds(
                            [finding.instance_ref],
                            allowed_artifact_ref_kinds,
                            context=f"finding {finding.id!r} instance_ref",
                        )
                appended_findings.extend(appended)
                updated_loop = replace(
                    updated_loop,
                    findings=list(updated_loop.findings) + appended,
                )
                family_obj = family_by_id(updated_loop, family.id)
                if family_obj is not None:
                    extended_ids = list(family_obj.confirmed_finding_ids)
                    for finding in appended:
                        if finding.id not in extended_ids:
                            extended_ids.append(finding.id)
                    updated_families = []
                    for item in updated_loop.finding_families:
                        if item.id == family.id:
                            updated_families.append(
                                replace(item, confirmed_finding_ids=extended_ids)
                            )
                        else:
                            updated_families.append(item)
                    updated_loop = replace(
                        updated_loop,
                        finding_families=updated_families,
                    )
            if disposition == "closed":
                if remaining_findings:
                    raise ValueError(
                        f"family {family.id!r} cannot close with "
                        "remaining_instance_findings"
                    )
                if parse_artifact_ref_list(
                    sweep_raw.get("remaining_instance_refs")
                ):
                    raise ValueError(
                        f"family {family.id!r} cannot close with remaining_instance_refs"
                    )
            events.append(
                {
                    "type": "review_family_verification_recorded",
                    "loop_id": loop.id,
                    "family_id": family.id,
                    "disposition": disposition,
                }
            )

    if appended_findings and finding_set_id:
        updated_loop = replace(
            updated_loop,
            finding_ids_by_set=record_discovery_finding_ids(
                updated_loop,
                finding_set_id,
                appended_findings,
            ),
        )

    updated_loop = replace(
        updated_loop,
        family_sweeps=list(updated_loop.family_sweeps) + new_sweeps,
    )

    if str(request.get("decision") or "") == "verified":
        for family in active:
            raw = results_by_family.get(family.id)
            if raw is None:
                continue
            disposition = str(raw.get("disposition") or "").strip()
            if disposition != "closed":
                events.append(
                    {
                        "type": "review_family_closure_blocked",
                        "loop_id": loop.id,
                        "family_id": family.id,
                        "stage": "finding_verification",
                        "reason": "disposition_not_closed",
                    }
                )
                raise ValueError(
                    f"verified rejected: family {family.id!r} requires "
                    "disposition closed"
                )
        for family in families_requiring_verification_approval(
            updated_loop,
            artifact_revision=artifact_revision,
            artifact_digest=artifact_digest,
        ):
            events.append(
                {
                    "type": "review_family_closure_blocked",
                    "loop_id": loop.id,
                    "family_id": family.id,
                    "stage": "finding_verification",
                    "reason": "operational_status_open",
                }
            )
            raise ValueError(
                f"verified rejected: family {family.id!r} status "
                f"{derive_family_operational_status(updated_loop, family.id, artifact_revision=artifact_revision, artifact_digest=artifact_digest)!r}"
            )

    return updated_loop.findings, result, updated_loop, events
