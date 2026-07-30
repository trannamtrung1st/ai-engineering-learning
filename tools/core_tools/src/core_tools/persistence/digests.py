"""Stable SHA-256 digests for content binding."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def digest_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def digest_json(payload: Any) -> str:
    return digest_text(canonical_json(payload))
