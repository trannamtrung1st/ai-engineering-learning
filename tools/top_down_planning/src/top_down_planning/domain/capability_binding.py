"""Capability binding to internal session identity (proposal §9.2, RR-SESSION-05)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from top_down_planning.domain.session_bindings import (
    PRIMARY_PLANNER_SLOT,
    PRIMARY_PRODUCER_SLOT,
    SessionBinding,
    SessionBindingError,
)


@dataclass(frozen=True)
class CapabilitySessionBinding:
    session_instance_id: str
    generation: int
    provider_session_id: str

    def to_record_fields(self) -> dict[str, Any]:
        return {
            "session_instance_id": self.session_instance_id,
            "generation": int(self.generation),
            "session_id": self.provider_session_id,
        }


def capability_binding_from_session_binding(
    binding: SessionBinding,
    *,
    provider_session_id: str,
) -> CapabilitySessionBinding:
    return CapabilitySessionBinding(
        session_instance_id=binding.session_instance_id,
        generation=int(binding.generation),
        provider_session_id=str(provider_session_id).strip(),
    )


def resolve_primary_capability_binding(
    run: dict[str, Any],
    role: str,
    *,
    provider_session_id: str,
) -> CapabilitySessionBinding:
    sessions = run.get("sessions") or {}
    slot = PRIMARY_PLANNER_SLOT if role == "planner" else PRIMARY_PRODUCER_SLOT
    payload = sessions.get(slot)
    if not isinstance(payload, dict) or not payload.get("session_instance_id"):
        raise SessionBindingError(
            f"structured session binding for role {role!r} is required before capability issuance"
        )
    binding = SessionBinding.from_dict(payload)
    return capability_binding_from_session_binding(
        binding,
        provider_session_id=provider_session_id,
    )


def resolve_reviewer_capability_binding(
    loop: dict[str, Any] | Any,
    *,
    provider_session_id: str,
    loop_id: str | None = None,
) -> CapabilitySessionBinding:
    from top_down_planning.domain.reviews import ReviewLoop

    if isinstance(loop, ReviewLoop):
        review_loop = loop
    else:
        review_loop = ReviewLoop.from_dict(dict(loop))

    binding = review_loop.reviewer_binding
    if binding is None:
        raise ValueError("reviewer session binding is required for capability issuance")
    return capability_binding_from_session_binding(
        binding,
        provider_session_id=provider_session_id,
    )


def record_capability_binding(record: dict[str, Any]) -> CapabilitySessionBinding | None:
    instance_id = str(record.get("session_instance_id") or "").strip()
    if not instance_id:
        return None
    provider_session_id = str(record.get("session_id") or "").strip()
    if not provider_session_id:
        return None
    generation_raw = record.get("generation")
    if generation_raw is None:
        return None
    return CapabilitySessionBinding(
        session_instance_id=instance_id,
        generation=int(generation_raw),
        provider_session_id=provider_session_id,
    )


def capability_binding_matches_record(
    record: dict[str, Any],
    expected: CapabilitySessionBinding,
) -> bool:
    bound = record_capability_binding(record)
    if bound is None:
        return False
    return (
        bound.session_instance_id == expected.session_instance_id
        and bound.generation == expected.generation
        and bound.provider_session_id == expected.provider_session_id
    )


__all__ = [
    "CapabilitySessionBinding",
    "capability_binding_from_session_binding",
    "capability_binding_matches_record",
    "record_capability_binding",
    "resolve_primary_capability_binding",
    "resolve_reviewer_capability_binding",
]
