"""Canonical payload digests for review families and bindings."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def digest_canonical_payload(payload: Mapping[str, Any]) -> str:
    """Opaque digest for family fingerprints, value digests, and request digests."""

    normalized = _canonical_json(dict(payload)).replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
