"""Deterministic digests for execution packages (proposal §8.2)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from core_tools.persistence import digest_file
from core_tools.persistence.digests import digest_json

from top_down_planning.domain.digest import digest_canonical_payload
from top_down_planning.domain.models import Plan
from top_down_planning.domain.unit_plan import collect_assigned_item_ids
from top_down_planning.persistence.digests import compute_plan_digest


def digest_plan_file(path: Path) -> str:
    return digest_file(path)


def digest_manifest_content(manifest: dict[str, Any]) -> str:
    """Digest normalized manifest excluding package_digest."""

    normalized = copy.deepcopy(manifest)
    normalized.pop("package_digest", None)
    return digest_json(normalized)


def compute_package_digest(
    manifest: dict[str, Any],
    *,
    parent_plan_digest: str,
    unit_plan_digests: list[str],
    approved_plan_digest: str,
    context_digests: dict[str, str],
) -> str:
    payload = {
        "manifest": digest_manifest_content(manifest),
        "parent_plan_digest": parent_plan_digest,
        "unit_plan_digests": sorted(unit_plan_digests),
        "approved_plan_digest": approved_plan_digest,
        "context": dict(sorted(context_digests.items())),
    }
    return digest_json(payload)


def plan_digest_from_payload(plan_payload: dict[str, Any]) -> str:
    return compute_plan_digest(plan_payload)


def assigned_subtree_digest(plan: Plan, unit_root_id: str) -> str:
    assigned_ids = sorted(collect_assigned_item_ids(plan, unit_root_id))
    return digest_canonical_payload(
        {
            "assigned_root_item_id": unit_root_id,
            "assigned_item_ids": assigned_ids,
        }
    )


def unit_plan_digest(unit_plan: Plan) -> str:
    return compute_plan_digest(unit_plan)


__all__ = [
    "assigned_subtree_digest",
    "compute_package_digest",
    "digest_manifest_content",
    "digest_plan_file",
    "plan_digest_from_payload",
    "unit_plan_digest",
]
