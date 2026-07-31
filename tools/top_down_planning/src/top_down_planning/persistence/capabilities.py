"""Session capability tokens for agent mutation authorization."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

CAPABILITY_ENV_VAR = "TDP_CAPABILITY_TOKEN"

MUTATING_OPS = frozenset(
    {
        "plan_apply",
        "production_apply",
        "production_request_amendment",
        "production_submit_completion",
        "production_report_blocked",
        "review_request",
        "review_respond",
        "review_record_finding_actions",
    }
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def hash_capability_secret(secret: str) -> str:
    """Return the persisted hash for a capability secret."""

    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def verify_capability_secret(secret: str, secret_hash: str) -> bool:
    """Constant-time compare of a secret against its stored hash."""

    expected = hash_capability_secret(secret)
    return hmac.compare_digest(expected, secret_hash)


def ops_for_session(
    role: str,
    phase: str,
    *,
    session_kind: str = "primary",
) -> frozenset[str]:
    """Return mutating operations a session may perform."""

    normalized_role = str(role).strip()
    normalized_phase = str(phase).strip()
    if normalized_role == "reviewer" or session_kind == "reviewer":
        return frozenset({"review_respond"})

    if normalized_role == "planner":
        if normalized_phase in {"planning", "whole_plan_review", "plan_amendment"}:
            ops = {"plan_apply", "review_record_finding_actions"}
            if normalized_phase == "planning":
                ops.add("review_request")
            return frozenset(ops)

    if normalized_role == "producer":
        if normalized_phase in {"plan_validated", "production"}:
            return frozenset(
                {
                    "production_apply",
                    "production_request_amendment",
                    "production_submit_completion",
                    "production_report_blocked",
                    "review_request",
                    "review_record_finding_actions",
                }
            )
        if normalized_phase == "whole_output_review":
            return frozenset(
                {
                    "production_apply",
                    "production_submit_completion",
                    "review_record_finding_actions",
                }
            )

    return frozenset()


def new_capability_record(
    *,
    run_id: str,
    role: str,
    phase: str,
    allowed_ops: frozenset[str],
    session_id: str,
    session_kind: str = "primary",
    loop_id: str | None = None,
) -> tuple[str, dict[str, Any], str]:
    """Create a capability token id, persisted record, and one-time raw secret."""

    if not str(session_id).strip():
        raise ValueError("session_id is required for capability records")
    normalized_session_id = str(session_id).strip()
    normalized_role = str(role).strip()
    if normalized_role == "reviewer" or session_kind == "reviewer":
        if loop_id is None or not str(loop_id).strip():
            raise ValueError("loop_id is required for reviewer capabilities")

    token_id = f"cap-{uuid.uuid4().hex}"
    raw_secret = secrets.token_hex(32)
    record: dict[str, Any] = {
        "id": token_id,
        "secret_hash": hash_capability_secret(raw_secret),
        "run_id": run_id,
        "role": role,
        "phase": phase,
        "session_kind": session_kind,
        "session_id": normalized_session_id,
        "allowed_ops": sorted(allowed_ops),
        "created_at": _utc_now(),
        "revoked": False,
    }
    if loop_id is not None:
        record["loop_id"] = str(loop_id).strip()
    return token_id, record, raw_secret


def capability_token_value(token_id: str, raw_secret: str) -> str:
    """Serialize a capability token for env export or CLI use."""

    return f"{token_id}.{raw_secret}"


def parse_capability_token(value: str) -> tuple[str, str]:
    """Split a capability token into id and secret."""

    if "." not in value:
        raise ValueError("capability token must contain id and secret")
    token_id, secret = value.split(".", 1)
    if not token_id or not secret:
        raise ValueError("capability token must contain id and secret")
    return token_id, secret
