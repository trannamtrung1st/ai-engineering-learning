"""Structured session bindings (proposal §9)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from typing import Any, Literal

SessionBindingState = Literal["unbound", "starting", "bound"]
SessionRole = Literal["planner", "producer", "reviewer"]
SessionKind = Literal["primary", "reviewer"]

PRIMARY_PLANNER_SLOT = "primary_planner"
PRIMARY_PRODUCER_SLOT = "primary_producer"

LEGACY_PRIMARY_SESSION_FIELDS: dict[str, str] = {
    "primary_planner_session_id": PRIMARY_PLANNER_SLOT,
    "primary_producer_session_id": PRIMARY_PRODUCER_SLOT,
}


class SessionBindingError(ValueError):
    """Invalid session binding state or payload."""


def new_session_instance_id() -> str:
    return f"tdp-session-{uuid.uuid4().hex[:12]}"


def is_transient_provider_session_id(value: str | None) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    return bool(text) and text.startswith("cursor-pending-")


def validate_durable_provider_session_id(value: str | None) -> str:
    if value is None or not str(value).strip():
        raise SessionBindingError("provider_session_id is required")
    text = str(value).strip()
    if is_transient_provider_session_id(text):
        raise SessionBindingError(
            f"transient provider session id must not be persisted: {text!r}"
        )
    return text


@dataclass(frozen=True)
class SessionBinding:
    session_instance_id: str
    generation: int
    role: str
    kind: str
    state: SessionBindingState = "unbound"
    provider: str | None = None
    provider_session_id: str | None = None
    model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "session_instance_id": self.session_instance_id,
            "generation": int(self.generation),
            "role": self.role,
            "kind": self.kind,
            "state": self.state,
        }
        if self.provider is not None:
            payload["provider"] = self.provider
        if self.provider_session_id is not None:
            payload["provider_session_id"] = self.provider_session_id
        if self.model is not None:
            payload["model"] = self.model
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SessionBinding:
        if not isinstance(payload, dict):
            raise SessionBindingError("session binding payload must be a mapping")
        instance_id = str(payload.get("session_instance_id") or "").strip()
        if not instance_id:
            raise SessionBindingError("session_instance_id is required")
        role = str(payload.get("role") or "").strip()
        kind = str(payload.get("kind") or "").strip()
        if not role or not kind:
            raise SessionBindingError("session binding role and kind are required")
        state_raw = str(payload.get("state") or "unbound").strip()
        if state_raw not in {"unbound", "starting", "bound"}:
            raise SessionBindingError(f"unsupported session binding state: {state_raw!r}")
        provider_raw = payload.get("provider")
        provider = str(provider_raw).strip() if provider_raw is not None else None
        provider_session_raw = payload.get("provider_session_id")
        provider_session_id = (
            str(provider_session_raw).strip()
            if provider_session_raw is not None and str(provider_session_raw).strip()
            else None
        )
        model_raw = payload.get("model")
        model = (
            str(model_raw).strip()
            if model_raw is not None and str(model_raw).strip()
            else None
        )
        binding = cls(
            session_instance_id=instance_id,
            generation=int(payload.get("generation") or 1),
            role=role,
            kind=kind,
            state=state_raw,  # type: ignore[arg-type]
            provider=provider or None,
            provider_session_id=provider_session_id,
            model=model,
        )
        validate_session_binding(binding)
        return binding

    def with_next_generation(self) -> SessionBinding:
        return replace(
            self,
            generation=int(self.generation) + 1,
            state="starting",
            provider_session_id=None,
        )

    def with_provider_session_id(
        self,
        provider_session_id: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        allow_transient: bool = False,
    ) -> SessionBinding:
        resolved = str(provider_session_id).strip()
        if not resolved:
            raise SessionBindingError("provider_session_id is required")
        if not allow_transient and is_transient_provider_session_id(resolved):
            raise SessionBindingError(
                f"transient provider session id must not be persisted: {resolved!r}"
            )
        updated = replace(
            self,
            provider_session_id=resolved,
            state="bound" if not is_transient_provider_session_id(resolved) else "starting",
        )
        if provider is not None:
            updated = replace(updated, provider=str(provider).strip() or None)
        if model is not None:
            updated = replace(updated, model=str(model).strip() or None)
        validate_session_binding(updated)
        return updated


def new_session_binding(
    *,
    role: str,
    kind: str,
    provider: str | None = "cursor",
    generation: int = 1,
    model: str | None = None,
    state: SessionBindingState = "unbound",
) -> SessionBinding:
    binding = SessionBinding(
        session_instance_id=new_session_instance_id(),
        generation=int(generation),
        role=str(role).strip(),
        kind=str(kind).strip(),
        state=state,
        provider=str(provider).strip() if provider is not None else None,
        model=str(model).strip() if model is not None else None,
    )
    validate_session_binding(binding)
    return binding


def binding_from_legacy_provider_session_id(
    *,
    role: str,
    kind: str,
    provider_session_id: str | None,
    provider: str | None = "cursor",
    model: str | None = None,
) -> SessionBinding:
    binding = new_session_binding(
        role=role,
        kind=kind,
        provider=provider,
        model=model,
        state="unbound",
    )
    if provider_session_id is None or not str(provider_session_id).strip():
        return binding
    return binding.with_provider_session_id(
        str(provider_session_id).strip(),
        provider=provider,
        model=model,
        allow_transient=is_transient_provider_session_id(provider_session_id),
    )


def reviewer_binding_from_legacy_session_id(
    provider_session_id: str | None,
    *,
    provider: str | None = "cursor",
    model: str | None = None,
    instance_seed: str | None = None,
) -> SessionBinding | None:
    if provider_session_id is None or not str(provider_session_id).strip():
        return None
    binding = binding_from_legacy_provider_session_id(
        role="reviewer",
        kind="reviewer",
        provider_session_id=str(provider_session_id).strip(),
        provider=provider,
        model=model,
    )
    if instance_seed:
        from hashlib import sha256

        digest = sha256(instance_seed.encode("utf-8")).hexdigest()[:12]
        binding = replace(binding, session_instance_id=f"tdp-session-{digest}")
    return binding


def binding_provider_session_id(binding: SessionBinding | dict[str, Any] | None) -> str | None:
    if binding is None:
        return None
    if isinstance(binding, SessionBinding):
        return binding.provider_session_id
    if isinstance(binding, dict):
        raw = binding.get("provider_session_id")
        if raw is None or not str(raw).strip():
            return None
        return str(raw).strip()
    return None


def validate_session_binding(binding: SessionBinding) -> None:
    if binding.state == "bound":
        validate_durable_provider_session_id(binding.provider_session_id)
    elif binding.provider_session_id is not None and binding.state != "starting":
        if is_transient_provider_session_id(binding.provider_session_id):
            raise SessionBindingError(
                "transient provider session id is only allowed while state is starting"
            )


__all__ = [
    "LEGACY_PRIMARY_SESSION_FIELDS",
    "PRIMARY_PLANNER_SLOT",
    "PRIMARY_PRODUCER_SLOT",
    "SessionBinding",
    "SessionBindingError",
    "SessionBindingState",
    "SessionKind",
    "SessionRole",
    "binding_from_legacy_provider_session_id",
    "binding_provider_session_id",
    "is_transient_provider_session_id",
    "new_session_binding",
    "new_session_instance_id",
    "reviewer_binding_from_legacy_session_id",
    "validate_durable_provider_session_id",
    "validate_session_binding",
]
