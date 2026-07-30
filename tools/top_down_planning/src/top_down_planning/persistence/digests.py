"""TDP-specific digests for plan, config, and production binding."""

from __future__ import annotations

from typing import Any

from core_tools.persistence.digests import digest_json

from top_down_planning.domain.models import Plan

from top_down_planning.domain.production import build_production_digest_payload

__all__ = [
    "compute_config_digest",
    "compute_context_digest",
    "compute_output_digest",
    "compute_plan_digest",
]


def compute_plan_digest(plan: Plan | dict[str, Any]) -> str:
    """Deterministic digest of canonical plan content."""
    if isinstance(plan, Plan):
        payload = plan.to_dict()
    else:
        payload = plan
    return digest_json(payload)


def compute_config_digest(config: dict[str, Any]) -> str:
    return digest_json(config)


def compute_context_digest(context: dict[str, Any]) -> str:
    return digest_json(context)


def compute_output_digest(production: dict[str, Any]) -> str:
    """Deterministic digest of live production output (excludes invalidated reconciliation evidence)."""

    return digest_json(build_production_digest_payload(production))
