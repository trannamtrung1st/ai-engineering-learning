"""Whole-plan owner family fix recording."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any
from uuid import uuid4

from top_down_planning.domain.artifact_refs import parse_artifact_ref_list
from top_down_planning.domain.finding_families import (
    FamilySweepRecord,
    compute_effective_fix_target_ids,
    compute_family_fix_request_digest,
    family_by_id,
    family_fix_idempotency_key,
    family_required_members,
)
from top_down_planning.domain.reviews import (
    FindingAction,
    ReviewLoop,
    apply_owner_finding_actions,
    effective_owner_actions,
    finding_by_id,
    loop_revise_at,
    parse_finding_action,
)


def _new_sweep_id() -> str:
    return f"sweep-{uuid4().hex[:12]}"


def _lookup_idempotent_sweep(
    loop: ReviewLoop,
    idempotency_key: str,
    request_digest: str,
) -> FamilySweepRecord | None:
    for sweep in loop.family_sweeps:
        if sweep.idempotency_key != idempotency_key:
            continue
        if sweep.request_digest == request_digest:
            return sweep
        raise ValueError(
            "family fix idempotency key replay with conflicting request_digest "
            f"(loop_id={loop.id!r}, stage={loop.active_stage!r}, "
            f"artifact_revision={sweep.artifact_revision})"
        )
    return None


def _owner_action_context(
    loop: ReviewLoop,
    *,
    artifact_revision: int,
) -> str:
    return (
        f"loop_id={loop.id!r}, stage={loop.active_stage!r}, "
        f"artifact_revision={artifact_revision}"
    )


def _effective_actions(
    loop: ReviewLoop,
    proposed_actions: Sequence[FindingAction],
) -> dict[str, FindingAction]:
    finding_set_id = str(loop.finding_set_id or "").strip() or None
    return effective_owner_actions(
        list(loop.finding_actions) + list(proposed_actions),
        finding_set_id=finding_set_id,
    )


def apply_family_fixes(
    loop: ReviewLoop,
    request: Mapping[str, Any],
    *,
    actor_role: str,
    artifact_revision: int,
    artifact_digest: str,
    current_artifact_revision: int | None = None,
) -> tuple[ReviewLoop, list[FindingAction], list[dict[str, Any]]]:
    raw_fixes = request.get("family_fixes") or []
    if not isinstance(raw_fixes, list):
        raise ValueError("family_fixes must be a list")
    raw_actions = request.get("finding_actions") or []
    if not isinstance(raw_actions, list):
        raise ValueError("finding_actions must be a list")

    explicit_actions: list[FindingAction] = []
    for item in raw_actions:
        if not isinstance(item, Mapping):
            raise ValueError("finding_actions entry must be an object")
        payload = dict(item)
        payload.setdefault("actor_role", actor_role)
        payload.setdefault("artifact_revision", artifact_revision)
        finding_set_id = str(loop.finding_set_id or "").strip()
        if finding_set_id and not str(payload.get("finding_set_id") or "").strip():
            payload["finding_set_id"] = finding_set_id
        explicit_actions.append(parse_finding_action(payload))

    generated_actions: list[dict[str, Any]] = []
    new_sweeps: list[FamilySweepRecord] = []
    events: list[dict[str, Any]] = []
    finding_set_id = str(loop.finding_set_id or "").strip()

    effective_union: set[str] = set()
    for raw in raw_fixes:
        if not isinstance(raw, Mapping):
            raise ValueError("each family_fix must be an object")
        family_id = str(raw.get("family_id") or "").strip()
        family = family_by_id(loop, family_id)
        if family is None:
            raise ValueError(f"unknown family_id {family_id!r}")
        target_ids = [
            str(item).strip()
            for item in (raw.get("target_finding_ids") or [])
            if str(item).strip()
        ]
        effective_prior = _effective_actions(loop, explicit_actions)
        required_ids = {
            finding.id for finding in family_required_members(loop, family_id)
        }
        for finding_id in target_ids:
            if finding_id in required_ids:
                continue
            prior = effective_prior.get(finding_id)
            if prior is not None and prior.action in {
                "challenge",
                "defer",
                "accept_as_is",
            }:
                raise ValueError(
                    f"target_finding_ids entry {finding_id!r} conflicts with "
                    f"existing action {prior.action!r}"
                )
        family_challenged = {
            action.finding_id
            for action in explicit_actions
            if action.action == "challenge"
            and finding_by_id(loop.findings, action.finding_id) is not None
            and finding_by_id(loop.findings, action.finding_id).family_id == family_id  # type: ignore[union-attr]
        }
        effective_ids = compute_effective_fix_target_ids(
            loop,
            family_id,
            target_finding_ids=target_ids,
            challenged_required_ids=family_challenged,
        )
        overlap = set(effective_ids) & {
            action.finding_id for action in explicit_actions
        }
        if overlap:
            raise ValueError(
                "family_fixes overlap finding_actions on findings "
                f"{sorted(overlap)} "
                f"({_owner_action_context(loop, artifact_revision=artifact_revision)})"
            )
        effective_union.update(effective_ids)
        owner_sweep_raw = raw.get("owner_sweep")
        if not isinstance(owner_sweep_raw, Mapping):
            raise ValueError("family_fix requires owner_sweep")
        if bool(owner_sweep_raw.get("completed")) and parse_artifact_ref_list(
            owner_sweep_raw.get("remaining_instance_refs")
        ):
            raise ValueError(
                "owner_sweep completed=true requires empty remaining_instance_refs"
            )
        if bool(owner_sweep_raw.get("completed")):
            searched_refs = [
                str(item).strip()
                for item in (owner_sweep_raw.get("searched_refs") or [])
                if str(item).strip()
            ]
            search_dimensions = [
                str(item).strip()
                for item in (owner_sweep_raw.get("search_dimensions") or [])
                if str(item).strip()
            ]
            summary = str(owner_sweep_raw.get("summary") or "").strip()
            if not searched_refs:
                raise ValueError(
                    f"family {family_id!r} completed owner_sweep requires searched_refs "
                    f"({_owner_action_context(loop, artifact_revision=artifact_revision)})"
                )
            if not search_dimensions:
                raise ValueError(
                    f"family {family_id!r} completed owner_sweep requires "
                    f"search_dimensions "
                    f"({_owner_action_context(loop, artifact_revision=artifact_revision)})"
                )
            if not summary:
                raise ValueError(
                    f"family {family_id!r} completed owner_sweep requires summary "
                    f"({_owner_action_context(loop, artifact_revision=artifact_revision)})"
                )
        idempotency_key = family_fix_idempotency_key(
            family_id=family_id,
            finding_set_id=finding_set_id,
            artifact_revision=artifact_revision,
            artifact_digest=artifact_digest,
            actor_role=actor_role,
        )
        request_digest = compute_family_fix_request_digest(
            effective_fix_target_ids=effective_ids,
            rationale=str(raw.get("rationale") or ""),
            changed_refs=[
                str(item).strip()
                for item in (raw.get("changed_refs") or [])
                if str(item).strip()
            ],
            owner_sweep=dict(owner_sweep_raw),
        )
        existing = _lookup_idempotent_sweep(loop, idempotency_key, request_digest)
        if existing is not None:
            events.append(
                {
                    "type": "review_family_owner_sweep_replayed",
                    "loop_id": loop.id,
                    "family_id": family_id,
                    "finding_set_id": finding_set_id,
                    "artifact_revision": existing.artifact_revision,
                }
            )
            continue
        if (
            current_artifact_revision is not None
            and artifact_revision != current_artifact_revision
        ):
            raise ValueError(
                f"artifact_revision {artifact_revision} does not match current "
                f"revision {current_artifact_revision}"
            )
        if int(owner_sweep_raw.get("artifact_revision") or 0) != artifact_revision:
            raise ValueError("owner_sweep artifact_revision mismatch")
        if str(owner_sweep_raw.get("artifact_digest") or "").strip() != artifact_digest:
            raise ValueError("owner_sweep artifact_digest mismatch")
        new_sweeps.append(
            FamilySweepRecord(
                id=_new_sweep_id(),
                family_id=family_id,
                actor_role=actor_role,  # type: ignore[arg-type]
                stage="owner_fix",
                artifact_revision=artifact_revision,
                artifact_digest=artifact_digest,
                finding_set_id=finding_set_id,
                searched_refs=[
                    str(item).strip()
                    for item in (owner_sweep_raw.get("searched_refs") or [])
                    if str(item).strip()
                ],
                search_dimensions=[
                    str(item).strip()
                    for item in (owner_sweep_raw.get("search_dimensions") or [])
                    if str(item).strip()
                ],
                additional_fixed_refs=parse_artifact_ref_list(
                    owner_sweep_raw.get("additional_fixed_refs")
                ),
                remaining_instance_refs=parse_artifact_ref_list(
                    owner_sweep_raw.get("remaining_instance_refs")
                ),
                completed=bool(owner_sweep_raw.get("completed")),
                summary=str(owner_sweep_raw.get("summary") or ""),
                evidence=[
                    str(item)
                    for item in (owner_sweep_raw.get("evidence") or [])
                    if str(item).strip()
                ],
                idempotency_key=idempotency_key,
                request_digest=request_digest,
            )
        )
        for finding_id in effective_ids:
            generated_actions.append(
                {
                    "finding_id": finding_id,
                    "action": "fix",
                    "actor_role": actor_role,
                    "artifact_revision": artifact_revision,
                    "finding_set_id": finding_set_id,
                    "rationale": str(raw.get("rationale") or ""),
                }
            )
        events.append(
            {
                "type": "review_family_owner_sweep_recorded",
                "loop_id": loop.id,
                "family_id": family_id,
                "finding_set_id": finding_set_id,
                "artifact_revision": artifact_revision,
            }
        )

    if not new_sweeps and not generated_actions:
        if explicit_actions:
            updated, parsed = apply_owner_finding_actions(
                loop,
                [action.to_dict() for action in explicit_actions],
                actor_role=actor_role,
                artifact_revision=artifact_revision,
            )
            return updated, parsed, events
        return loop, [], events

    merged_raw_actions = list(generated_actions) + [
        action.to_dict() for action in explicit_actions
    ]
    updated, parsed = apply_owner_finding_actions(
        loop,
        merged_raw_actions,
        actor_role=actor_role,
        artifact_revision=artifact_revision,
    )
    updated = replace(
        updated,
        family_sweeps=list(updated.family_sweeps) + new_sweeps,
    )
    return updated, parsed, events
