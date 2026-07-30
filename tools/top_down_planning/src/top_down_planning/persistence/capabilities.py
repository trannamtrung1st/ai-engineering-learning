"""Session capability tokens for agent mutation authorization."""

from __future__ import annotations

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
    }
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
            ops = {"plan_apply"}
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
                }
            )
        if normalized_phase == "whole_output_review":
            return frozenset({"production_apply", "production_submit_completion"})

    return frozenset()


def new_capability_record(
    *,
    run_id: str,
    role: str,
    phase: str,
    allowed_ops: frozenset[str],
    session_id: str | None = None,
    session_kind: str = "primary",
) -> tuple[str, dict[str, Any]]:
    """Create a capability token id and persisted record."""

    token_id = f"cap-{uuid.uuid4().hex}"
    record = {
        "id": token_id,
        "secret": secrets.token_hex(32),
        "run_id": run_id,
        "role": role,
        "phase": phase,
        "session_kind": session_kind,
        "session_id": session_id,
        "allowed_ops": sorted(allowed_ops),
        "created_at": _utc_now(),
        "revoked": False,
    }
    return token_id, record


def capability_token_value(record: dict[str, Any]) -> str:
    """Serialize a capability token for env export or CLI use."""

    return f"{record['id']}.{record['secret']}"


def parse_capability_token(value: str) -> tuple[str, str]:
    """Split a capability token into id and secret."""

    if "." not in value:
        raise ValueError("capability token must contain id and secret")
    token_id, secret = value.split(".", 1)
    if not token_id or not secret:
        raise ValueError("capability token must contain id and secret")
    return token_id, secret
