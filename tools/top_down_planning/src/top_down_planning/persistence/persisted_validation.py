"""Strict validation for persisted current-schema records at the store boundary."""

from __future__ import annotations

from typing import Any

from core_tools.persistence import PersistenceError, parse_revision_value

from top_down_planning.config.binding_validation import validate_context_snapshot_binding
from top_down_planning.domain.models import Plan
from top_down_planning.domain.production import (
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
        value = digests.get(key)
        if not value or not str(value).strip():
            raise PersistenceError(f"digests.{key} is required on schema v3 run records")


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
            ProductionBatch.from_dict(batch)
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
        if isinstance(value, str):
            if not str(value).strip():
                raise PersistenceError(
                    f"production.dispositions[{item_id!r}] must be a non-empty string"
                )
            continue
        if not isinstance(value, dict):
            raise PersistenceError(
                f"production.dispositions[{item_id!r}] must be a string or object"
            )
        try:
            ItemDispositionRecord.from_dict(value)
        except (KeyError, TypeError, ValueError) as exc:
            raise PersistenceError(
                f"production.dispositions[{item_id!r}] is invalid: {exc}"
            ) from exc
    output_evidence = payload.get("output_evidence")
    if output_evidence is None:
        output_evidence = []
    if not isinstance(output_evidence, list):
        raise PersistenceError("production.output_evidence must be a list")
    for index, entry in enumerate(output_evidence):
        if not isinstance(entry, dict):
            raise PersistenceError(f"production.output_evidence[{index}] must be an object")
        try:
            OutputEvidence.from_dict(entry)
        except (KeyError, TypeError, ValueError) as exc:
            raise PersistenceError(
                f"production.output_evidence[{index}] is invalid: {exc}"
            ) from exc
    completion_claim = payload.get("completion_claim")
    if completion_claim is not None and not isinstance(completion_claim, dict):
        raise PersistenceError("production.completion_claim must be an object or null")
    for field_name in ("amendment_requests", "reconciliation_reports"):
        value = payload.get(field_name)
        if value is None:
            continue
        if not isinstance(value, list):
            raise PersistenceError(f"production.{field_name} must be a list")
    blocker_report = payload.get("blocker_report")
    if blocker_report is not None and not isinstance(blocker_report, dict):
        raise PersistenceError("production.blocker_report must be an object or null")
    sub_tdps = payload.get("sub_tdps")
    if sub_tdps is not None and not isinstance(sub_tdps, dict):
        raise PersistenceError("production.sub_tdps must be an object or null")
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
