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
        if not isinstance(goal_assessment, str) or not goal_assessment.strip():
            raise ValueError("goal_assessment must be a non-empty string")
        full_fields = ("plan_revision", "output_revision", "all_applicable_items_processed")
        if all(key in value for key in full_fields):
            _require_strict_non_negative_int(value.get("plan_revision"), "plan_revision")
            _require_strict_non_negative_int(value.get("output_revision"), "output_revision")
            if value.get("all_applicable_items_processed") is not True:
                raise ValueError("all_applicable_items_processed must be true")
        return

    if status == "integration_pending":
        if not isinstance(goal_assessment, str) or not goal_assessment.strip():
            raise ValueError("goal_assessment must be a non-empty string")
        submitted_at = value.get("submitted_at")
        if submitted_at is not None and not isinstance(submitted_at, str):
            raise ValueError("submitted_at must be a string")
        return

    if goal_assessment is None:
        raise ValueError("goal_assessment must be a string")


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


def _parse_persisted_sub_tdp_unit(value: dict[str, Any], *, label: str) -> None:
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
    if unit_plan_digest is not None:
        if not isinstance(unit_plan_digest, str) or not _SHA256_PATTERN.fullmatch(
            unit_plan_digest
        ):
            raise ValueError(f"{label}.unit_plan_digest must be a 64-character lowercase hex digest")
    assigned_subtree_digest = value.get("assigned_subtree_digest")
    if assigned_subtree_digest is not None:
        if not isinstance(assigned_subtree_digest, str) or not _SHA256_PATTERN.fullmatch(
            assigned_subtree_digest
        ):
            raise ValueError(
                f"{label}.assigned_subtree_digest must be a 64-character lowercase hex digest"
            )
    depends_on = value.get("depends_on")
    if depends_on is not None:
        _require_strict_string_list(depends_on, f"{label}.depends_on")
    if unit_id != plan_item_id:
        raise ValueError(f"{label}.id must match plan_item_id")
    if status == UNIT_STATUS_COMPLETED:
        digest = value.get("accepted_result_digest")
        if not isinstance(digest, str) or not _SHA256_PATTERN.fullmatch(digest):
            raise ValueError(
                f"{label}.accepted_result_digest must be a 64-character lowercase hex digest"
            )
        try:
            verify_accepted_result_attestation(value)
        except ValueError as exc:
            raise ValueError(f"{label} completed unit attestation is invalid: {exc}") from exc


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
    if package_id is not None and not isinstance(package_id, str):
        raise ValueError("sub_tdps.package_id must be a string")
    package_digest = value.get("package_digest")
    if package_digest is not None:
        if not isinstance(package_digest, str) or not _SHA256_PATTERN.fullmatch(package_digest):
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
        _parse_persisted_sub_tdp_unit(unit, label=label)
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


def _validate_persisted_production_graph(payload: dict[str, Any]) -> None:
    batches = payload.get("batches") or []
    batch_ids_seen: set[str] = set()
    live_batch_ids_set: set[str] = set()

    for batch in batches:
        if not isinstance(batch, dict):
            continue
        batch_id = str(batch.get("id") or "")
        if batch_id in batch_ids_seen:
            raise ValueError(f"duplicate batch id {batch_id!r}")
        batch_ids_seen.add(batch_id)

        plan_items = batch.get("plan_items") or []
        seen_plan_items: set[str] = set()
        for item_id in plan_items:
            item_s = str(item_id)
            if item_s in seen_plan_items:
                raise ValueError(f"duplicate plan_item {item_s!r} in batch {batch_id!r}")
            seen_plan_items.add(item_s)

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
            plan_item_set = {str(item_id) for item_id in plan_items}
            for item_id in invalidated_item_ids:
                if str(item_id) not in plan_item_set:
                    raise ValueError(
                        f"invalidated_item_ids entry {item_id!r} must be in batch plan_items"
                    )
        else:
            live_batch_ids_set.add(batch_id)

    output_evidence = payload.get("output_evidence") or []
    evidence_ids_seen: set[str] = set()
    live_evidence_ids: set[str] = set()
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
        if batch_id in live_batch_ids_set:
            live_evidence_ids.add(evidence_id)

    for batch in batches:
        if not isinstance(batch, dict):
            continue
        batch_id = str(batch.get("id") or "")
        if batch_id not in live_batch_ids_set:
            continue
        result = batch.get("result")
        if not isinstance(result, dict):
            continue
        for contrib in result.get("contributions") or []:
            if not isinstance(contrib, dict):
                continue
            for ref in contrib.get("output_refs") or []:
                ref_s = str(ref)
                if ref_s and ref_s not in live_evidence_ids:
                    raise ValueError(
                        f"contribution output_ref {ref_s!r} does not reference live "
                        "output_evidence"
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


def validate_persisted_production(payload: dict[str, Any]) -> dict[str, Any]:
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
