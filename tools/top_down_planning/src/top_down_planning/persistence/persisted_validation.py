"""Strict validation for persisted current-schema records at the store boundary."""

from __future__ import annotations

import re
from typing import Any

from core_tools.persistence import PersistenceError, parse_revision_value

from top_down_planning.config.binding_validation import validate_context_snapshot_binding
from top_down_planning.domain.dispositions import TERMINAL_DISPOSITIONS
from top_down_planning.domain.models import Plan
from top_down_planning.domain.production import (
    BatchResult,
    Contribution,
    ItemDispositionRecord,
    OutputEvidence,
    ProductionBatch,
    SUB_TDP_INTEGRATION_BATCH_INTENT,
    all_applicable_items_processed,
    derive_live_disposition_map,
    is_live_completed_batch,
)
from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.domain.run_lifecycle import (
    RunLifecycleError,
    validate_run_lifecycle_invariants,
)
from top_down_planning.domain.session_bindings import (
    PRIMARY_PLANNER_SLOT,
    PRIMARY_PRODUCER_SLOT,
    SessionBinding,
    SessionBindingError,
    validate_session_binding,
)
from top_down_planning.persistence.run_schema import (
    validate_run_digests,
    validate_run_schema_version,
)
from top_down_planning.package.lineage import verify_accepted_result_attestation
from top_down_planning.persistence.sub_tdp_state import (
    ORCHESTRATION_STATUS_COMPLETED,
    ORCHESTRATION_STATUS_FAILED,
    ORCHESTRATION_STATUS_PREPARING,
    ORCHESTRATION_STATUS_RUNNING,
    UNIT_STATUS_COMPLETED,
    UNIT_STATUS_FAILED,
    UNIT_STATUS_PAUSED,
    UNIT_STATUS_PENDING,
    UNIT_STATUS_RUNNING,
)
from top_down_planning.domain.session_recovery_state import validate_session_recovery_fields

_PROTECTED_RUN_RECORD_KEYS = frozenset(
    {
        "id",
        "schema_version",
        "revision",
        "status",
        "phase",
        "outcome",
        "stop",
        "phase_action_id",
        "session_replacement_phase_action_id",
        "phase_action_domain_committed_id",
        "digests",
        "context_snapshot_binding",
        "sessions",
        "planning",
        "production_loop",
        "created_at",
        "updated_at",
        "workspace",
    }
)

_REQUIRED_V3_DIGEST_KEYS = frozenset(
    {
        "input",
        "output_goal",
        "config_contract",
        "config_execution",
        "plan",
        "context_spec",
        "context_snapshot",
    }
)

_SLOT_ROLE_KIND: dict[str, tuple[str, str]] = {
    PRIMARY_PLANNER_SLOT: ("planner", "primary"),
    PRIMARY_PRODUCER_SLOT: ("producer", "primary"),
}

_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_VALID_BATCH_STATUSES = frozenset({"started", "completed", "failed", "aborted"})
_COMPLETED_BATCH_STATUS = "completed"
_OUTPUT_MIRROR_FIELDS = (
    "id",
    "type",
    "ref",
    "sha256",
    "size",
    "media_type",
    "captured_at",
    "snapshot_ref",
)
_ACCEPTED_RESULT_DIGEST_FIELDS = (
    "package_digest",
    "unit_plan_digest",
    "assigned_subtree_digest",
    "output_digest",
    "whole_output_review_digest",
    "evidence_digest",
    "baseline_context_snapshot_digest",
    "final_context_snapshot_digest",
)
_VALID_AMENDMENT_STATUSES = frozenset({"pending", "completed"})
_VALID_BATCH_EVIDENCE_STATUSES = frozenset({"invalidated_by_reconciliation"})
_SUPPORTED_SUB_TDP_VERSIONS = frozenset({1, 2})
_VALID_ORCHESTRATION_STATUSES = frozenset(
    {
        ORCHESTRATION_STATUS_PREPARING,
        ORCHESTRATION_STATUS_RUNNING,
        ORCHESTRATION_STATUS_COMPLETED,
        ORCHESTRATION_STATUS_FAILED,
    }
)
_VALID_UNIT_STATUSES = frozenset(
    {
        UNIT_STATUS_PENDING,
        UNIT_STATUS_RUNNING,
        UNIT_STATUS_PAUSED,
        UNIT_STATUS_COMPLETED,
        UNIT_STATUS_FAILED,
    }
)


def _require_strict_non_empty_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _require_strict_non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be a non-negative integer")
    if value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _require_strict_sha256_digest(value: Any, field_name: str) -> str:
    digest = _require_strict_non_empty_str(value, field_name)
    if not _SHA256_PATTERN.fullmatch(digest):
        raise ValueError(f"{field_name} must be a 64-character lowercase hex digest")
    return digest


def _require_optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string or null")
    text = value.strip()
    return text or None


def _require_persisted_sha256_digest(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise PersistenceError(f"{field_name} must be a string")
    if not value.strip():
        raise PersistenceError(f"{field_name} is required on schema v3 run records")
    if not _SHA256_PATTERN.fullmatch(value):
        raise PersistenceError(f"{field_name} must be a 64-character lowercase hex digest")
    return value


def _parse_persisted_disposition_record(value: dict[str, Any]) -> ItemDispositionRecord:
    disposition = value.get("disposition")
    if not isinstance(disposition, str) or disposition not in TERMINAL_DISPOSITIONS:
        raise ValueError(
            f"disposition must be one of: {', '.join(sorted(TERMINAL_DISPOSITIONS))}"
        )
    return ItemDispositionRecord(
        disposition=disposition,  # type: ignore[arg-type]
        reason=_require_optional_string(value.get("reason"), "reason"),
        replacement_ref=_require_optional_string(
            value.get("replacement_ref"),
            "replacement_ref",
        ),
        evidence=_require_optional_string(value.get("evidence"), "evidence"),
    )


def _require_strict_string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    return [
        _require_strict_non_empty_str(entry, f"{field_name}[{index}]")
        for index, entry in enumerate(value)
    ]


def _validate_persisted_flat_disposition_value(
    item_id: str,
    value: Any,
) -> None:
    if not isinstance(value, str):
        raise PersistenceError(
            f"production.dispositions[{item_id!r}] must be a terminal disposition string"
        )
    if not value.strip():
        raise PersistenceError(
            f"production.dispositions[{item_id!r}] must be a non-empty string"
        )
    if value not in TERMINAL_DISPOSITIONS:
        raise PersistenceError(
            f"production.dispositions[{item_id!r}] must be a terminal disposition"
        )


def _parse_persisted_completion_claim(value: dict[str, Any]) -> None:
    if not value:
        raise ValueError("completion_claim must not be empty")

    status = value.get("status")
    if status is not None and not isinstance(status, str):
        raise ValueError("status must be a string")
    goal_assessment = value.get("goal_assessment")
    if goal_assessment is not None and not isinstance(goal_assessment, str):
        raise ValueError("goal_assessment must be a string")
    summary = value.get("summary")
    if summary is not None and not isinstance(summary, str):
        raise ValueError("summary must be a string")

    goal_met = value.get("goal_met")
    if not isinstance(goal_met, bool):
        raise ValueError("goal_met must be a boolean")

    if goal_met is True:
        if status is not None:
            raise ValueError("status is not allowed when goal_met is true")
        if not isinstance(goal_assessment, str) or not goal_assessment.strip():
            raise ValueError("goal_assessment must be a non-empty string")
        _require_strict_non_negative_int(value.get("plan_revision"), "plan_revision")
        _require_strict_non_negative_int(value.get("output_revision"), "output_revision")
        if value.get("all_applicable_items_processed") is not True:
            raise ValueError("all_applicable_items_processed must be true")
        return

    if status != "integration_pending":
        raise ValueError("status must be integration_pending when goal_met is false")
    for forbidden in ("plan_revision", "output_revision", "all_applicable_items_processed"):
        if forbidden in value:
            raise ValueError(f"{forbidden} is not allowed when goal_met is false")
    if not isinstance(goal_assessment, str) or not goal_assessment.strip():
        raise ValueError("goal_assessment must be a non-empty string")
    submitted_at = value.get("submitted_at")
    if submitted_at is not None and not isinstance(submitted_at, str):
        raise ValueError("submitted_at must be a string")


def _validate_completion_claim_bindings(
    payload: dict[str, Any],
    plan: dict[str, Any] | None,
) -> None:
    claim = payload.get("completion_claim")
    if not isinstance(claim, dict):
        return
    if claim.get("goal_met") is not True:
        return
    claim_output_revision = _require_strict_non_negative_int(
        claim.get("output_revision"),
        "completion_claim.output_revision",
    )
    production_output_revision = _require_strict_non_negative_int(
        payload.get("output_revision"),
        "production.output_revision",
    )
    if claim_output_revision != production_output_revision:
        raise ValueError(
            "completion_claim.output_revision must match production.output_revision"
        )
    if plan is None:
        raise ValueError("completion_claim requires current plan revision binding")
    plan_revision = _require_strict_non_negative_int(plan.get("revision"), "plan.revision")
    claim_plan_revision = _require_strict_non_negative_int(
        claim.get("plan_revision"),
        "completion_claim.plan_revision",
    )
    if claim_plan_revision != plan_revision:
        raise ValueError("completion_claim.plan_revision must match plan.revision")
    dispositions = payload.get("dispositions") or {}
    if not isinstance(dispositions, dict):
        raise ValueError("production.dispositions must be an object")
    plan_model = Plan.from_dict(dict(plan))
    if not all_applicable_items_processed(plan_model, dispositions):
        raise ValueError(
            "completion_claim.all_applicable_items_processed is false for current plan"
        )


def _validate_accepted_result_schema(accepted: dict[str, Any], *, label: str) -> None:
    schema_version = accepted.get("schema_version")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise ValueError(f"{label}.accepted_result.schema_version must be an integer")
    if schema_version != 1:
        raise ValueError(f"{label}.accepted_result.schema_version must be 1")
    _require_strict_non_empty_str(
        accepted.get("package_id"),
        f"{label}.accepted_result.package_id",
    )
    _require_strict_sha256_digest(
        accepted.get("package_digest"),
        f"{label}.accepted_result.package_digest",
    )
    _require_strict_non_empty_str(
        accepted.get("unit_id"),
        f"{label}.accepted_result.unit_id",
    )
    _require_strict_sha256_digest(
        accepted.get("unit_plan_digest"),
        f"{label}.accepted_result.unit_plan_digest",
    )
    _require_strict_sha256_digest(
        accepted.get("assigned_subtree_digest"),
        f"{label}.accepted_result.assigned_subtree_digest",
    )
    _require_strict_non_empty_str(
        accepted.get("child_run_id"),
        f"{label}.accepted_result.child_run_id",
    )
    _require_strict_non_empty_str(
        accepted.get("whole_output_review_id"),
        f"{label}.accepted_result.whole_output_review_id",
    )
    _require_strict_sha256_digest(
        accepted.get("whole_output_review_digest"),
        f"{label}.accepted_result.whole_output_review_digest",
    )
    _require_strict_non_negative_int(
        accepted.get("output_revision"),
        f"{label}.accepted_result.output_revision",
    )
    assessment = accepted.get("completion_assessment")
    if not isinstance(assessment, str) or not assessment.strip():
        raise ValueError(
            f"{label}.accepted_result.completion_assessment must be a non-empty string"
        )
    output_refs = accepted.get("output_refs")
    if not isinstance(output_refs, list):
        raise ValueError(f"{label}.accepted_result.output_refs must be a list")
    output_ids: set[str] = set()
    for index, output in enumerate(output_refs):
        if not isinstance(output, dict):
            raise ValueError(
                f"{label}.accepted_result.output_refs[{index}] must be an object"
            )
        output_id = _require_strict_non_empty_str(
            output.get("id"),
            f"{label}.accepted_result.output_refs[{index}].id",
        )
        if output_id in output_ids:
            raise ValueError(
                f"{label}.accepted_result.output_refs contains duplicate id {output_id!r}"
            )
        output_ids.add(output_id)
        _require_strict_non_empty_str(
            output.get("type"),
            f"{label}.accepted_result.output_refs[{index}].type",
        )
        _require_strict_non_empty_str(
            output.get("ref"),
            f"{label}.accepted_result.output_refs[{index}].ref",
        )
        _require_strict_sha256_digest(
            output.get("sha256"),
            f"{label}.accepted_result.output_refs[{index}].sha256",
        )
        _require_strict_non_negative_int(
            output.get("size"),
            f"{label}.accepted_result.output_refs[{index}].size",
        )
        _require_strict_non_empty_str(
            output.get("media_type"),
            f"{label}.accepted_result.output_refs[{index}].media_type",
        )
        _require_strict_non_empty_str(
            output.get("captured_at"),
            f"{label}.accepted_result.output_refs[{index}].captured_at",
        )
        _require_strict_non_empty_str(
            output.get("snapshot_ref"),
            f"{label}.accepted_result.output_refs[{index}].snapshot_ref",
        )
    contributions = accepted.get("contributions")
    if not isinstance(contributions, list):
        raise ValueError(f"{label}.accepted_result.contributions must be a list")
    for index, contribution in enumerate(contributions):
        if not isinstance(contribution, dict):
            raise ValueError(
                f"{label}.accepted_result.contributions[{index}] must be an object"
            )
        _require_strict_non_empty_str(
            contribution.get("item_id"),
            f"{label}.accepted_result.contributions[{index}].item_id",
        )
        summary = contribution.get("summary")
        if summary is not None and not isinstance(summary, str):
            raise ValueError(
                f"{label}.accepted_result.contributions[{index}].summary must be a string"
            )
        output_refs_raw = contribution.get("output_refs")
        if output_refs_raw is None:
            output_refs_raw = []
        if not isinstance(output_refs_raw, list):
            raise ValueError(
                f"{label}.accepted_result.contributions[{index}].output_refs must be a list"
            )
        for ref_index, ref in enumerate(output_refs_raw):
            ref_id = _require_strict_non_empty_str(
                ref,
                f"{label}.accepted_result.contributions[{index}].output_refs[{ref_index}]",
            )
            if ref_id not in output_ids:
                raise ValueError(
                    f"{label}.accepted_result.contributions[{index}].output_refs[{ref_index}] "
                    f"references unknown output id {ref_id!r}"
                )
    output_paths: set[str] = set()
    for index, output in enumerate(output_refs):
        if not isinstance(output, dict):
            continue
        ref_path = str(output.get("ref") or "").strip()
        if ref_path:
            output_paths.add(ref_path)
    workspace_changes = accepted.get("workspace_changes")
    if not isinstance(workspace_changes, dict):
        raise ValueError(f"{label}.accepted_result.workspace_changes must be an object")
    for path, change in workspace_changes.items():
        if not isinstance(change, dict):
            raise ValueError(
                f"{label}.accepted_result.workspace_changes[{path!r}] must be an object"
            )
        operation = str(change.get("operation") or "").strip()
        if operation == "delete":
            raise ValueError(
                f"{label}.accepted_result.workspace_changes delete operation is not supported "
                "until production can capture delete tombstones"
            )
        if operation != "write":
            raise ValueError(
                f"{label}.accepted_result.workspace_changes[{path!r}] has invalid operation"
            )
        _require_strict_sha256_digest(
            change.get("sha256"),
            f"{label}.accepted_result.workspace_changes[{path!r}].sha256",
        )
    extra_paths = set(workspace_changes.keys()) - output_paths
    if extra_paths:
        extra = sorted(extra_paths)[0]
        raise ValueError(
            f"{label}.accepted_result.workspace_changes[{extra!r}] "
            "is not authorized by accepted output_refs"
        )
    for path in sorted(output_paths):
        if path not in workspace_changes:
            raise ValueError(
                f"{label}.accepted_result output_refs path {path!r} "
                "missing from workspace_changes"
            )


def _parse_persisted_amendment_request(value: dict[str, Any]) -> None:
    _require_strict_non_empty_str(value.get("id"), "id")
    status = _require_strict_non_empty_str(value.get("status"), "status")
    if status not in _VALID_AMENDMENT_STATUSES:
        raise ValueError(
            f"status must be one of: {', '.join(sorted(_VALID_AMENDMENT_STATUSES))}"
        )
    _require_strict_non_empty_str(value.get("evidence"), "evidence")
    _require_strict_string_list(value.get("affected_refs"), "affected_refs")
    summary = value.get("summary")
    if summary is not None and not isinstance(summary, str):
        raise ValueError("summary must be a string")
    if "plan_revision" in value:
        _require_strict_non_negative_int(value.get("plan_revision"), "plan_revision")
    if "output_revision" in value:
        _require_strict_non_negative_int(value.get("output_revision"), "output_revision")


def _parse_persisted_reconciliation_report(value: dict[str, Any]) -> None:
    _require_strict_non_empty_str(value.get("amendment_id"), "amendment_id")
    prior_plan_revision = _require_strict_non_negative_int(
        value.get("prior_plan_revision"),
        "prior_plan_revision",
    )
    new_plan_revision = _require_strict_non_negative_int(
        value.get("new_plan_revision"),
        "new_plan_revision",
    )
    if new_plan_revision < prior_plan_revision:
        raise ValueError("new_plan_revision must be >= prior_plan_revision")
    _require_strict_string_list(value.get("unchanged"), "unchanged")
    changed = _require_strict_string_list(value.get("changed"), "changed")
    removed = _require_strict_string_list(value.get("removed"), "removed")
    _require_strict_string_list(value.get("newly_added"), "newly_added")
    _require_strict_string_list(value.get("evidence_preserved"), "evidence_preserved")
    expected_invalidated = sorted(set(changed) | set(removed))
    invalidated_item_ids = value.get("invalidated_item_ids")
    if invalidated_item_ids is not None:
        actual_invalidated = _require_strict_string_list(
            invalidated_item_ids,
            "invalidated_item_ids",
        )
        if sorted(actual_invalidated) != expected_invalidated:
            raise ValueError("invalidated_item_ids must match changed and removed items")
    elif expected_invalidated:
        raise ValueError("invalidated_item_ids is required when changed or removed items exist")


def _validate_persisted_amendment_state(payload: dict[str, Any]) -> None:
    pending_id = payload.get("pending_amendment_id")
    if pending_id is not None and (
        not isinstance(pending_id, str) or not pending_id.strip()
    ):
        raise PersistenceError(
            "production.pending_amendment_id must be null or a non-empty string"
        )

    requests = payload.get("amendment_requests") or []
    if not isinstance(requests, list):
        raise PersistenceError("production.amendment_requests must be a list")

    seen_ids: set[str] = set()
    pending_ids: list[str] = []
    for index, request in enumerate(requests):
        if not isinstance(request, dict):
            raise PersistenceError(f"production.amendment_requests[{index}] must be an object")
        request_id = str(request.get("id") or "")
        if request_id in seen_ids:
            raise PersistenceError(
                f"production.amendment_requests contains duplicate id {request_id!r}"
            )
        seen_ids.add(request_id)
        status = str(request.get("status") or "")
        if status == "pending":
            pending_ids.append(request_id)

    if len(pending_ids) > 1:
        raise PersistenceError("production.amendment_requests cannot contain multiple pending requests")

    if pending_id:
        if pending_id not in seen_ids:
            raise PersistenceError(
                "production.pending_amendment_id does not reference an amendment request"
            )
        pending_request = next(
            request
            for request in requests
            if isinstance(request, dict) and str(request.get("id") or "") == pending_id
        )
        if str(pending_request.get("status") or "") != "pending":
            raise PersistenceError(
                "production.pending_amendment_id must reference a pending amendment request"
            )
    elif pending_ids:
        raise PersistenceError(
            "production.pending_amendment_id is required when an amendment request is pending"
        )


def _parse_persisted_blocker_report(value: dict[str, Any]) -> None:
    _require_strict_non_empty_str(value.get("evidence"), "evidence")
    affected_refs = value.get("affected_refs")
    if affected_refs is None:
        affected_refs = []
    if not isinstance(affected_refs, list):
        raise ValueError("affected_refs must be a list")
    for index, ref in enumerate(affected_refs):
        _require_strict_non_empty_str(ref, f"affected_refs[{index}]")
    summary = value.get("summary")
    if summary is not None and not isinstance(summary, str):
        raise ValueError("summary must be a string")
    if "plan_revision" in value:
        _require_strict_non_negative_int(value.get("plan_revision"), "plan_revision")
    if "output_revision" in value:
        _require_strict_non_negative_int(value.get("output_revision"), "output_revision")


def _normalized_output_mirror(entry: dict[str, Any]) -> dict[str, Any]:
    size = entry.get("size")
    normalized_size = size
    if isinstance(size, bool) or not isinstance(size, int):
        normalized_size = size
    return {
        "id": str(entry.get("id") or ""),
        "type": str(entry.get("type", "artifact") or "artifact"),
        "ref": str(entry.get("ref") or ""),
        "sha256": str(entry.get("sha256") or ""),
        "size": normalized_size,
        "media_type": str(entry.get("media_type") or ""),
        "captured_at": str(entry.get("captured_at") or ""),
        "snapshot_ref": entry.get("snapshot_ref"),
    }


def _output_mirrors_match(nested: dict[str, Any], top_level: dict[str, Any]) -> bool:
    return _normalized_output_mirror(nested) == _normalized_output_mirror(top_level)


def _require_accepted_result_digest_field(
    value: Any,
    *,
    field_name: str,
    label: str,
) -> str:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise ValueError(
            f"{label}.accepted_result.{field_name} must be a 64-character lowercase hex digest"
        )
    return value


def _verify_persisted_completed_unit_identity(
    unit: dict[str, Any],
    *,
    label: str,
    package_id: str,
    package_digest: str,
) -> None:
    accepted = unit.get("accepted_result")
    if not isinstance(accepted, dict):
        raise ValueError(f"{label}.accepted_result attestation is missing")
    for field_name in _ACCEPTED_RESULT_DIGEST_FIELDS:
        _require_accepted_result_digest_field(
            accepted.get(field_name),
            field_name=field_name,
            label=label,
        )
    baseline_digests = accepted.get("baseline_accepted_result_digests")
    if not isinstance(baseline_digests, list):
        raise ValueError(f"{label}.accepted_result.baseline_accepted_result_digests must be a list")
    for index, digest in enumerate(baseline_digests):
        if not isinstance(digest, str) or not _SHA256_PATTERN.fullmatch(digest):
            raise ValueError(
                f"{label}.accepted_result.baseline_accepted_result_digests[{index}] "
                "must be a 64-character lowercase hex digest"
            )
    workspace_changes = accepted.get("workspace_changes")
    if not isinstance(workspace_changes, dict):
        raise ValueError(f"{label}.accepted_result.workspace_changes must be an object")
    for path, change in workspace_changes.items():
        if not isinstance(change, dict):
            raise ValueError(
                f"{label}.accepted_result.workspace_changes[{path!r}] must be an object"
            )
        _require_accepted_result_digest_field(
            change.get("sha256"),
            field_name=f"workspace_changes[{path!r}].sha256",
            label=label,
        )
    if str(accepted.get("package_id") or "") != package_id:
        raise ValueError(f"{label}.accepted_result.package_id does not match sub_tdps.package_id")
    if str(accepted.get("package_digest") or "") != package_digest:
        raise ValueError(
            f"{label}.accepted_result.package_digest does not match sub_tdps.package_digest"
        )
    unit_subtree = str(unit.get("assigned_subtree_digest") or "")
    if str(accepted.get("assigned_subtree_digest") or "") != unit_subtree:
        raise ValueError(
            f"{label}.accepted_result.assigned_subtree_digest does not match unit record"
        )


def _parse_persisted_sub_tdp_unit(
    value: dict[str, Any],
    *,
    label: str,
    version: int,
    package_id: str | None = None,
    package_digest: str | None = None,
) -> None:
    unit_id = _require_strict_non_empty_str(value.get("id"), f"{label}.id")
    plan_item_id = _require_strict_non_empty_str(
        value.get("plan_item_id"),
        f"{label}.plan_item_id",
    )
    status = value.get("status")
    if status is None:
        status = UNIT_STATUS_PENDING
    if not isinstance(status, str) or status not in _VALID_UNIT_STATUSES:
        raise ValueError(f"{label}.status must be a valid unit status")
    title = value.get("title")
    if title is not None and not isinstance(title, str):
        raise ValueError(f"{label}.title must be a string")
    directory = value.get("directory")
    if directory is not None and not isinstance(directory, str):
        raise ValueError(f"{label}.directory must be a string")
    ordinal = value.get("ordinal")
    if ordinal is not None:
        _require_strict_non_negative_int(ordinal, f"{label}.ordinal")
    child_run_id = value.get("child_run_id")
    if child_run_id is not None and not isinstance(child_run_id, str):
        raise ValueError(f"{label}.child_run_id must be a string or null")
    notes = value.get("notes")
    if notes is None:
        notes = []
    if not isinstance(notes, list):
        raise ValueError(f"{label}.notes must be a list")
    for index, note in enumerate(notes):
        if not isinstance(note, str):
            raise ValueError(f"{label}.notes[{index}] must be a string")
    unit_plan_digest = value.get("unit_plan_digest")
    if version == 2:
        if not isinstance(unit_plan_digest, str) or not _SHA256_PATTERN.fullmatch(
            unit_plan_digest
        ):
            raise ValueError(
                f"{label}.unit_plan_digest must be a 64-character lowercase hex digest"
            )
    elif unit_plan_digest is not None:
        if not isinstance(unit_plan_digest, str) or not _SHA256_PATTERN.fullmatch(
            unit_plan_digest
        ):
            raise ValueError(f"{label}.unit_plan_digest must be a 64-character lowercase hex digest")
    assigned_subtree_digest = value.get("assigned_subtree_digest")
    if version == 2:
        if not isinstance(assigned_subtree_digest, str) or not _SHA256_PATTERN.fullmatch(
            assigned_subtree_digest
        ):
            raise ValueError(
                f"{label}.assigned_subtree_digest must be a 64-character lowercase hex digest"
            )
    elif assigned_subtree_digest is not None:
        if not isinstance(assigned_subtree_digest, str) or not _SHA256_PATTERN.fullmatch(
            assigned_subtree_digest
        ):
            raise ValueError(
                f"{label}.assigned_subtree_digest must be a 64-character lowercase hex digest"
            )
    depends_on = value.get("depends_on")
    if version == 2:
        if depends_on is None:
            raise ValueError(f"{label}.depends_on is required for sub_tdps version 2")
        _require_strict_string_list(depends_on, f"{label}.depends_on")
    elif depends_on is not None:
        _require_strict_string_list(depends_on, f"{label}.depends_on")
    if unit_id != plan_item_id:
        raise ValueError(f"{label}.id must match plan_item_id")
    if status == UNIT_STATUS_COMPLETED:
        digest = value.get("accepted_result_digest")
        if not isinstance(digest, str) or not _SHA256_PATTERN.fullmatch(digest):
            raise ValueError(
                f"{label}.accepted_result_digest must be a 64-character lowercase hex digest"
            )
        accepted = value.get("accepted_result")
        if isinstance(accepted, dict):
            _validate_accepted_result_schema(accepted, label=label)
        try:
            verify_accepted_result_attestation(value)
        except ValueError as exc:
            raise ValueError(f"{label} completed unit attestation is invalid: {exc}") from exc
        if version == 2:
            if not package_id or not package_digest:
                raise ValueError("sub_tdps package identity is required for version 2")
            _verify_persisted_completed_unit_identity(
                value,
                label=label,
                package_id=package_id,
                package_digest=package_digest,
            )


def _parse_persisted_sub_tdps(value: dict[str, Any]) -> None:
    version = value.get("version")
    if version is None:
        raise ValueError("sub_tdps.version is required")
    version = _require_strict_non_negative_int(version, "sub_tdps.version")
    if version not in _SUPPORTED_SUB_TDP_VERSIONS:
        raise ValueError("sub_tdps.version is not supported")
    status = value.get("status")
    if not isinstance(status, str) or status not in _VALID_ORCHESTRATION_STATUSES:
        raise ValueError("sub_tdps.status must be a valid orchestration status")
    active_unit_id = value.get("active_unit_id")
    if active_unit_id is not None and not isinstance(active_unit_id, str):
        raise ValueError("sub_tdps.active_unit_id must be a string or null")
    package_id = value.get("package_id")
    package_digest: str | None = None
    if version == 2:
        package_id = _require_strict_non_empty_str(package_id, "sub_tdps.package_id")
        package_digest = value.get("package_digest")
        if not isinstance(package_digest, str) or not _SHA256_PATTERN.fullmatch(package_digest):
            raise ValueError(
                "sub_tdps.package_digest must be a 64-character lowercase hex digest"
            )
        _require_strict_non_empty_str(value.get("manifest_path"), "sub_tdps.manifest_path")
    elif package_id is not None and not isinstance(package_id, str):
        raise ValueError("sub_tdps.package_id must be a string")
    if version != 2:
        package_digest_value = value.get("package_digest")
        if package_digest_value is not None:
            if not isinstance(package_digest_value, str) or not _SHA256_PATTERN.fullmatch(
                package_digest_value
            ):
                raise ValueError(
                    "sub_tdps.package_digest must be a 64-character lowercase hex digest"
                )
    manifest_path = value.get("manifest_path")
    if manifest_path is not None and not isinstance(manifest_path, str):
        raise ValueError("sub_tdps.manifest_path must be a string")
    units = value.get("units")
    if units is None:
        units = []
    if not isinstance(units, list):
        raise ValueError("sub_tdps.units must be a list")
    unit_ids: set[str] = set()
    plan_item_ids: set[str] = set()
    for index, unit in enumerate(units):
        if not isinstance(unit, dict):
            raise ValueError(f"sub_tdps.units[{index}] must be an object")
        label = f"sub_tdps.units[{index}]"
        _parse_persisted_sub_tdp_unit(
            unit,
            label=label,
            version=version,
            package_id=package_id if version == 2 else None,
            package_digest=package_digest if version == 2 else None,
        )
        unit_id = str(unit.get("id") or "")
        plan_item_id = str(unit.get("plan_item_id") or "")
        if unit_id in unit_ids:
            raise ValueError(f"{label}.id must be unique")
        if plan_item_id in plan_item_ids:
            raise ValueError(f"{label}.plan_item_id must be unique")
        unit_ids.add(unit_id)
        plan_item_ids.add(plan_item_id)
    if active_unit_id is not None and active_unit_id not in unit_ids:
        raise ValueError("sub_tdps.active_unit_id must reference a persisted unit id")
    if status in (ORCHESTRATION_STATUS_COMPLETED, ORCHESTRATION_STATUS_FAILED):
        if active_unit_id:
            raise ValueError(
                "sub_tdps.active_unit_id must be null when orchestration is terminal"
            )
    if active_unit_id:
        active_unit = next(
            unit
            for unit in units
            if isinstance(unit, dict) and str(unit.get("id") or "") == active_unit_id
        )
        active_status = str(active_unit.get("status") or UNIT_STATUS_PENDING)
        if active_status in (UNIT_STATUS_COMPLETED, UNIT_STATUS_FAILED):
            raise ValueError(
                "sub_tdps.active_unit_id must not reference a completed or failed unit"
            )
    if status == ORCHESTRATION_STATUS_COMPLETED:
        for index, unit in enumerate(units):
            if not isinstance(unit, dict):
                continue
            unit_status = str(unit.get("status") or UNIT_STATUS_PENDING)
            if unit_status != UNIT_STATUS_COMPLETED:
                raise ValueError(
                    f"sub_tdps.status completed requires units[{index}] completed"
                )
    if status == ORCHESTRATION_STATUS_FAILED:
        if not any(
            isinstance(unit, dict)
            and str(unit.get("status") or UNIT_STATUS_PENDING) == UNIT_STATUS_FAILED
            for unit in units
        ):
            raise ValueError(
                "sub_tdps.status failed requires at least one unit with status failed"
            )


def _validate_batch_disposition_scope(
    batch: dict[str, Any],
    *,
    batch_id: str,
    plan_items: set[str],
    result: dict[str, Any],
) -> None:
    disposition_records = result.get("dispositions") or {}
    if not isinstance(disposition_records, dict):
        raise ValueError(f"batch {batch_id!r} result.dispositions must be an object")
    disposition_keys = {
        str(item_id)
        for item_id, record in disposition_records.items()
        if isinstance(record, dict) and str(record.get("disposition") or "").strip()
    }
    intent = str(batch.get("intent") or "")
    if not plan_items:
        raise ValueError(f"completed batch {batch_id!r} requires non-empty plan_items")
    if disposition_keys != plan_items:
        raise ValueError(
            f"batch {batch_id!r} result.dispositions must match plan_items exactly"
        )
    if intent == SUB_TDP_INTEGRATION_BATCH_INTENT and not disposition_keys:
        raise ValueError(
            f"batch {batch_id!r} sub_tdp_integration requires disposition records"
        )


def _validate_persisted_production_graph(payload: dict[str, Any]) -> None:
    batches = payload.get("batches") or []
    batch_ids_seen: set[str] = set()
    completed_live_batch_ids: set[str] = set()
    batch_plan_items: dict[str, set[str]] = {}

    for batch in batches:
        if not isinstance(batch, dict):
            continue
        batch_id = str(batch.get("id") or "")
        if batch_id in batch_ids_seen:
            raise ValueError(f"duplicate batch id {batch_id!r}")
        batch_ids_seen.add(batch_id)

        plan_items = batch.get("plan_items") or []
        seen_plan_items: set[str] = set()
        plan_item_set: set[str] = set()
        for item_id in plan_items:
            item_s = str(item_id)
            if item_s in seen_plan_items:
                raise ValueError(f"duplicate plan_item {item_s!r} in batch {batch_id!r}")
            seen_plan_items.add(item_s)
            plan_item_set.add(item_s)
        batch_plan_items[batch_id] = plan_item_set

        evidence_status = batch.get("evidence_status")
        invalidated_item_ids = batch.get("invalidated_item_ids")
        if invalidated_item_ids is not None and evidence_status != "invalidated_by_reconciliation":
            raise ValueError(
                "invalidated_item_ids is only valid when evidence_status is "
                "invalidated_by_reconciliation"
            )
        if evidence_status == "invalidated_by_reconciliation":
            if not invalidated_item_ids:
                raise ValueError(
                    "invalidated_item_ids is required when evidence_status is "
                    "invalidated_by_reconciliation"
                )
            for item_id in invalidated_item_ids:
                if str(item_id) not in plan_item_set:
                    raise ValueError(
                        f"invalidated_item_ids entry {item_id!r} must be in batch plan_items"
                    )
            continue

        status = str(batch.get("status") or "")
        if is_live_completed_batch(batch):
            result = batch.get("result")
            if not isinstance(result, dict):
                raise ValueError(f"completed batch {batch_id!r} requires a result")
            completed_live_batch_ids.add(batch_id)

    output_evidence = payload.get("output_evidence") or []
    evidence_ids_seen: set[str] = set()
    top_level_by_batch: dict[str, dict[str, dict[str, Any]]] = {}
    for entry in output_evidence:
        if not isinstance(entry, dict):
            continue
        evidence_id = str(entry.get("id") or "")
        if evidence_id in evidence_ids_seen:
            raise ValueError(f"duplicate output evidence id {evidence_id!r}")
        evidence_ids_seen.add(evidence_id)

        batch_id = entry.get("batch_id")
        if not isinstance(batch_id, str) or not batch_id.strip():
            raise ValueError("output_evidence batch_id must be a non-empty string")
        if batch_id not in batch_ids_seen:
            raise ValueError(f"output_evidence references unknown batch {batch_id!r}")
        if batch_id not in completed_live_batch_ids:
            raise ValueError(
                f"output_evidence batch {batch_id!r} must reference a completed live batch"
            )
        top_level_by_batch.setdefault(batch_id, {})[evidence_id] = entry

    batch_owned_evidence: dict[str, set[str]] = {}
    for batch in batches:
        if not isinstance(batch, dict):
            continue
        batch_id = str(batch.get("id") or "")
        if batch_id not in completed_live_batch_ids:
            continue
        result = batch.get("result")
        if not isinstance(result, dict):
            continue
        nested_outputs = result.get("outputs") or []
        if not isinstance(nested_outputs, list):
            raise ValueError(f"batch {batch_id!r} result.outputs must be a list")
        nested_by_id: dict[str, dict[str, Any]] = {}
        for index, nested in enumerate(nested_outputs):
            if not isinstance(nested, dict):
                raise ValueError(f"batch {batch_id!r} result.outputs[{index}] must be an object")
            nested_id = str(nested.get("id") or "")
            if not nested_id:
                raise ValueError(f"batch {batch_id!r} result.outputs[{index}].id is required")
            if nested_id in nested_by_id:
                raise ValueError(
                    f"duplicate output id {nested_id!r} in batch {batch_id!r} result.outputs"
                )
            nested_by_id[nested_id] = nested

        top_for_batch = top_level_by_batch.get(batch_id, {})
        for evidence_id, top_entry in top_for_batch.items():
            nested = nested_by_id.get(evidence_id)
            if nested is None:
                raise ValueError(
                    f"output_evidence {evidence_id!r} missing from batch {batch_id!r} result.outputs"
                )
            if not _output_mirrors_match(nested, top_entry):
                raise ValueError(
                    f"output_evidence {evidence_id!r} does not mirror batch {batch_id!r} result.outputs"
                )
            snapshot_ref = str(top_entry.get("snapshot_ref") or "").strip()
            if not snapshot_ref:
                raise ValueError(
                    f"output_evidence {evidence_id!r} requires snapshot_ref"
                )
            nested_snapshot_ref = str(nested.get("snapshot_ref") or "").strip()
            if nested_snapshot_ref != snapshot_ref:
                raise ValueError(
                    f"output_evidence {evidence_id!r} snapshot_ref must mirror nested output"
                )
        for evidence_id in nested_by_id:
            if evidence_id not in top_for_batch:
                raise ValueError(
                    f"batch {batch_id!r} result.outputs[{evidence_id!r}] missing top-level "
                    "output_evidence"
                )
        batch_owned_evidence[batch_id] = set(nested_by_id)

        plan_items = batch_plan_items.get(batch_id, set())
        for contrib in result.get("contributions") or []:
            if not isinstance(contrib, dict):
                continue
            item_id = str(contrib.get("item_id") or "")
            if item_id and item_id not in plan_items:
                raise ValueError(
                    f"contribution item_id {item_id!r} must be in batch {batch_id!r} plan_items"
                )
            owned_ids = batch_owned_evidence.get(batch_id, set())
            for ref in contrib.get("output_refs") or []:
                ref_s = str(ref)
                if ref_s and ref_s not in owned_ids:
                    raise ValueError(
                        f"contribution output_ref {ref_s!r} must reference output owned by "
                        f"batch {batch_id!r}"
                    )

        plan_items = batch_plan_items.get(batch_id, set())
        _validate_batch_disposition_scope(
            batch,
            batch_id=batch_id,
            plan_items=plan_items,
            result=result,
        )

    flat_dispositions = payload.get("dispositions")
    if flat_dispositions is None:
        raise ValueError("production.dispositions is required")
    if not isinstance(flat_dispositions, dict):
        raise ValueError("production.dispositions must be an object")
    try:
        derived_dispositions = derive_live_disposition_map(payload)
    except ValueError as exc:
        raise ValueError(f"dispositions: {exc}") from exc
    flat_normalized = {str(item_id): str(value) for item_id, value in flat_dispositions.items()}
    if flat_normalized != derived_dispositions:
        orphan_items = sorted(set(flat_normalized) - set(derived_dispositions))
        if orphan_items:
            raise ValueError(
                "dispositions contains orphan terminal value(s) for "
                f"{orphan_items[0]!r}"
            )
        missing_items = sorted(set(derived_dispositions) - set(flat_normalized))
        if missing_items:
            raise ValueError(
                "dispositions missing live batch disposition for "
                f"{missing_items[0]!r}"
            )
        for item_id in set(flat_normalized) & set(derived_dispositions):
            if flat_normalized[item_id] != derived_dispositions[item_id]:
                raise ValueError(
                    f"dispositions[{item_id!r}] conflicts with live batch disposition record"
                )


def _parse_persisted_output_evidence(entry: dict[str, Any]) -> OutputEvidence:
    evidence_id = _require_strict_non_empty_str(entry.get("id"), "id")
    evidence_type = _require_strict_non_empty_str(entry.get("type", "artifact"), "type")
    ref = _require_strict_non_empty_str(entry.get("ref"), "ref")
    sha256 = _require_strict_non_empty_str(entry.get("sha256"), "sha256")
    if not _SHA256_PATTERN.fullmatch(sha256):
        raise ValueError("sha256 must be a 64-character lowercase hex digest")
    size = _require_strict_non_negative_int(entry.get("size"), "size")
    media_type = _require_strict_non_empty_str(entry.get("media_type"), "media_type")
    captured_at = _require_strict_non_empty_str(entry.get("captured_at"), "captured_at")
    batch_id = entry.get("batch_id")
    if batch_id is not None and not isinstance(batch_id, str):
        raise ValueError("batch_id must be a string or null")
    snapshot_ref = entry.get("snapshot_ref")
    if snapshot_ref is not None and not isinstance(snapshot_ref, str):
        raise ValueError("snapshot_ref must be a string or null")
    return OutputEvidence(
        id=evidence_id,
        type=evidence_type,
        ref=ref,
        sha256=sha256,
        size=size,
        media_type=media_type,
        captured_at=captured_at,
        batch_id=batch_id,
        snapshot_ref=snapshot_ref,
    )


def _parse_persisted_contribution(entry: dict[str, Any]) -> Contribution:
    item_id = _require_strict_non_empty_str(entry.get("item_id"), "item_id")
    output_refs_raw = entry.get("output_refs")
    if output_refs_raw is None:
        output_refs_raw = []
    if not isinstance(output_refs_raw, list):
        raise ValueError("output_refs must be a list")
    output_refs = [
        _require_strict_non_empty_str(ref, "output_ref") for ref in output_refs_raw
    ]
    summary = entry.get("summary")
    if summary is not None and not isinstance(summary, str):
        raise ValueError("summary must be a string")
    return Contribution(
        item_id=item_id,
        output_refs=output_refs,
        summary=str(summary or ""),
    )


def _parse_persisted_batch_result(result: dict[str, Any]) -> BatchResult:
    outputs_raw = result.get("outputs")
    if outputs_raw is None:
        outputs_raw = []
    if not isinstance(outputs_raw, list):
        raise ValueError("result.outputs must be a list")
    outputs = []
    for index, entry in enumerate(outputs_raw):
        if not isinstance(entry, dict):
            raise ValueError(f"result.outputs[{index}] must be an object")
        outputs.append(_parse_persisted_output_evidence(entry))

    contributions_raw = result.get("contributions")
    if contributions_raw is None:
        contributions_raw = []
    if not isinstance(contributions_raw, list):
        raise ValueError("result.contributions must be a list")
    contributions = []
    for index, entry in enumerate(contributions_raw):
        if not isinstance(entry, dict):
            raise ValueError(f"result.contributions[{index}] must be an object")
        contributions.append(_parse_persisted_contribution(entry))

    dispositions_raw = result.get("dispositions")
    if dispositions_raw is None:
        dispositions_raw = {}
    if not isinstance(dispositions_raw, dict):
        raise ValueError("result.dispositions must be an object")
    dispositions: dict[str, ItemDispositionRecord] = {}
    for item_id, value in dispositions_raw.items():
        if not isinstance(value, dict):
            raise ValueError(f"result.dispositions[{item_id!r}] must be an object")
        dispositions[str(item_id)] = _parse_persisted_disposition_record(value)

    summary = result.get("summary")
    if summary is not None and not isinstance(summary, str):
        raise ValueError("result.summary must be a string")
    empty_output = result.get("empty_output", False)
    if not isinstance(empty_output, bool):
        raise ValueError("result.empty_output must be a boolean")
    empty_output_reason = result.get("empty_output_reason")
    if empty_output_reason is not None and not isinstance(empty_output_reason, str):
        raise ValueError("result.empty_output_reason must be a string or null")
    goal_assessment = result.get("goal_assessment")
    if goal_assessment is not None and not isinstance(goal_assessment, str):
        raise ValueError("result.goal_assessment must be a string")

    return BatchResult(
        outputs=outputs,
        contributions=contributions,
        dispositions=dispositions,
        summary=str(summary or ""),
        empty_output=empty_output,
        empty_output_reason=empty_output_reason,
        goal_assessment=str(goal_assessment or ""),
    )


def _parse_persisted_batch(batch: dict[str, Any]) -> ProductionBatch:
    batch_id = _require_strict_non_empty_str(batch.get("id"), "id")
    if "status" not in batch:
        raise ValueError("batch status is required")
    status = _require_strict_non_empty_str(batch.get("status"), "status")
    if status not in _VALID_BATCH_STATUSES:
        raise ValueError(f"invalid batch status: {status!r}")
    evidence_status = batch.get("evidence_status")
    if evidence_status is not None:
        if (
            not isinstance(evidence_status, str)
            or evidence_status not in _VALID_BATCH_EVIDENCE_STATUSES
        ):
            raise ValueError("evidence_status must be invalidated_by_reconciliation")
    invalidated_item_ids = batch.get("invalidated_item_ids")
    if invalidated_item_ids is not None:
        _require_strict_string_list(invalidated_item_ids, "invalidated_item_ids")
    plan_items_raw = batch.get("plan_items")
    if plan_items_raw is None:
        plan_items_raw = []
    if not isinstance(plan_items_raw, list):
        raise ValueError("plan_items must be a list")
    plan_items = [
        _require_strict_non_empty_str(item_id, "plan_item") for item_id in plan_items_raw
    ]
    agent_turns = batch.get("agent_turns", 0)
    if agent_turns is None:
        agent_turns = 0
    agent_turns = _require_strict_non_negative_int(agent_turns, "agent_turns")
    intent = batch.get("intent")
    if intent is not None and not isinstance(intent, str):
        raise ValueError("intent must be a string or null")
    result_payload = batch.get("result")
    result = None
    if result_payload is not None:
        if not isinstance(result_payload, dict):
            raise ValueError("batch result must be an object")
        result = _parse_persisted_batch_result(result_payload)
    return ProductionBatch(
        id=batch_id,
        plan_items=plan_items,
        status=status,
        agent_turns=agent_turns,
        intent=intent,
        result=result,
    )


def reject_protected_run_extras_keys(run_extras: dict[str, Any]) -> None:
    collisions = sorted(_PROTECTED_RUN_RECORD_KEYS.intersection(run_extras))
    if collisions:
        joined = ", ".join(collisions)
        raise PersistenceError(f"run_extras cannot overwrite protected run fields: {joined}")


def _validate_persisted_binding(
    binding_raw: dict[str, Any],
    *,
    label: str,
    expected_role: str | None = None,
    expected_kind: str | None = None,
) -> dict[str, Any]:
    try:
        binding = SessionBinding.from_persisted_dict(binding_raw)
    except SessionBindingError as exc:
        raise PersistenceError(f"{label} is invalid: {exc}") from exc
    if expected_role is not None and binding.role != expected_role:
        raise PersistenceError(f"{label} must have role={expected_role!r}")
    if expected_kind is not None and binding.kind != expected_kind:
        raise PersistenceError(f"{label} must have kind={expected_kind!r}")
    validate_session_binding(binding)
    return binding.to_dict()


def validate_persisted_sessions(sessions: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(sessions, dict):
        raise PersistenceError("sessions must be an object on schema v3 run records")

    structured: dict[str, dict[str, Any]] = {}
    for slot, (role, kind) in _SLOT_ROLE_KIND.items():
        binding_raw = sessions.get(slot)
        if not isinstance(binding_raw, dict):
            raise PersistenceError(f"sessions.{slot} must be a structured session binding")
        structured[slot] = _validate_persisted_binding(
            binding_raw,
            label=f"sessions.{slot}",
            expected_role=role,
            expected_kind=kind,
        )

    for key, value in sessions.items():
        if key in _SLOT_ROLE_KIND:
            continue
        if not isinstance(value, dict) or not value.get("session_instance_id"):
            raise PersistenceError(
                f"sessions.{key} must be a structured session binding with session_instance_id"
            )
        structured[key] = _validate_persisted_binding(
            value,
            label=f"sessions.{key}",
        )
    return structured


def validate_persisted_review_binding(review: dict[str, Any]) -> dict[str, Any]:
    payload = dict(review)
    if "revision" in payload:
        payload["revision"] = parse_revision_value(payload["revision"], "review")
    binding_raw = payload.get("reviewer_binding")
    if binding_raw is None:
        return payload
    if not isinstance(binding_raw, dict) or not binding_raw.get("session_instance_id"):
        raise PersistenceError("reviewer_binding must be a structured session binding")
    payload["reviewer_binding"] = _validate_persisted_binding(
        binding_raw,
        label="reviewer_binding",
        expected_role="reviewer",
        expected_kind="reviewer",
    )
    return payload


def _validate_required_run_digests(payload: dict[str, Any]) -> None:
    digests = payload.get("digests")
    if not isinstance(digests, dict):
        raise PersistenceError("digests must be an object on schema v3 run records")
    for key in _REQUIRED_V3_DIGEST_KEYS:
        _require_persisted_sha256_digest(
            digests.get(key),
            field_name=f"digests.{key}",
        )
    output_digest = digests.get("output")
    if output_digest is not None and str(output_digest).strip():
        _require_persisted_sha256_digest(output_digest, field_name="digests.output")


def _require_sha256_digest_field(value: str, *, field_name: str) -> None:
    if not _SHA256_PATTERN.fullmatch(value):
        raise PersistenceError(f"{field_name} must be a 64-character lowercase hex digest")


def validate_canonical_run(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a run payload for publication and reload symmetry."""

    normalized = validate_persisted_run(run_id, payload)
    try:
        validate_run_lifecycle_invariants(normalized)
        validate_session_recovery_fields(normalized)
    except RunLifecycleError as exc:
        raise PersistenceError(str(exc)) from exc
    return normalized


def validate_persisted_run(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    validate_run_schema_version(payload)
    validate_run_digests(payload)
    _validate_required_run_digests(payload)
    persisted_id = str(payload.get("id") or "").strip()
    if persisted_id != run_id:
        raise PersistenceError("run.id does not match run directory id")
    parse_revision_value(payload.get("revision"), "run")
    binding = payload.get("context_snapshot_binding")
    if not isinstance(binding, dict):
        raise PersistenceError("context_snapshot_binding is required on schema v3 run records")
    validate_context_snapshot_binding(binding)
    sessions = validate_persisted_sessions(payload.get("sessions"))
    normalized = dict(payload)
    normalized["sessions"] = sessions
    return normalized


def canonicalize_persisted_plan(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PersistenceError("plan.json must contain a JSON object")
    return Plan.from_dict(dict(payload)).to_dict()


def validate_persisted_production(
    payload: dict[str, Any],
    *,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PersistenceError("production.json must contain a JSON object")
    parse_revision_value(payload.get("revision"), "production")
    parse_revision_value(payload.get("output_revision"), "production output")
    batches = payload.get("batches")
    if batches is None:
        raise PersistenceError("production.batches is required")
    if not isinstance(batches, list):
        raise PersistenceError("production.batches must be a list")
    for index, batch in enumerate(batches):
        if not isinstance(batch, dict):
            raise PersistenceError(f"production.batches[{index}] must be an object")
        try:
            _parse_persisted_batch(batch)
        except (KeyError, TypeError, ValueError) as exc:
            raise PersistenceError(
                f"production.batches[{index}] is invalid: {exc}"
            ) from exc
    dispositions = payload.get("dispositions")
    if dispositions is None:
        raise PersistenceError("production.dispositions is required")
    if not isinstance(dispositions, dict):
        raise PersistenceError("production.dispositions must be an object")
    for item_id, value in dispositions.items():
        _validate_persisted_flat_disposition_value(str(item_id), value)
    output_evidence = payload.get("output_evidence")
    if output_evidence is None:
        output_evidence = []
    if not isinstance(output_evidence, list):
        raise PersistenceError("production.output_evidence must be a list")
    for index, entry in enumerate(output_evidence):
        if not isinstance(entry, dict):
            raise PersistenceError(f"production.output_evidence[{index}] must be an object")
        try:
            _parse_persisted_output_evidence(entry)
        except (KeyError, TypeError, ValueError) as exc:
            raise PersistenceError(
                f"production.output_evidence[{index}] is invalid: {exc}"
            ) from exc
    completion_claim = payload.get("completion_claim")
    if completion_claim is not None:
        if not isinstance(completion_claim, dict):
            raise PersistenceError("production.completion_claim must be an object or null")
        try:
            _parse_persisted_completion_claim(completion_claim)
        except (KeyError, TypeError, ValueError) as exc:
            raise PersistenceError(f"production.completion_claim is invalid: {exc}") from exc
        try:
            _validate_completion_claim_bindings(payload, plan)
        except (KeyError, TypeError, ValueError) as exc:
            raise PersistenceError(f"production.completion_claim is invalid: {exc}") from exc
    for field_name in ("amendment_requests", "reconciliation_reports"):
        value = payload.get(field_name)
        if value is None:
            continue
        if not isinstance(value, list):
            raise PersistenceError(f"production.{field_name} must be a list")
        for index, entry in enumerate(value):
            if not isinstance(entry, dict):
                raise PersistenceError(f"production.{field_name}[{index}] must be an object")
            try:
                if field_name == "amendment_requests":
                    _parse_persisted_amendment_request(entry)
                else:
                    _parse_persisted_reconciliation_report(entry)
            except (KeyError, TypeError, ValueError) as exc:
                raise PersistenceError(
                    f"production.{field_name}[{index}] is invalid: {exc}"
                ) from exc
    try:
        _validate_persisted_amendment_state(payload)
    except PersistenceError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise PersistenceError(f"production amendment state is invalid: {exc}") from exc
    blocker_report = payload.get("blocker_report")
    if blocker_report is not None:
        if not isinstance(blocker_report, dict):
            raise PersistenceError("production.blocker_report must be an object or null")
        try:
            _parse_persisted_blocker_report(blocker_report)
        except (KeyError, TypeError, ValueError) as exc:
            raise PersistenceError(f"production.blocker_report is invalid: {exc}") from exc
    sub_tdps = payload.get("sub_tdps")
    if sub_tdps is not None:
        if not isinstance(sub_tdps, dict):
            raise PersistenceError("production.sub_tdps must be an object or null")
        try:
            _parse_persisted_sub_tdps(sub_tdps)
        except (KeyError, TypeError, ValueError) as exc:
            raise PersistenceError(f"production.sub_tdps is invalid: {exc}") from exc
    try:
        _validate_persisted_production_graph(payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise PersistenceError(f"production graph is invalid: {exc}") from exc
    return dict(payload)


_PRESERVED_REVIEW_ATTESTATION_KEYS = (
    "plan_review_inherited",
    "inherited_plan_approval",
    "plan_source",
)


def canonicalize_persisted_review(
    expected_review_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PersistenceError("review record must be a mapping")
    if "revision" in payload:
        parse_revision_value(payload["revision"], "review")
    review_id = str(payload.get("id") or "").strip()
    if review_id != expected_review_id:
        raise PersistenceError("review.id does not match review filename id")
    loop = ReviewLoop.from_dict(dict(payload))
    normalized = validate_persisted_review_binding(loop.to_dict())
    for key in _PRESERVED_REVIEW_ATTESTATION_KEYS:
        if key in payload:
            normalized[key] = payload[key]
    if str(normalized.get("id") or "").strip() != expected_review_id:
        raise PersistenceError("review.id does not match review filename id")
    return normalized


__all__ = [
    "canonicalize_persisted_plan",
    "canonicalize_persisted_review",
    "reject_protected_run_extras_keys",
    "validate_canonical_run",
    "validate_persisted_production",
    "validate_persisted_review_binding",
    "validate_persisted_run",
    "validate_persisted_sessions",
]
