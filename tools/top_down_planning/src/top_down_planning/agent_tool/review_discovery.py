"""Whole-plan discovery respond parsing and application."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from top_down_planning.domain.artifact_refs import parse_artifact_ref_list
from top_down_planning.domain.finding_families import (
    AuditAttestationPass,
    AuditAttestationRun,
    FamilySweepRecord,
    FindingFamily,
    compute_family_fingerprint,
    find_closed_family_by_fingerprint,
    instance_ref_matches_prior,
    validate_candidate_refs_do_not_duplicate_confirmed,
)
from top_down_planning.domain.reviews import (
    DiscoveryDerivedOutcome,
    ReviewFinding,
    ReviewLoop,
    derive_discovery_outcome,
    assert_reported_finding_ids_unused,
    finding_by_id,
    is_mandatory_review_loop,
    is_scope_review_stage_name,
    loop_revise_at,
    map_discovery_outcome_to_loop_status,
    merge_discovery_findings,
    parse_discovery_respond_findings,
    parse_reported_findings,
    parse_request_finding_actions,
    record_discovery_finding_ids,
    validate_finding_set_id_echo,
)
from top_down_planning.orchestrator.review_analysis_context import (
    required_audit_passes,
    rubric_items_with_ids,
)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def _reject_agent_reopen_fields(request: Mapping[str, Any]) -> None:
    for family in request.get("finding_families") or []:
        if not isinstance(family, Mapping):
            continue
        if family.get("reopens_family_id"):
            raise ValueError("agents must not submit reopens_family_id on discovery")
    for finding in request.get("reported_findings") or []:
        if not isinstance(finding, Mapping):
            continue
        if finding.get("reopens_finding_id"):
            raise ValueError("agents must not submit reopens_finding_id on discovery")


def _validate_audit_attestation(
    request: Mapping[str, Any],
    *,
    review_type: str,
    artifact_revision: int,
    artifact_digest: str,
    rubric_items: Sequence[Mapping[str, str]],
    review_completed: bool,
) -> AuditAttestationRun | None:
    raw = request.get("audit_attestation")
    if raw is None:
        if review_completed:
            raise ValueError("completed discovery requires audit_attestation")
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("audit_attestation must be an object")
    if int(raw.get("artifact_revision") or 0) != artifact_revision:
        raise ValueError("audit_attestation artifact_revision mismatch")
    if str(raw.get("artifact_digest") or "").strip() != artifact_digest:
        raise ValueError("audit_attestation artifact_digest mismatch")
    required_passes = set(required_audit_passes(review_type))
    passes_raw = raw.get("passes") or []
    if not isinstance(passes_raw, list):
        raise ValueError("audit_attestation.passes must be a list")
    seen: set[str] = set()
    parsed_passes: list[AuditAttestationPass] = []
    for item in passes_raw:
        if not isinstance(item, Mapping):
            raise ValueError("each audit pass must be an object")
        pass_id = str(item.get("pass_id") or "").strip()
        if not pass_id:
            raise ValueError("audit pass requires pass_id")
        if pass_id in seen:
            raise ValueError(f"duplicate audit pass_id {pass_id!r}")
        seen.add(pass_id)
        parsed_passes.append(AuditAttestationPass.from_dict(item))
    if review_completed:
        if seen != required_passes:
            missing = required_passes - seen
            extra = seen - required_passes
            if missing:
                raise ValueError(f"audit attestation missing passes: {sorted(missing)}")
            if extra:
                raise ValueError(f"audit attestation has unknown passes: {sorted(extra)}")
        for item in parsed_passes:
            if not item.completed:
                raise ValueError(f"audit pass {item.pass_id!r} must be completed")
        required_rubric_ids = {item["id"] for item in rubric_items}
        covered: set[str] = set()
        for item in parsed_passes:
            covered.update(item.rubric_item_ids)
        if covered != required_rubric_ids:
            raise ValueError("audit attestation rubric_item_ids union mismatch")
    finding_set_id = str(request.get("finding_set_id") or "").strip()
    return AuditAttestationRun(
        id=_new_id("audit"),
        finding_set_id=finding_set_id,
        artifact_revision=artifact_revision,
        artifact_digest=artifact_digest,
        passes=parsed_passes,
        recorded_at=datetime.now(timezone.utc).isoformat(),
    )


def _normalize_discovery_sweep(
    family: FindingFamily,
    sweep_raw: Mapping[str, Any],
    *,
    finding_set_id: str,
    stage: str,
    actor_role: str,
    artifact_revision: int,
    artifact_digest: str,
) -> FamilySweepRecord:
    if sweep_raw.get("remaining_instance_refs"):
        raise ValueError(
            f"family {family.id!r} discovery_sweep must not include "
            "remaining_instance_refs"
        )
    sweep_revision = sweep_raw.get("artifact_revision")
    if sweep_revision is None:
        raise ValueError("discovery_sweep requires artifact_revision")
    if int(sweep_revision) != artifact_revision:
        raise ValueError("discovery_sweep artifact_revision mismatch")
    sweep_digest = str(sweep_raw.get("artifact_digest") or "").strip()
    if not sweep_digest:
        raise ValueError("discovery_sweep requires artifact_digest")
    if sweep_digest != artifact_digest:
        raise ValueError("discovery_sweep artifact_digest mismatch")
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
                f"family {family.id!r} completed discovery_sweep requires "
                "searched_refs"
            )
        if not search_dimensions:
            raise ValueError(
                f"family {family.id!r} completed discovery_sweep requires "
                "search_dimensions"
            )
        if not summary:
            raise ValueError(
                f"family {family.id!r} completed discovery_sweep requires summary"
            )
    return FamilySweepRecord(
        id=_new_id("sweep"),
        family_id=family.id,
        actor_role=actor_role,  # type: ignore[arg-type]
        stage=stage,  # type: ignore[arg-type]
        artifact_revision=artifact_revision,
        artifact_digest=artifact_digest,
        finding_set_id=finding_set_id,
        searched_refs=searched_refs,
        search_dimensions=search_dimensions,
        additional_fixed_refs=[],
        remaining_instance_refs=[],
        completed=completed,
        summary=summary,
        evidence=[
            str(item)
            for item in (sweep_raw.get("evidence") or [])
            if str(item).strip()
        ],
    )


def _parse_whole_plan_families(
    request: Mapping[str, Any],
    *,
    loop: ReviewLoop,
    finding_set_id: str,
    stage: str,
    review_completed: bool,
    artifact_revision: int,
    artifact_digest: str,
) -> tuple[list[FindingFamily], list[FamilySweepRecord], list[ReviewFinding]]:
    raw_families = request.get("finding_families") or []
    if not isinstance(raw_families, list):
        raise ValueError("finding_families must be a list")
    seen_family_ids: set[str] = set()
    families: list[FindingFamily] = []
    sweeps: list[FamilySweepRecord] = []
    for raw in raw_families:
        if not isinstance(raw, Mapping):
            raise ValueError("each finding family must be an object")
        family_id = str(raw.get("id") or "").strip()
        if not family_id:
            raise ValueError("each finding family requires id")
        if family_id in seen_family_ids:
            raise ValueError(f"duplicate finding family id {family_id!r}")
        seen_family_ids.add(family_id)
        sweep_raw = raw.get("discovery_sweep")
        if not isinstance(sweep_raw, Mapping):
            raise ValueError("each finding family requires discovery_sweep")
        family_payload = dict(raw)
        family_payload.pop("discovery_sweep", None)
        family_payload.setdefault("finding_set_id", finding_set_id)
        fingerprint = compute_family_fingerprint(
            rule_id=str(family_payload.get("rule_id") or ""),
            subject_key=str(family_payload.get("subject_key") or ""),
            scope_kind=str(family_payload.get("scope_kind") or "active-plan"),  # type: ignore[arg-type]
            rule_definition=(
                str(family_payload.get("rule_definition"))
                if family_payload.get("rule_definition")
                else None
            ),
        )
        family_payload["family_fingerprint"] = fingerprint
        family = FindingFamily.from_dict(family_payload)
        if family.finding_set_id != finding_set_id:
            raise ValueError("family finding_set_id must match active discovery set")
        if review_completed and not bool(sweep_raw.get("completed")):
            raise ValueError(
                f"family {family.id!r} discovery_sweep must be completed"
            )
        prior = find_closed_family_by_fingerprint(loop, fingerprint)
        if prior is not None:
            family = replace(family, reopens_family_id=prior.id)
        families.append(family)
        sweeps.append(
            _normalize_discovery_sweep(
                family,
                sweep_raw,
                finding_set_id=finding_set_id,
                stage="scope_review" if stage == "scope_review" else "discovery",
                actor_role="reviewer",
                artifact_revision=artifact_revision,
                artifact_digest=artifact_digest,
            )
        )
    reported = parse_discovery_respond_findings(loop, request)
    findings_by_id = {finding.id: finding for finding in reported}
    if review_completed:
        for finding in reported:
            if not finding.family_id:
                raise ValueError(f"finding {finding.id!r} requires family_id")
            if finding.instance_ref is None:
                raise ValueError(f"finding {finding.id!r} requires instance_ref")
        if reported and not families:
            raise ValueError(
                "completed discovery with reported_findings requires finding_families"
            )
        family_ids = {family.id for family in families}
        for finding in reported:
            if finding.family_id not in family_ids:
                raise ValueError(
                    f"finding {finding.id!r} references unknown family_id "
                    f"{finding.family_id!r}"
                )
    for family in families:
        if set(family.confirmed_finding_ids) != {
            finding.id
            for finding in reported
            if finding.family_id == family.id
        }:
            raise ValueError(
                f"family {family.id!r} confirmed_finding_ids must match reported findings"
            )
        validate_candidate_refs_do_not_duplicate_confirmed(
            family,
            findings_by_id,
        )
    if review_completed:
        reported_ids = {finding.id for finding in reported}
        family_finding_ids = {
            finding_id
            for family in families
            for finding_id in family.confirmed_finding_ids
        }
        if reported_ids != family_finding_ids:
            raise ValueError(
                "reported_findings must match the union of family confirmed_finding_ids"
            )
    for family in families:
        if family.reopens_family_id:
            prior = find_closed_family_by_fingerprint(loop, family.family_fingerprint)
            if prior is None:
                continue
            for finding in reported:
                if finding.family_id != family.id:
                    continue
                for prior_finding in prior.confirmed_finding_ids:
                    prior_obj = finding_by_id(loop.findings, prior_finding)
                    if prior_obj is None:
                        continue
                    if instance_ref_matches_prior(finding.instance_ref, prior_obj):
                        idx = reported.index(finding)
                        reported[idx] = replace(
                            finding,
                            reopens_finding_id=prior_obj.id,
                        )
    return families, sweeps, reported


def apply_whole_plan_discovery_response(
    loop: ReviewLoop,
    request: Mapping[str, Any],
    *,
    stage: str | None,
    review_type: str,
    artifact_revision: int,
    artifact_digest: str,
    rubric: list[str],
) -> tuple[ReviewLoop, list[ReviewFinding], DiscoveryDerivedOutcome, list[dict[str, Any]]]:
    """Apply whole-plan discovery respond payload with families and audit attestation."""

    _reject_agent_reopen_fields(request)
    explicit_blocked = bool(request.get("block_review"))
    if request.get("decision") is not None:
        raise ValueError(
            "discovery respond must not include decision; use block_review to halt "
            "scope review without reporting findings"
        )
    if explicit_blocked:
        finding_set_id = validate_finding_set_id_echo(loop, request)
        reported = (
            parse_reported_findings(request) if request.get("reported_findings") else []
        )
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
        return updated, merged, "blocked", []

    finding_set_id = validate_finding_set_id_echo(loop, request)
    review_completed = bool(request.get("review_completed"))
    rubric_items = rubric_items_with_ids([str(item) for item in rubric])
    audit_run = _validate_audit_attestation(
        request,
        review_type=review_type,
        artifact_revision=artifact_revision,
        artifact_digest=artifact_digest,
        rubric_items=rubric_items,
        review_completed=review_completed,
    )
    families, sweeps, reported = _parse_whole_plan_families(
        request,
        loop=loop,
        finding_set_id=finding_set_id,
        stage=stage or (loop.active_stage or "initial_review"),
        review_completed=review_completed,
        artifact_revision=artifact_revision,
        artifact_digest=artifact_digest,
    )
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
    incomplete = None
    if outcome == "review_incomplete":
        reason = str(request.get("summary") or "").strip() or (
            "Review could not be completed."
        )
        from top_down_planning.domain.reviews import build_review_incomplete_marker

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
        finding_families=list(loop.finding_families) + families,
        family_sweeps=list(loop.family_sweeps) + sweeps,
        audit_runs=list(loop.audit_runs)
        + ([audit_run] if audit_run is not None else []),
        status=status,
        review_incomplete=incomplete,
    )
    events: list[dict[str, Any]] = []
    if audit_run is not None:
        events.append(
            {
                "type": "review_audit_attestation_recorded",
                "loop_id": loop.id,
                "finding_set_id": finding_set_id,
                "artifact_revision": artifact_revision,
                "pass_count": len(audit_run.passes),
            }
        )
    for family in families:
        events.append(
            {
                "type": "review_finding_family_reported",
                "loop_id": loop.id,
                "finding_set_id": finding_set_id,
                "family_id": family.id,
                "rule_id": family.rule_id,
                "confirmed_instance_count": len(family.confirmed_finding_ids),
                "candidate_count": len(family.candidate_refs),
                "artifact_revision": artifact_revision,
            }
        )
        if family.reopens_family_id:
            events.append(
                {
                    "type": "review_family_regressed",
                    "loop_id": loop.id,
                    "family_id": family.id,
                    "reopens_family_id": family.reopens_family_id,
                }
            )
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
    return updated, merged, outcome, events
