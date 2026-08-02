"""TDP-specific digests for plan, config, and production binding."""

from __future__ import annotations

import copy
from typing import Any, Mapping

from core_tools.persistence.digests import digest_json

from top_down_planning.domain.digest import (
    digest_canonical_payload as _digest_canonical_payload,
)
from top_down_planning.domain.models import Plan

from top_down_planning.domain.production import build_production_digest_payload

__all__ = [
    "compute_config_contract_digest",
    "compute_config_execution_digest",
    "contract_config_projection",
    "digest_binding_payload",
    "digest_canonical_payload",
    "compute_output_digest",
    "compute_plan_digest",
    "execution_config_projection",
    "semantic_config_projection",
]

_INVOCATION_ONLY_CONFIG_KEYS = frozenset({"observability", "notifications"})
_EXECUTION_ONLY_TOP_LEVEL_KEYS = frozenset({"limits"})


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


def contract_config_projection(config: dict[str, Any]) -> dict[str, Any]:
    """Return approval-binding config projection (excludes execution limits)."""

    projected = semantic_config_projection(config)
    for key in _EXECUTION_ONLY_TOP_LEVEL_KEYS:
        projected.pop(key, None)
    return projected


def execution_config_projection(config: dict[str, Any]) -> dict[str, Any]:
    """Return execution-policy config projection (operational limits only)."""

    limits = config.get("limits")
    if not isinstance(limits, dict) or not limits:
        return {}
    return {"limits": copy.deepcopy(limits)}


def compute_plan_digest(plan: Plan | dict[str, Any]) -> str:
    """Deterministic digest of canonical plan content."""
    if isinstance(plan, Plan):
        payload = plan.to_dict()
    else:
        payload = plan
    return digest_json(payload)


def compute_config_contract_digest(config: dict[str, Any]) -> str:
    return digest_json(contract_config_projection(config))


def compute_config_execution_digest(config: dict[str, Any]) -> str:
    return digest_json(execution_config_projection(config))


def digest_binding_payload(payload: dict[str, Any]) -> str:
    """Deterministic digest of a canonical context spec or snapshot payload."""

    return digest_json(payload)


def digest_canonical_payload(payload: Mapping[str, Any]) -> str:
    """Re-export for persistence callers."""

    return _digest_canonical_payload(payload)


def compute_output_digest(production: dict[str, Any]) -> str:
    """Deterministic digest of live production output (excludes invalidated reconciliation evidence)."""

    return digest_json(build_production_digest_payload(production))
