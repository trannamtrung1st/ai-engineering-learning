"""TDP-specific digests for plan, config, and production binding."""

from __future__ import annotations

import copy
from typing import Any

from core_tools.persistence.digests import digest_json

from top_down_planning.domain.models import Plan

from top_down_planning.domain.production import build_production_digest_payload

__all__ = [
    "compute_config_digest",
    "compute_context_digest",
    "compute_output_digest",
    "compute_plan_digest",
    "semantic_config_projection",
]

_INVOCATION_ONLY_CONFIG_KEYS = frozenset({"observability"})


def semantic_config_projection(config: dict[str, Any]) -> dict[str, Any]:
    """Return config copy with invocation/presentation fields excluded from digests."""

    projected = copy.deepcopy(config)
    for key in _INVOCATION_ONLY_CONFIG_KEYS:
        projected.pop(key, None)
    runtime = projected.get("runtime")
    if isinstance(runtime, dict):
        runtime.pop("runs_dir", None)
        if not runtime:
            projected.pop("runtime", None)
    return projected


def compute_plan_digest(plan: Plan | dict[str, Any]) -> str:
    """Deterministic digest of canonical plan content."""
    if isinstance(plan, Plan):
        payload = plan.to_dict()
    else:
        payload = plan
    return digest_json(payload)


def compute_config_digest(config: dict[str, Any]) -> str:
    return digest_json(semantic_config_projection(config))


def compute_context_digest(context: dict[str, Any]) -> str:
    return digest_json(context)


def compute_output_digest(production: dict[str, Any]) -> str:
    """Deterministic digest of live production output (excludes invalidated reconciliation evidence)."""

    return digest_json(build_production_digest_payload(production))
