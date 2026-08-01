"""Phase and capability enforcement for agent mutations."""

from __future__ import annotations

import os
from typing import Any

from top_down_planning.agent_tool.errors import CapabilityDeniedError
from top_down_planning.domain.capability_binding import (
    CapabilitySessionBinding,
    record_capability_binding,
)
from top_down_planning.domain.reviews import ReviewLoop
from top_down_planning.domain.session_bindings import binding_provider_session_id
from top_down_planning.persistence.capabilities import (
    CAPABILITY_ENV_VAR,
    MUTATING_OPS,
    parse_capability_token,
    verify_capability_secret,
)
from top_down_planning.persistence.interface import RunStore
from top_down_planning.persistence.session_bindings import get_primary_binding


def resolve_capability_token(explicit: str | None = None) -> str | None:
    """Resolve a capability token from an explicit value or process env."""

    if explicit is not None and str(explicit).strip():
        return str(explicit).strip()
    env_value = os.environ.get(CAPABILITY_ENV_VAR)
    if env_value is None or not str(env_value).strip():
        return None
    return str(env_value).strip()


def _assert_capability_binding_matches(
    record: dict[str, Any],
    expected: CapabilitySessionBinding,
    *,
    operation: str,
    message: str,
) -> None:
    record_binding = record_capability_binding(record)
    if record_binding is None:
        if str(record.get("session_id") or "").strip() != expected.provider_session_id:
            raise CapabilityDeniedError(message, operation=operation)
        return
    if (
        record_binding.session_instance_id != expected.session_instance_id
        or record_binding.generation != expected.generation
        or record_binding.provider_session_id != expected.provider_session_id
    ):
        raise CapabilityDeniedError(message, operation=operation)


def authorize_mutation(
    store: RunStore,
    run_id: str,
    *,
    operation: str,
    capability_token: str | None = None,
    loop_id: str | None = None,
) -> str:
    """Authorize a mutating agent operation and return the bound role."""

    if operation not in MUTATING_OPS:
        raise CapabilityDeniedError(
            f"unknown mutating operation: {operation}",
            operation=operation,
        )

    token = resolve_capability_token(capability_token)
    if token is None:
        raise CapabilityDeniedError(
            "mutating agent commands require a capability token "
            f"({CAPABILITY_ENV_VAR} or capability_token parameter)",
            operation=operation,
        )

    try:
        token_id, secret = parse_capability_token(token)
    except ValueError as exc:
        raise CapabilityDeniedError(str(exc), operation=operation) from exc

    record = store.load_capability(run_id, token_id)
    if record.get("revoked") is True:
        raise CapabilityDeniedError("capability token has been revoked", operation=operation)

    secret_hash = str(record.get("secret_hash") or "")
    if not secret_hash:
        raise CapabilityDeniedError("capability token is invalid", operation=operation)
    if not verify_capability_secret(secret, secret_hash):
        raise CapabilityDeniedError("capability token is invalid", operation=operation)

    run = store.load_run(run_id)
    status = str(run.get("status") or "running")
    current_phase = str(run.get("phase") or "")
    if status != "running" and not (status == "paused" and current_phase == "plan_amendment"):
        raise CapabilityDeniedError(
            f"mutations are not allowed when run status is {status!r}",
            operation=operation,
        )

    record_phase = str(record.get("phase") or "")
    if record_phase != current_phase:
        raise CapabilityDeniedError(
            f"capability token phase {record_phase!r} does not match run phase {current_phase!r}",
            operation=operation,
        )

    allowed_ops = frozenset(str(item) for item in (record.get("allowed_ops") or []))
    if operation not in allowed_ops:
        raise CapabilityDeniedError(
            f"operation {operation!r} is not allowed for this capability",
            operation=operation,
        )

    role = str(record.get("role") or "").strip()
    if not role:
        raise CapabilityDeniedError(
            "Capability record is missing role.",
            operation=operation,
        )

    record_session_id = str(record.get("session_id") or "").strip()
    if not record_session_id:
        raise CapabilityDeniedError(
            "capability token is not bound to a session",
            operation=operation,
        )

    if role == "reviewer":
        record_loop_id = str(record.get("loop_id") or "").strip()
        if not record_loop_id:
            raise CapabilityDeniedError(
                "reviewer capability is not bound to a review loop",
                operation=operation,
            )
        loop = ReviewLoop.from_dict(store.load_review(run_id, record_loop_id))
        binding = loop.reviewer_binding
        provider_session_id = binding_provider_session_id(binding)
        if not provider_session_id or provider_session_id != record_session_id:
            raise CapabilityDeniedError(
                "capability token session does not match the review loop reviewer session",
                operation=operation,
            )
        if binding is not None:
            expected = CapabilitySessionBinding(
                session_instance_id=binding.session_instance_id,
                generation=int(binding.generation),
                provider_session_id=provider_session_id,
            )
            _assert_capability_binding_matches(
                record,
                expected,
                operation=operation,
                message=(
                    "capability token session does not match the review loop reviewer session"
                ),
            )
        if operation == "review_respond":
            if loop_id is None or not str(loop_id).strip():
                raise CapabilityDeniedError(
                    "review_respond requires a loop_id bound to the capability",
                    operation=operation,
                )
            if str(loop_id).strip() != record_loop_id:
                raise CapabilityDeniedError(
                    "capability token is not authorized for this review loop",
                    operation=operation,
                )
    else:
        binding = get_primary_binding(run, role)
        provider_session_id = binding_provider_session_id(binding)
        if provider_session_id is None or provider_session_id != record_session_id:
            raise CapabilityDeniedError(
                "capability token session does not match the active provider session",
                operation=operation,
            )
        if binding is not None:
            expected = CapabilitySessionBinding(
                session_instance_id=binding.session_instance_id,
                generation=int(binding.generation),
                provider_session_id=provider_session_id,
            )
            _assert_capability_binding_matches(
                record,
                expected,
                operation=operation,
                message="capability token session does not match the active provider session",
            )

    return role
