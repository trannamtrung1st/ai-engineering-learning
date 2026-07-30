"""Stable SHA-256 digests for resume and review binding (proposal §18)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from top_down_planning.domain.models import Plan


def digest_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def compute_plan_digest(plan: Plan | dict[str, Any]) -> str:
    """Deterministic digest of canonical plan content."""
    if isinstance(plan, Plan):
        payload = plan.to_dict()
    else:
        payload = plan
    return digest_text(_canonical_json(payload))


def compute_config_digest(config: dict[str, Any]) -> str:
    return digest_text(_canonical_json(config))


def compute_context_digest(context: dict[str, Any]) -> str:
    return digest_text(_canonical_json(context))


def compute_output_digest(production: dict[str, Any]) -> str:
    """Deterministic digest of production output state (excluding revision counters)."""

    payload = {
        "batches": production.get("batches") or [],
        "dispositions": production.get("dispositions") or {},
        "output_evidence": production.get("output_evidence") or [],
        "completion_claim": production.get("completion_claim"),
    }
    return digest_text(_canonical_json(payload))
